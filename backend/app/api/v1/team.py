from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, status
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep
from app.models.project import Project
from app.models.team import Allocation, Engineer
from app.schemas.entities import (
    AllocationCreate,
    AllocationRead,
    CapacityResponse,
    CapacityRow,
    EngineerCreate,
    EngineerRead,
)
from app.services.capacity import AllocationSpan, mondays, weekly_capacity

router = APIRouter()


@router.get("/engineers", response_model=list[EngineerRead])
async def list_engineers(session: SessionDep, _: CurrentUser) -> list[Engineer]:
    result = await session.execute(select(Engineer).order_by(Engineer.name))
    return list(result.scalars().all())


@router.post("/engineers", response_model=EngineerRead, status_code=status.HTTP_201_CREATED)
async def create_engineer(
    session: SessionDep, _: CurrentUser, payload: EngineerCreate
) -> Engineer:
    engineer = Engineer(**payload.model_dump())
    session.add(engineer)
    await session.commit()
    await session.refresh(engineer)
    return engineer


@router.get("/allocations", response_model=list[AllocationRead])
async def list_allocations(
    session: SessionDep, _: CurrentUser, project_id: int | None = None
) -> list[Allocation]:
    stmt = select(Allocation)
    if project_id is not None:
        stmt = stmt.where(Allocation.project_id == project_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.post("/allocations", response_model=AllocationRead, status_code=status.HTTP_201_CREATED)
async def create_allocation(
    session: SessionDep, _: CurrentUser, payload: AllocationCreate
) -> Allocation:
    allocation = Allocation(**payload.model_dump())
    session.add(allocation)
    await session.commit()
    await session.refresh(allocation)
    return allocation


@router.get("/capacity", response_model=CapacityResponse)
async def capacity(session: SessionDep, _: CurrentUser, project_id: int) -> CapacityResponse:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    allocations = list(
        (
            await session.execute(select(Allocation).where(Allocation.project_id == project_id))
        ).scalars().all()
    )
    engineers = {
        e.id: e.name
        for e in (await session.execute(select(Engineer))).scalars().all()
        if e.id is not None
    }

    spans = [
        AllocationSpan(a.engineer_id, a.percent_allocation, a.start_date, a.end_date)
        for a in allocations
    ]
    alloc_starts = [a.start_date for a in allocations if a.start_date]
    alloc_ends = [a.end_date for a in allocations if a.end_date]
    window_start = project.start_date or (min(alloc_starts) if alloc_starts else date.today())
    window_end = (
        project.target_date
        or (max(alloc_ends) if alloc_ends else window_start + timedelta(weeks=8))
    )

    grid = weekly_capacity(spans, window_start, window_end)
    weeks = [w.isoformat() for w in mondays(window_start, window_end)]
    rows = [
        CapacityRow(
            engineer_id=eng_id,
            engineer_name=engineers.get(eng_id, f"#{eng_id}"),
            cells={week.isoformat(): pct for week, pct in by_week.items()},
        )
        for eng_id, by_week in sorted(grid.items())
    ]
    return CapacityResponse(project_id=project_id, weeks=weeks, rows=rows)
