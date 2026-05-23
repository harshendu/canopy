from fastapi import APIRouter, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, func, select

from app.api.deps import CurrentUser, SessionDep
from app.models.architecture import (
    ADRComponentLink,
    ArchitectureComponent,
    ArchitectureDecision,
)
from app.schemas.entities import (
    ADRCreate,
    ADRRead,
    ADRUpdate,
    ComponentCreate,
    ComponentRead,
)

router = APIRouter()


# --- Components ---
@router.get("/components", response_model=list[ComponentRead])
async def list_components(
    session: SessionDep, _: CurrentUser, project_id: int | None = None
) -> list[ArchitectureComponent]:
    stmt = select(ArchitectureComponent)
    if project_id is not None:
        stmt = stmt.where(ArchitectureComponent.project_id == project_id)
    result = await session.execute(stmt.order_by(ArchitectureComponent.name))
    return list(result.scalars().all())


@router.post("/components", response_model=ComponentRead, status_code=status.HTTP_201_CREATED)
async def create_component(
    session: SessionDep, _: CurrentUser, payload: ComponentCreate
) -> ArchitectureComponent:
    component = ArchitectureComponent(**payload.model_dump())
    session.add(component)
    await session.commit()
    await session.refresh(component)
    return component


# --- ADRs ---
async def _set_component_links(
    session: AsyncSession, adr_id: int, component_ids: list[int]
) -> None:
    existing = await session.execute(
        select(ADRComponentLink).where(ADRComponentLink.adr_id == adr_id)
    )
    for link in existing.scalars().all():
        await session.delete(link)
    for cid in component_ids:
        session.add(ADRComponentLink(adr_id=adr_id, component_id=cid))


@router.get("/adrs", response_model=list[ADRRead])
async def list_adrs(
    session: SessionDep, _: CurrentUser, project_id: int | None = None
) -> list[ArchitectureDecision]:
    stmt = select(ArchitectureDecision)
    if project_id is not None:
        stmt = stmt.where(ArchitectureDecision.project_id == project_id)
    result = await session.execute(stmt.order_by(col(ArchitectureDecision.number)))
    return list(result.scalars().all())


@router.post("/adrs", response_model=ADRRead, status_code=status.HTTP_201_CREATED)
async def create_adr(
    session: SessionDep, _: CurrentUser, payload: ADRCreate
) -> ArchitectureDecision:
    max_number = await session.execute(
        select(func.max(ArchitectureDecision.number)).where(
            ArchitectureDecision.project_id == payload.project_id
        )
    )
    next_number = (max_number.scalar() or 0) + 1
    data = payload.model_dump(exclude={"component_ids"})
    adr = ArchitectureDecision(number=next_number, **data)
    session.add(adr)
    await session.flush()
    assert adr.id is not None  # guaranteed after flush
    await _set_component_links(session, adr.id, payload.component_ids)
    await session.commit()
    await session.refresh(adr)
    return adr


@router.patch("/adrs/{adr_id}", response_model=ADRRead)
async def update_adr(
    session: SessionDep, _: CurrentUser, adr_id: int, payload: ADRUpdate
) -> ArchitectureDecision:
    adr = await session.get(ArchitectureDecision, adr_id)
    if adr is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ADR not found")
    data = payload.model_dump(exclude_unset=True, exclude={"component_ids"})
    for field, value in data.items():
        setattr(adr, field, value)
    if payload.component_ids is not None and adr.id is not None:
        await _set_component_links(session, adr.id, payload.component_ids)
    await session.commit()
    await session.refresh(adr)
    return adr
