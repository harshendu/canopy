from fastapi import APIRouter, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, func, select

from app.api.deps import CurrentUser, SessionDep
from app.connectors import get_connector
from app.connectors.gdrive import GoogleDriveConnector
from app.connectors.github import GitHubConnector
from app.models.architecture import (
    ADRComment,
    ADRComponentLink,
    ADRStakeholder,
    ArchitectureComponent,
    ArchitectureDecision,
    ComponentLink,
)
from app.models.base import ADRCommentKind, ADRStatus, DecisionRule
from app.models.integration import Connection
from app.models.project import Project
from app.schemas.entities import (
    ADRCommentCreate,
    ADRCommentRead,
    ADRCreate,
    ADRDetail,
    ADRImportRequest,
    ADRRead,
    ADRUpdate,
    ComponentCreate,
    ComponentLinkCreate,
    ComponentLinkRead,
    ComponentRead,
    ImpactResponse,
    ReviewSummaryRead,
)
from app.services.decisions import review_summary, valid_transition
from app.services.impact import downstream_components
from app.services.markdown_adr import parse_markdown_adr

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
    for cid in dict.fromkeys(component_ids):  # dedupe, keep order
        session.add(ADRComponentLink(adr_id=adr_id, component_id=cid))


async def _set_stakeholders(
    session: AsyncSession, adr_id: int, engineer_ids: list[int]
) -> None:
    existing = await session.execute(
        select(ADRStakeholder).where(ADRStakeholder.adr_id == adr_id)
    )
    for row in existing.scalars().all():
        await session.delete(row)
    for eid in dict.fromkeys(engineer_ids):  # dedupe, keep order
        session.add(ADRStakeholder(adr_id=adr_id, engineer_id=eid))


async def _component_ids(session: AsyncSession, adr_id: int) -> list[int]:
    rows = await session.execute(
        select(ADRComponentLink.component_id).where(ADRComponentLink.adr_id == adr_id)
    )
    return list(rows.scalars().all())


async def _stakeholder_ids(session: AsyncSession, adr_id: int) -> list[int]:
    rows = await session.execute(
        select(ADRStakeholder.engineer_id).where(ADRStakeholder.adr_id == adr_id)
    )
    return list(rows.scalars().all())


def _adr_read(
    adr: ArchitectureDecision, component_ids: list[int], stakeholder_ids: list[int]
) -> ADRRead:
    assert adr.id is not None
    return ADRRead(
        id=adr.id,
        project_id=adr.project_id,
        number=adr.number,
        title=adr.title,
        status=adr.status,
        context=adr.context,
        decision=adr.decision,
        consequences=adr.consequences,
        alternatives=adr.alternatives,
        reversibility=adr.reversibility,
        decision_owner_id=adr.decision_owner_id,
        proposed_by_id=adr.proposed_by_id,
        decide_by=adr.decide_by,
        rfc_url=adr.rfc_url,
        supersedes_id=adr.supersedes_id,
        pr_links=adr.pr_links,
        component_ids=component_ids,
        stakeholder_ids=stakeholder_ids,
    )


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
    stakeholders_by_adr: dict[int, list[int]] = {}
    if adr_ids:
        links = (
            await session.execute(
                select(ADRComponentLink).where(col(ADRComponentLink.adr_id).in_(adr_ids))
            )
        ).scalars().all()
        for link in links:
            links_by_adr.setdefault(link.adr_id, []).append(link.component_id)
        stakeholders = (
            await session.execute(
                select(ADRStakeholder).where(col(ADRStakeholder.adr_id).in_(adr_ids))
            )
        ).scalars().all()
        for row in stakeholders:
            stakeholders_by_adr.setdefault(row.adr_id, []).append(row.engineer_id)

    return [
        _adr_read(a, links_by_adr.get(a.id, []), stakeholders_by_adr.get(a.id, []))
        for a in adrs
        if a.id is not None
    ]


async def _next_number(session: AsyncSession, project_id: int) -> int:
    result = await session.execute(
        select(func.max(ArchitectureDecision.number)).where(
            ArchitectureDecision.project_id == project_id
        )
    )
    return (result.scalar() or 0) + 1


@router.post("/adrs", response_model=ADRRead, status_code=status.HTTP_201_CREATED)
async def create_adr(session: SessionDep, _: CurrentUser, payload: ADRCreate) -> ADRRead:
    if payload.status == ADRStatus.deferred and payload.decide_by is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A deferred ADR needs a decide_by date",
        )
    data = payload.model_dump(exclude={"component_ids", "stakeholder_ids"})
    adr = ArchitectureDecision(number=await _next_number(session, payload.project_id), **data)
    session.add(adr)
    await session.flush()
    assert adr.id is not None  # guaranteed after flush
    await _set_component_links(session, adr.id, payload.component_ids)
    await _set_stakeholders(session, adr.id, payload.stakeholder_ids)
    await session.commit()
    await session.refresh(adr)
    return _adr_read(
        adr,
        list(dict.fromkeys(payload.component_ids)),
        list(dict.fromkeys(payload.stakeholder_ids)),
    )


