"""Blockers: flagged impediments on tasks — the leading signal that work has stalled.

Any contributor (engineer or planner) can raise one; the engineer who raises it is recorded
(defaulting to the caller's linked engineer). Open blockers surface in the engineer workspace
(§M), the project's alerts digest (§I/Q), and a project Blockers panel."""

from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from sqlmodel import col, select

from app.api.deps import ContributorWriter, CurrentUser, PlannerWriter, SessionDep, current_engineer
from app.models.project import Blocker, Task
from app.schemas.entities import BlockerCreate, BlockerRead, BlockerUpdate

router = APIRouter()


@router.post(
    "/tasks/{task_id}/blockers", response_model=BlockerRead, status_code=status.HTTP_201_CREATED
)
async def raise_blocker(
    session: SessionDep, user: ContributorWriter, task_id: int, payload: BlockerCreate
) -> Blocker:
    task = await session.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    raised_by = payload.raised_by_engineer_id
    if raised_by is None:
        engineer = await current_engineer(session, user)
        raised_by = engineer.id if engineer is not None else None
    blocker = Blocker(
        task_id=task_id,
        reason=payload.reason,
        raised_by_engineer_id=raised_by,
        blocking_task_id=payload.blocking_task_id,
        category=payload.category,
        severity=payload.severity,
        owner_engineer_id=payload.owner_engineer_id,
        needed_by=payload.needed_by,
    )
    session.add(blocker)
    await session.commit()
    await session.refresh(blocker)
    return blocker


@router.get("/tasks/{task_id}/blockers", response_model=list[BlockerRead])
async def list_task_blockers(
    session: SessionDep, _: CurrentUser, task_id: int
) -> list[Blocker]:
    rows = await session.execute(
        select(Blocker).where(Blocker.task_id == task_id).order_by(col(Blocker.id).desc())
    )
    return list(rows.scalars().all())


@router.get("/blockers", response_model=list[BlockerRead])
async def list_blockers(
    session: SessionDep,
    _: CurrentUser,
    project_id: int | None = None,
    open_only: bool = True,
) -> list[Blocker]:
    """Blockers, newest first. Filter to a project's tasks and/or open (unresolved) ones."""
    stmt = select(Blocker)
    if open_only:
        stmt = stmt.where(col(Blocker.resolved_at).is_(None))
    if project_id is not None:
        task_ids = (
            await session.execute(select(Task.id).where(Task.project_id == project_id))
        ).scalars().all()
        stmt = stmt.where(col(Blocker.task_id).in_(set(task_ids)))
    rows = await session.execute(stmt.order_by(col(Blocker.id).desc()))
    return list(rows.scalars().all())


@router.patch("/blockers/{blocker_id}", response_model=BlockerRead)
async def update_blocker(
    session: SessionDep, _: ContributorWriter, blocker_id: int, payload: BlockerUpdate
) -> Blocker:
    blocker = await session.get(Blocker, blocker_id)
    if blocker is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Blocker not found")
    data = payload.model_dump(exclude_unset=True)
    if payload.resolved is not None:
        blocker.resolved_at = datetime.utcnow() if payload.resolved else None
    # `resolved` is a derived flag (not a column), so apply the rest field-by-field.
    for field in ("reason", "category", "severity", "owner_engineer_id", "needed_by"):
        if field in data:
            setattr(blocker, field, data[field])
    await session.commit()
    await session.refresh(blocker)
    return blocker


@router.delete("/blockers/{blocker_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_blocker(session: SessionDep, _: PlannerWriter, blocker_id: int) -> None:
    blocker = await session.get(Blocker, blocker_id)
    if blocker is not None:
        await session.delete(blocker)
        await session.commit()
