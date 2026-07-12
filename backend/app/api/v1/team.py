from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, status
from sqlmodel import col, select

from app.api.deps import CurrentUser, FeatureGate, PlannerWriter, SessionDep
from app.models.project import Project
from app.models.team import Allocation, Engineer, EngineerAvailability, Role
from app.schemas.entities import (
    AllocationCreate,
    AllocationRead,
    AvailabilityCreate,
    AvailabilityRead,
    AvailabilityUpdate,
    CapacityResponse,
    CapacityRow,
    EngineerCreate,
    EngineerRead,
    EngineerUpdate,
    RoleCreate,
    RoleRead,
)
from app.services.capacity import (
    AllocationSpan,
    AvailabilitySpan,
    mondays,
    weekly_availability,
    weekly_capacity,
)

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


@router.get(
    "/capacity",
    response_model=CapacityResponse,
    dependencies=[FeatureGate("tracking.capacity")],
)
async def capacity(
    session: SessionDep, _: CurrentUser, project_id: int | None = None
) -> CapacityResponse:
    # Single project: scope to its allocations and prefer its date window. Org-wide
    # (project_id omitted): sum every allocation per engineer so cross-project
    # over-allocation — invisible per-project — surfaces.
    default_start: date | None = None
    default_end: date | None = None
    if project_id is not None:
        project = await session.get(Project, project_id)
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        stmt = select(Allocation).where(Allocation.project_id == project_id)
        default_start, default_end = project.start_date, project.target_date
    else:
        stmt = select(Allocation)
    allocations = list((await session.execute(stmt)).scalars().all())

    engineers = {
        e.id: e.name
        for e in (await session.execute(select(Engineer))).scalars().all()
        if e.id is not None
    }
    project_keys = {
        p.id: p.key
        for p in (await session.execute(select(Project))).scalars().all()
        if p.id is not None
    }

    spans = [
        AllocationSpan(a.engineer_id, a.percent_allocation, a.start_date, a.end_date)
        for a in allocations
    ]
    alloc_starts = [a.start_date for a in allocations if a.start_date]
    alloc_ends = [a.end_date for a in allocations if a.end_date]
    window_start = default_start or (min(alloc_starts) if alloc_starts else date.today())
    window_end = default_end or (
        max(alloc_ends) if alloc_ends else window_start + timedelta(weeks=8)
    )

    grid = weekly_capacity(spans, window_start, window_end)
    weeks = [w.isoformat() for w in mondays(window_start, window_end)]

    # Per-engineer availability (PTO/ramp-up) reduces the effective ceiling — surface the
    # factor so the heatmap can shade weeks where someone is partially out.
    avail_rows = list((await session.execute(select(EngineerAvailability))).scalars().all())
    avail_grid = weekly_availability(
        [
            AvailabilitySpan(a.engineer_id, a.capacity_factor, a.start_date, a.end_date)
            for a in avail_rows
        ],
        window_start,
        window_end,
    )

    projects_by_engineer: dict[int, set[str]] = {}
    for a in allocations:
        if a.project_id is not None and a.project_id in project_keys:
            projects_by_engineer.setdefault(a.engineer_id, set()).add(project_keys[a.project_id])

    rows = [
        CapacityRow(
            engineer_id=eng_id,
            engineer_name=engineers.get(eng_id, f"#{eng_id}"),
            cells={week.isoformat(): pct for week, pct in by_week.items()},
            projects=sorted(projects_by_engineer.get(eng_id, set())),
            availability={
                week.isoformat(): factor
                for week, factor in avail_grid.get(eng_id, {}).items()
            },
        )
        for eng_id, by_week in sorted(grid.items())
    ]
    return CapacityResponse(project_id=project_id, weeks=weeks, rows=rows)


@router.get("/availability", response_model=list[AvailabilityRead])
async def list_availability(
    session: SessionDep, _: CurrentUser, engineer_id: int | None = None
) -> list[EngineerAvailability]:
    stmt = select(EngineerAvailability)
    if engineer_id is not None:
        stmt = stmt.where(EngineerAvailability.engineer_id == engineer_id)
    result = await session.execute(stmt.order_by(col(EngineerAvailability.start_date)))
    return list(result.scalars().all())


@router.post(
    "/availability", response_model=AvailabilityRead, status_code=status.HTTP_201_CREATED
)
async def create_availability(
    session: SessionDep, _: PlannerWriter, payload: AvailabilityCreate
) -> EngineerAvailability:
    availability = EngineerAvailability(**payload.model_dump())
    session.add(availability)
    await session.commit()
    await session.refresh(availability)
    return availability


@router.patch("/availability/{availability_id}", response_model=AvailabilityRead)
async def update_availability(
    session: SessionDep, _: PlannerWriter, availability_id: int, payload: AvailabilityUpdate
) -> EngineerAvailability:
    availability = await session.get(EngineerAvailability, availability_id)
    if availability is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Availability not found"
        )
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(availability, field, value)
    await session.commit()
    await session.refresh(availability)
    return availability


@router.delete("/availability/{availability_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_availability(
    session: SessionDep, _: PlannerWriter, availability_id: int
) -> None:
    availability = await session.get(EngineerAvailability, availability_id)
    if availability is not None:
        await session.delete(availability)
        await session.commit()
