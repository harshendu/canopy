"""Draft plans: stage a proposed plan, review it, then create/update Jira tickets from it.

Drafts live apart from the live schedule (the Gantt/CPM/board never see them). Pushing a
plan writes ticket **content** to Jira (summary/description/story points) — never status;
the next Jira sync pulls the new issues back as canopy tasks. Writes are planner-gated.
"""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import delete as sa_delete
from sqlalchemy import update as sa_update
from sqlmodel import col, select

from app.api.deps import CurrentUser, HumanOnly, PlannerWriter, SessionDep
from app.core.events import publish
from app.models.base import Provider
from app.models.draft import DraftPlan, DraftTask
from app.models.project import Project
from app.schemas.entities import (
    DraftPlanCreate,
    DraftPlanDetail,
    DraftPlanRead,
    DraftPlanUpdate,
    DraftPushRequest,
    DraftPushResult,
    DraftTaskCreate,
    DraftTaskRead,
    DraftTaskUpdate,
)
from app.services import draft_sync, integration_policy

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
    session: SessionDep, _: PlannerWriter, project_id: int, payload: DraftPlanCreate
) -> DraftPlan:
    if await session.get(Project, project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
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
    session: SessionDep, _: PlannerWriter, plan_id: int, payload: DraftPlanUpdate
) -> DraftPlan:
    plan = await _get_plan(session, plan_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(plan, field, value)
    await session.commit()
    await session.refresh(plan)
    return plan


@router.delete("/draft-plans/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_draft_plan(session: SessionDep, _: PlannerWriter, plan_id: int) -> None:
    plan = await session.get(DraftPlan, plan_id)
    if plan is None:
        return
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
    session: SessionDep, _: PlannerWriter, plan_id: int, payload: DraftTaskCreate
) -> DraftTask:
    await _get_plan(session, plan_id)
    task = DraftTask(plan_id=plan_id, **payload.model_dump())
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


@router.patch("/draft-tasks/{task_id}", response_model=DraftTaskRead)
async def update_draft_task(
    session: SessionDep, _: PlannerWriter, task_id: int, payload: DraftTaskUpdate
) -> DraftTask:
    task = await session.get(DraftTask, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft task not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(task, field, value)
    await session.commit()
    await session.refresh(task)
    return task


@router.delete("/draft-tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_draft_task(session: SessionDep, _: PlannerWriter, task_id: int) -> None:
    task = await session.get(DraftTask, task_id)
    if task is not None:
        # Detach any child tasks first (parent_id FK is enforced on Postgres/MySQL).
        await session.execute(
            sa_update(DraftTask).where(col(DraftTask.parent_id) == task_id).values(parent_id=None)
        )
        await session.delete(task)
        await session.commit()


@router.post("/draft-plans/{plan_id}/push-to-jira", response_model=DraftPushResult)
async def push_draft_to_jira(
    session: SessionDep, _: PlannerWriter, __: HumanOnly, plan_id: int, payload: DraftPushRequest
) -> DraftPushResult:
    write = await integration_policy.resolve_write(session, Provider.jira)
    if not write.allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=write.reason)
    try:
        return await draft_sync.push_plan_to_jira(session, plan_id, payload.connection_id)
    except draft_sync.DraftPushError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
