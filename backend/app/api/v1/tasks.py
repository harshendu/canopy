from fastapi import APIRouter, HTTPException, status
from sqlmodel import col, select

from app.api.deps import (
    ContributorWriter,
    CurrentUser,
    PlannerWriter,
    SessionDep,
    current_engineer,
    is_planner,
)
from app.core.events import publish
from app.models.base import TaskType
from app.models.project import Project, Task, TaskStatusHistory
from app.models.user import User
from app.schemas.entities import (
    TaskCreate,
    TaskExternalLinksRead,
    TaskMoveRequest,
    TaskMoveResponse,
    TaskRead,
    TaskStatusHistoryRead,
    TaskUpdate,
)
from app.services.access import (
    ensure_project_editable,
    ensure_task_editable,
    project_can_edit,
)
from app.services.access import (
    ensure_project_editable as ensure_initiative_editable_for_project,
)
from app.services.cascade import delete_task_cascade
from app.services.features import feature_enabled
from app.services.links import collect_task_links, external_urls
from app.services.metadata import normalize_tags
from app.services.workflow import TrackingError, initialise_native_task
from app.services.workflow import move_task as workflow_move

router = APIRouter()


@router.get("", response_model=list[TaskRead])
async def list_tasks(
    session: SessionDep, _: CurrentUser, project_id: int | None = None
) -> list[Task]:
    stmt = select(Task)
    if project_id is not None:
        stmt = stmt.where(Task.project_id == project_id)
    result = await session.execute(stmt.order_by(col(Task.id)))
    return list(result.scalars().all())


def actor_name(user: User) -> str:
    """How a person appears in status history (`TaskStatusHistory.author`)."""
    return user.full_name or user.email


def _tracking_http_error(exc: TrackingError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail())


@router.post("", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
async def create_task(session: SessionDep, user: PlannerWriter, payload: TaskCreate) -> Task:
    await ensure_project_editable(session, user, payload.project_id)
    data = payload.model_dump(exclude={"status"})
    data["tags"] = normalize_tags(data.get("tags") or [])
    task = Task(**data)
    session.add(task)
    await session.flush()
    try:
        # Its key and its first status (a workflow column, else the first `todo` column) —
        # recorded as a transition like every status write.
        await initialise_native_task(
            session,
            task,
            status=payload.status,
            native_enabled=await feature_enabled(session, "tracking.native"),
            author=actor_name(user),
        )
    except TrackingError as exc:
        await session.rollback()
        raise _tracking_http_error(exc) from exc
    await session.commit()
    await session.refresh(task)
    await publish({"type": "board", "project_id": task.project_id, "task_id": task.id})
    return task


@router.get("/{task_id}", response_model=TaskRead)
async def get_task(session: SessionDep, _: CurrentUser, task_id: int) -> Task:
    task = await session.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return task


@router.get("/{task_id}/links", response_model=TaskExternalLinksRead)
async def get_task_links(
    session: SessionDep, _: CurrentUser, task_id: int
) -> TaskExternalLinksRead:
    """A task's external resource links: its Jira issue, the GitHub PRs implementing it, and the
    design docs (GitHub/Drive) scoped to it. Canopy links out; it never stores the resources."""
    task = await session.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return await collect_task_links(session, task_id)


@router.get("/{task_id}/history", response_model=list[TaskStatusHistoryRead])
async def get_task_history(
    session: SessionDep, _: CurrentUser, task_id: int
) -> list[TaskStatusHistory]:
    result = await session.execute(
        select(TaskStatusHistory)
        .where(TaskStatusHistory.task_id == task_id)
        .order_by(col(TaskStatusHistory.changed_at))
    )
    return list(result.scalars().all())


@router.patch("/{task_id}", response_model=TaskRead)
async def update_task(
    session: SessionDep, user: ContributorWriter, task_id: int, payload: TaskUpdate
) -> Task:
    task = await session.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    # Planners edit tasks inside the initiatives they lead; an engineer only their own tasks.
    await ensure_initiative_editable_for_project(session, user, task.project_id)
    if not is_planner(user):
        engineer = await current_engineer(session, user)
        if engineer is None or task.assignee_engineer_id != engineer.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Engineers may only edit tasks assigned to them",
            )
    data = payload.model_dump(exclude_unset=True)
    if "tags" in data and data["tags"] is not None:
        data["tags"] = normalize_tags(data["tags"])
    for field, value in data.items():
        setattr(task, field, value)
    await session.commit()
    await session.refresh(task)
    return task


