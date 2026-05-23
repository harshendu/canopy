from fastapi import APIRouter, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, func, select

from app.api.deps import CurrentUser, SessionDep
from app.models.architecture import (
    ADRComponentLink,
    ArchitectureComponent,
    ArchitectureDecision,
    ComponentLink,
)
from app.schemas.entities import (
    ADRCreate,
    ADRRead,
    ADRUpdate,
    ComponentCreate,
    ComponentLinkCreate,
    ComponentLinkRead,
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


# --- Component links (system-map edges) ---
@router.get("/component-links", response_model=list[ComponentLinkRead])
async def list_component_links(
    session: SessionDep, _: CurrentUser, project_id: int | None = None
) -> list[ComponentLink]:
    if project_id is None:
        result = await session.execute(select(ComponentLink))
        return list(result.scalars().all())
    component_ids = set(
        (
            await session.execute(
                select(ArchitectureComponent.id).where(
                    ArchitectureComponent.project_id == project_id
                )
            )
        ).scalars().all()
    )
    result = await session.execute(select(ComponentLink))
    return [
        link
        for link in result.scalars().all()
        if link.source_id in component_ids or link.target_id in component_ids
    ]


@router.post(
    "/component-links", response_model=ComponentLinkRead, status_code=status.HTTP_201_CREATED
)
async def create_component_link(
    session: SessionDep, _: CurrentUser, payload: ComponentLinkCreate
) -> ComponentLink:
    if payload.source_id == payload.target_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Self-link")
    link = ComponentLink(**payload.model_dump())
    session.add(link)
    await session.commit()
    await session.refresh(link)
    return link


@router.delete("/component-links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_component_link(session: SessionDep, _: CurrentUser, link_id: int) -> None:
    link = await session.get(ComponentLink, link_id)
    if link is not None:
        await session.delete(link)
        await session.commit()


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
) -> list[ADRRead]:
    stmt = select(ArchitectureDecision)
    if project_id is not None:
        stmt = stmt.where(ArchitectureDecision.project_id == project_id)
    adrs = list(
        (await session.execute(stmt.order_by(col(ArchitectureDecision.number)))).scalars().all()
    )
    adr_ids = [a.id for a in adrs if a.id is not None]
    links_by_adr: dict[int, list[int]] = {}
    if adr_ids:
        links = (
            await session.execute(
                select(ADRComponentLink).where(col(ADRComponentLink.adr_id).in_(adr_ids))
            )
        ).scalars().all()
        for link in links:
            links_by_adr.setdefault(link.adr_id, []).append(link.component_id)

    out: list[ADRRead] = []
    for a in adrs:
        if a.id is None:
            continue
        out.append(
            ADRRead(
                id=a.id,
                project_id=a.project_id,
                number=a.number,
                title=a.title,
                status=a.status,
                context=a.context,
                decision=a.decision,
                consequences=a.consequences,
                supersedes_id=a.supersedes_id,
                pr_links=a.pr_links,
                component_ids=links_by_adr.get(a.id, []),
            )
        )
    return out


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