@router.post("/adrs/import", response_model=ADRRead, status_code=status.HTTP_201_CREATED)
async def import_adr(
    session: SessionDep, _: CurrentUser, payload: ADRImportRequest
) -> ArchitectureDecision:
    """Read a markdown doc from GitHub/Drive and create an ADR from its sections."""
    connection = await session.get(Connection, payload.connection_id)
    if connection is None or connection.provider != payload.provider:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Bad connection")
    connector = get_connector(connection, session)
    if isinstance(connector, GitHubConnector):
        text = await connector.read_file(payload.ref)
    elif isinstance(connector, GoogleDriveConnector):
        text = await connector.export_doc(payload.ref)
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported provider")

    fields = parse_markdown_adr(text, fallback_title=payload.ref.rsplit("/", 1)[-1])
    adr = ArchitectureDecision(
        project_id=payload.project_id,
        number=await _next_number(session, payload.project_id),
        title=fields["title"] or payload.ref,
        context=fields["context"],
        decision=fields["decision"],
        consequences=fields["consequences"],
    )
    session.add(adr)
    await session.commit()
    await session.refresh(adr)
    return adr


@router.get("/adrs/{adr_id}/impact", response_model=ImpactResponse)
async def adr_impact(session: SessionDep, _: CurrentUser, adr_id: int) -> ImpactResponse:
    """Components an ADR directly affects, plus everything that transitively depends on them."""
    adr = await session.get(ArchitectureDecision, adr_id)
    if adr is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ADR not found")
    direct = set(
        (
            await session.execute(
                select(ADRComponentLink.component_id).where(ADRComponentLink.adr_id == adr_id)
            )
        ).scalars().all()
    )
    project_components = set(
        (
            await session.execute(
                select(ArchitectureComponent.id).where(
                    ArchitectureComponent.project_id == adr.project_id
                )
            )
        ).scalars().all()
    )
    all_links = (await session.execute(select(ComponentLink))).scalars().all()
    edges = [
        (link.source_id, link.target_id)
        for link in all_links
        if link.source_id in project_components or link.target_id in project_components
    ]
    downstream = downstream_components(direct, edges)
    return ImpactResponse(
        adr_id=adr_id,
        direct_component_ids=sorted(direct),
        downstream_component_ids=sorted(downstream),
    )


@router.get("/adrs/{adr_id}", response_model=ADRDetail)
async def get_adr(session: SessionDep, _: CurrentUser, adr_id: int) -> ADRDetail:
    """Full ADR with its comment thread and a stakeholder-review summary."""
    adr = await session.get(ArchitectureDecision, adr_id)
    if adr is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ADR not found")
    component_ids = await _component_ids(session, adr_id)
    stakeholder_ids = await _stakeholder_ids(session, adr_id)
    comments = list(
        (
            await session.execute(
                select(ADRComment)
                .where(ADRComment.adr_id == adr_id)
                .order_by(col(ADRComment.id))
            )
        ).scalars().all()
    )
    # Each stakeholder's most recent review action (plain comments don't count).
    latest: dict[int, ADRCommentKind] = {}
    for c in comments:
        if c.engineer_id is not None and c.kind != ADRCommentKind.comment:
            latest[c.engineer_id] = c.kind
    project = await session.get(Project, adr.project_id)
    rule = project.decision_rule if project else DecisionRule.owner_decides
    summary = review_summary(stakeholder_ids, latest, rule)
    base = _adr_read(adr, component_ids, stakeholder_ids)
    return ADRDetail(
        **base.model_dump(),
        comments=[ADRCommentRead.model_validate(c) for c in comments],
        review=ReviewSummaryRead.model_validate(summary, from_attributes=True),
    )


@router.post(
    "/adrs/{adr_id}/comments",
    response_model=ADRCommentRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_adr_comment(
    session: SessionDep, _: CurrentUser, adr_id: int, payload: ADRCommentCreate
) -> ADRComment:
    """Post to an ADR's thread. A non-``comment`` kind is a formal review action
    (approve / request_changes / reject) that feeds the stakeholder-review summary."""
    adr = await session.get(ArchitectureDecision, adr_id)
    if adr is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ADR not found")
    comment = ADRComment(
        adr_id=adr_id,
        body=payload.body,
        kind=payload.kind,
        engineer_id=payload.engineer_id,
        author_name=payload.author_name,
    )
    session.add(comment)
    await session.commit()
    await session.refresh(comment)
    return comment


@router.patch("/adrs/{adr_id}", response_model=ADRRead)
async def update_adr(
    session: SessionDep, _: CurrentUser, adr_id: int, payload: ADRUpdate
) -> ADRRead:
    adr = await session.get(ArchitectureDecision, adr_id)
    if adr is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ADR not found")
    data = payload.model_dump(exclude_unset=True, exclude={"component_ids", "stakeholder_ids"})

    new_status = data.get("status", adr.status)
    if "status" in data and not valid_transition(adr.status, new_status):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot move an ADR from {adr.status} to {new_status}",
        )
    new_decide_by = data.get("decide_by", adr.decide_by)
    if new_status == ADRStatus.deferred and new_decide_by is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A deferred ADR needs a decide_by date",
        )

    for field, value in data.items():
        setattr(adr, field, value)
    if payload.component_ids is not None:
        await _set_component_links(session, adr_id, payload.component_ids)
    if payload.stakeholder_ids is not None:
        await _set_stakeholders(session, adr_id, payload.stakeholder_ids)
    await session.commit()
    await session.refresh(adr)
    return _adr_read(
        adr,
        await _component_ids(session, adr_id),
        await _stakeholder_ids(session, adr_id),
    )
