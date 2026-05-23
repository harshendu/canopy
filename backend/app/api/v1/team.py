from fastapi import APIRouter, status
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep
from app.models.team import Allocation, Engineer
from app.schemas.entities import (
    AllocationCreate,
    AllocationRead,
    EngineerCreate,
    EngineerRead,
)

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