async def _own_card_rules(
    session: SessionDep, user: User, task: Task, payload: TaskMoveRequest
) -> int | None:
    """Without planning rights on the project, a contributor moves their own cards, or pulls an
    unassigned one into another column (which assigns it to them — reordering it alone does
    not). Returns the engineer to assign on a pull."""
    engineer = await current_engineer(session, user)
    if engineer is None or engineer.id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Link your login to an engineer profile to move cards",
        )
    if task.assignee_engineer_id == engineer.id:
        return None
    if task.assignee_engineer_id is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Engineers may only move their own cards or pull an unassigned one",
        )
    changing = payload.to_status is not None and payload.to_status.strip().casefold() != (
        task.status or ""
    ).casefold()
    if not changing:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Pull an unassigned card by moving it to another column; reordering it "
            "doesn't take it",
        )
    return engineer.id  # pulling unassigned work assigns it to you


@router.post("/{task_id}/move", response_model=TaskMoveResponse)
async def move_task(
    session: SessionDep, user: ContributorWriter, task_id: int, payload: TaskMoveRequest
) -> TaskMoveResponse:
    """Move a card on the board: change its status (canopy-owned tasks only — a mirrored task's
    status belongs to its tracker: 409 `status_externally_owned`) and/or its place in the
    column. The one status write path for people and agents: every change is recorded in the
    task's history. Planners move any card in projects they may edit; an engineer moves their
    own cards, or pulls an unassigned one (which assigns it to them). WIP limits warn or block
    per the workflow's enforcement."""
    task = await session.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    if task.type == TaskType.summary:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "not_a_card", "message": "Summary tasks (phases) are not cards"},
        )
    pull_for: int | None = None
    project = await session.get(Project, task.project_id)
    planner_ok = (
        is_planner(user) and project is not None and await project_can_edit(session, user, project)
    )
    if not planner_ok:
        # Engineer rules — also for a planner outside this project (their own cards still move).
        try:
            pull_for = await _own_card_rules(session, user, task, payload)
        except HTTPException:
            if is_planner(user):
                await ensure_project_editable(session, user, task.project_id)  # says why
            raise
    try:
        outcome = await workflow_move(
            session,
            task,
            to_status=payload.to_status,
            after_task_id=payload.after_task_id,
            before_task_id=payload.before_task_id,
            position=payload.position,
            expected_status=payload.expected_status,
            author=actor_name(user),
            native_enabled=await feature_enabled(session, "tracking.native"),
        )
    except TrackingError as exc:
        await session.rollback()
        if exc.code == "status_externally_owned":
            urls = await external_urls(session, [task_id])
            exc.extra["url"] = urls.get(task_id)
        raise _tracking_http_error(exc) from exc
    if pull_for is not None:
        task.assignee_engineer_id = pull_for
    await session.commit()
    await session.refresh(task)
    await publish({"type": "board", "project_id": task.project_id, "task_id": task.id})
    return TaskMoveResponse(
        task=TaskRead.model_validate(task), changed=outcome.changed, warnings=outcome.warnings
    )


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(session: SessionDep, user: PlannerWriter, task_id: int) -> None:
    await ensure_task_editable(session, user, task_id)
    # Clear FK-referencing rows first (deps, history, blockers, allocations, PR/scenario refs)
    # and promote children — a bare delete 500s on Postgres/MySQL for any linked task.
    await delete_task_cascade(session, task_id)
    await session.commit()
