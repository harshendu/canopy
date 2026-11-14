"""Draft plans: stage a proposed plan, review it, then finalise it into real work.

Drafts live apart from the live schedule (the Gantt/CPM/board never see them). Finalising
(`/finalize`) creates canopy tasks in a native project, or writes ticket **content** to the
project's tracker (summary/description/story points) — never status — in a mirrored one; the
next sync pulls the new items back as canopy tasks. Writes are planner-gated; finalising is
human-only.
"""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import delete as sa_delete
from sqlalchemy import update as sa_update
from sqlmodel import col, select

from app.api.deps import CurrentUser, HumanOnly, PlannerWriter, SessionDep
from app.core.events import publish
from app.models.draft import DraftPlan, DraftTask
from app.models.project import Project
from app.schemas.entities import (
    DraftFinalizeRequest,
    DraftFinalizeResult,
    DraftPlanCreate,
    DraftPlanDetail,
    DraftPlanRead,
    DraftPlanUpdate,
    DraftRecordPushRequest,
    DraftRecordPushResult,
    DraftTaskCreate,
    DraftTaskRead,
    DraftTaskUpdate,
)
from app.services import draft_sync
from app.services.access import ensure_project_editable

router = APIRouter()


async def _get_plan(session: SessionDep, plan_id: int) -> DraftPlan:
    plan = await session.get(DraftPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft plan not found")
    return plan


@router.get("/projects/{project_id}/draft-plans", response_model=list[DraftPlanRead])
async def list_draft_plans(
    session: SessionDep, _: CurrentUser, project_id: int
) -> list[DraftPlan]:
    rows = await session.execute(
        select(DraftPlan)
        .where(DraftPlan.project_id == project_id)
        .order_by(col(DraftPlan.id).desc())
    )
    return list(rows.scalars().all())


@router.post(
    "/projects/{project_id}/draft-plans",
    response_model=DraftPlanRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_draft_plan(
    session: SessionDep, user: PlannerWriter, project_id: int, payload: DraftPlanCreate
) -> DraftPlan:
    if await session.get(Project, project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    await ensure_project_editable(session, user, project_id)
    plan = DraftPlan(project_id=project_id, **payload.model_dump())
    session.add(plan)
    await session.commit()
    await session.refresh(plan)
    await publish({"type": "draft_plan", "project_id": project_id})
    return plan


@router.get("/draft-plans/{plan_id}", response_model=DraftPlanDetail)
async def get_draft_plan(session: SessionDep, _: CurrentUser, plan_id: int) -> DraftPlanDetail:
    plan = await _get_plan(session, plan_id)
    rows = await session.execute(
        select(DraftTask)
        .where(DraftTask.plan_id == plan_id)
        .order_by(col(DraftTask.sort_order), col(DraftTask.id))
    )
    tasks = [DraftTaskRead.model_validate(t) for t in rows.scalars().all()]
    return DraftPlanDetail(**DraftPlanRead.model_validate(plan).model_dump(), tasks=tasks)


@router.patch("/draft-plans/{plan_id}", response_model=DraftPlanRead)
async def update_draft_plan(
    session: SessionDep, user: PlannerWriter, plan_id: int, payload: DraftPlanUpdate
) -> DraftPlan:
    plan = await _get_plan(session, plan_id)
    await ensure_project_editable(session, user, plan.project_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(plan, field, value)
    await session.commit()
    await session.refresh(plan)
    return plan


@router.delete("/draft-plans/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_draft_plan(session: SessionDep, user: PlannerWriter, plan_id: int) -> None:
    plan = await session.get(DraftPlan, plan_id)
    if plan is None:
        return
    await ensure_project_editable(session, user, plan.project_id)
    # Clear the self-referential parent links first, then bulk-delete: Postgres/MySQL enforce
    # the parent_id FK (SQLite does not), so per-row deletes could drop a parent before its
    # child. Nulling parents removes that ordering hazard.
    await session.execute(
        sa_update(DraftTask).where(col(DraftTask.plan_id) == plan_id).values(parent_id=None)
    )
    await session.execute(sa_delete(DraftTask).where(col(DraftTask.plan_id) == plan_id))
    await session.delete(plan)
    await session.commit()


@router.post(
    "/draft-plans/{plan_id}/tasks",
    response_model=DraftTaskRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_draft_task(
    session: SessionDep, user: PlannerWriter, plan_id: int, payload: DraftTaskCreate
) -> DraftTask:
    plan = await _get_plan(session, plan_id)
    await ensure_project_editable(session, user, plan.project_id)
    task = DraftTask(plan_id=plan_id, **payload.model_dump())
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


@router.patch("/draft-tasks/{task_id}", response_model=DraftTaskRead)
async def update_draft_task(
    session: SessionDep, user: PlannerWriter, task_id: int, payload: DraftTaskUpdate
) -> DraftTask:
    task = await session.get(DraftTask, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft task not found")
    plan = await _get_plan(session, task.plan_id)
    await ensure_project_editable(session, user, plan.project_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(task, field, value)
    await session.commit()
    await session.refresh(task)
    return task


@router.delete("/draft-tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_draft_task(session: SessionDep, user: PlannerWriter, task_id: int) -> None:
    task = await session.get(DraftTask, task_id)
    if task is not None:
        plan = await _get_plan(session, task.plan_id)
        await ensure_project_editable(session, user, plan.project_id)
    if task is not None:
        # Detach any child tasks first (parent_id FK is enforced on Postgres/MySQL).
        await session.execute(
            sa_update(DraftTask).where(col(DraftTask.parent_id) == task_id).values(parent_id=None)
        )
        await session.delete(task)
        await session.commit()


@router.post("/draft-plans/{plan_id}/finalize", response_model=DraftFinalizeResult)
async def finalize_draft_plan(
    session: SessionDep,
    user: PlannerWriter,
    __: HumanOnly,
    plan_id: int,
    payload: DraftFinalizeRequest,
) -> DraftFinalizeResult:
    """Turn a reviewed plan into real work, following the project's tracking mode: a native
    project gets canopy tasks (keys, first statuses, parents, then a replan); a mirrored project
    pushes the content to its bound tracker (never status — the next sync brings the items
    back). Human-only in every mode: a draft plan exists so a person reviews work before it
    becomes real."""
    existing = await session.get(DraftPlan, plan_id)  # a missing plan is draft_sync's 400
    if existing is not None:
        await ensure_project_editable(session, user, existing.project_id)
    try:
        return await draft_sync.finalize_plan(
            session,
            plan_id,
            connection_id=payload.connection_id,
            user_id=user.id,
            author=user.full_name or user.email,
        )
    except draft_sync.DraftWriteBlockedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except draft_sync.DraftPushError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/draft-plans/{plan_id}/record-push", response_model=DraftRecordPushResult)
async def record_draft_push(
    session: SessionDep, user: PlannerWriter, plan_id: int, payload: DraftRecordPushRequest
) -> DraftRecordPushResult:
    """Write-back for `write_strategy=mcp`: Claude created the tracker items itself; record
    their ids here so re-pushing is idempotent and the plan flips to synced. Internal write —
    allowed for agent-scope tokens (no `HumanOnly` gate), unlike finalising above."""
    existing = await session.get(DraftPlan, plan_id)
    if existing is not None:
        await ensure_project_editable(session, user, existing.project_id)
    try:
        return await draft_sync.record_external_push(session, plan_id, payload.results)
    except draft_sync.DraftPushError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
