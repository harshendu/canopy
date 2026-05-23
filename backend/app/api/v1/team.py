from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, status
from sqlmodel import select

from app.api.deps import CurrentUser, PlannerWriter, SessionDep
from app.models.project import Project
from app.models.team import Allocation, Engineer, Role
from app.schemas.entities import (
    AllocationCreate,
    AllocationRead,
    CapacityResponse,
    CapacityRow,
    EngineerCreate,
    EngineerRead,
    EngineerUpdate,
    RoleCreate,
    RoleRead,
)
from app.services.capacity import AllocationSpan, mondays, weekly_capacity

router = APIRouter()


@router.get("/roles", response_model=list[RoleRead])
async def list_roles(session: SessionDep, _: CurrentUser) -> list[Role]:
    result = await session.execute(select(Role).order_by(Role.name))
    return list(result.scalars().all())


@router.post("/roles", response_model=RoleRead, status_code=status.HTTP_201_CREATED)
async def create_role(session: SessionDep, _: PlannerWriter, payload: RoleCreate) -> Role:
    role = Role(name=payload.name)
    session.add(role)
    await session.commit()
    await session.refresh(role)
    return role


@router.get("/engineers", response_model=list[EngineerRead])
async def list_engineers(session: SessionDep, _: CurrentUser) -> list[Engineer]:
    result = await session.execute(select(Engineer).order_by(Engineer.name))
    return list(result.scalars().all())


@router.post("/engineers", response_model=EngineerRead, status_code=status.HTTP_201_CREATED)
async def create_engineer(
    session: SessionDep, _: PlannerWriter, payload: EngineerCreate
) -> Engineer:
    engineer = Engineer(**payload.model_dump())
    session.add(engineer)
    await session.commit()
    await session.refresh(engineer)
    return engineer


@router.patch("/engineers/{engineer_id}", response_model=EngineerRead)
async def update_engineer(
    session: SessionDep, _: PlannerWriter, engineer_id: int, payload: EngineerUpdate
) -> Engineer:
    engineer = await session.get(Engineer, engineer_id)
    if engineer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Engineer not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(engineer, field, value)
    await session.commit()
    await session.refresh(engineer)
    return engineer


@router.delete("/engineers/{engineer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_engineer(session: SessionDep, _: PlannerWriter, engineer_id: int) -> None:
    engineer = await session.get(Engineer, engineer_id)
    if engineer is not None:
        await session.delete(engineer)
        await session.commit()


@router.delete("/allocations/{allocation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_allocation(session: SessionDep, _: PlannerWriter, allocation_id: int) -> None:
    allocation = await session.get(Allocation, allocation_id)
    if allocation is not None:
        await session.delete(allocation)
        await session.commit()


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
    session: SessionDep, _: PlannerWriter, payload: AllocationCreate
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
