"""Document graph + design docs: typed *links* to documents that live elsewhere (Claude docs and
artifacts, Jira epics, Drive, Figma, repo files), their links to the work they serve, the kind
catalog, and a coverage report. Canopy links, it never stores — see
`app/services/doc_graph.py` and `app/services/design_docs.py` (USER_FLOWS §V).

Permissions live in the service: a planner who may edit a doc's home, the contributor who
registered it, or — for a personal doc — its owner alone. Personal docs are invisible to
everyone else, including an impersonating admin.
"""

from typing import Any

from fastapi import APIRouter, HTTPException, Response, status

from app.api.deps import (
    AdminUser,
    CurrentUser,
    Impersonator,
    PlannerWriter,
    SessionDep,
    TokenScopeDep,
)
from app.core.events import publish
from app.models.base import (
    DocLinkEntity,
    DocProvider,
    DocScope,
    DocSource,
    DocStage,
    DocVisibility,
    TokenScope,
)
from app.models.doc import DocLink, DocReference
from app.models.user import User
from app.schemas.docs import (
    DesignDocRead,
    DocKindMergeIn,
    DocKindMergeOut,
    DocKindRead,
    DocKindUpdateIn,
    DocLinkIn,
    DocLinkRead,
    DocLinkUpdateIn,
    DocPromoteIn,
    DocRegisterIn,
    DocRegisterOut,
    EntityDocRead,
)
from app.schemas.entities import (
    DocCoverageRead,
    DocReferenceCreate,
    DocReferenceRead,
    DocReferenceUpdate,
)
from app.services import design_docs, doc_graph, doc_kinds, doc_views
from app.services.design_docs import DocError, DocQuery, LinkSpec, RegisterInput

router = APIRouter()


def _http(exc: DocError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}
    )


async def _changed(doc: DocReference | None = None) -> None:
    event: dict[str, Any] = {"type": "docs"}
    if doc is not None:
        event.update(
            doc_id=doc.id,
            scope_level=doc.scope_level.value if doc.scope_level else None,
            scope_id=doc.scope_id,
        )
    await publish(event)


# --- list / legacy add / coverage --------------------------------------------------------


@router.get("/docs", response_model=list[DesignDocRead])
async def list_docs(
    session: SessionDep,
    user: CurrentUser,
    impersonator: Impersonator,
    scope_level: DocScope | None = None,
    scope_id: int | None = None,
    kind: str | None = None,
    stage: DocStage | None = None,
    provider: DocProvider | None = None,
    review_status: str | None = None,
    personal: bool | None = None,
    entity_type: DocLinkEntity | None = None,
    entity_id: int | None = None,
) -> list[DesignDocRead]:
    """Docs the caller may see, newest first. A scope filter returns docs homed there *and*
    docs linked to that same entity. `review_status=untracked` lists plain links."""
    stage_kinds: list[str] | None = None
    if stage is not None:
        catalog = await doc_kinds.load_catalog(session)
        stage_kinds = [k for k, info in catalog.items() if info.stage == stage.value]
    docs = await design_docs.list_docs(
        session,
        user,
        DocQuery(
            scope_level=scope_level,
            scope_id=scope_id,
            kind=kind,
            provider=provider.value if provider else None,
            review_status=review_status,
            personal=personal,
            entity_type=entity_type,
            entity_id=entity_id,
            stage_kinds=stage_kinds,
        ),
        impersonator,
    )
    return await doc_views.design_doc_reads(session, docs)


@router.post("/docs", response_model=DocReferenceRead, status_code=status.HTTP_201_CREATED)
async def create_doc(
    session: SessionDep, user: CurrentUser, payload: DocReferenceCreate
) -> DocReference:
    """Add a plain link at a scope (the Docs tab's form). A document already tracked is not
    duplicated: the scope gets a link to the existing record."""
    try:
        await design_docs.ensure_home_writable(
            session, user, payload.scope_level, payload.scope_id
        )
        info = design_docs.classify(payload.url, strict=False)
        await design_docs.require_shareable(session, info, payload.visibility, payload.title)
        result = await design_docs.register_core(
            session,
            info=info,
            kind=payload.kind,
            title=payload.title,
            scope_level=payload.scope_level,
            scope_id=payload.scope_id,
            source=DocSource.manual,
            created_by=user.id,
            visibility=payload.visibility,
            owner_engineer_id=payload.owner_engineer_id,
        )
    except DocError as exc:
        raise _http(exc) from exc
    await session.commit()
    await session.refresh(result.doc)
    await _changed(result.doc)
    return result.doc


@router.post("/docs/register", response_model=DocRegisterOut)
async def register_doc(
    session: SessionDep,
    user: CurrentUser,
    scope: TokenScopeDep,
    payload: DocRegisterIn,
    response: Response,
) -> DocRegisterOut:
    """Track a Claude doc, artifact or any other design document: identity, kind, format,
    version and a short summary — never the content. Idempotent per document: a second
    registration returns the existing record (200) and adds any requested links."""
    data = RegisterInput(
        url=payload.url,
        title=payload.title,
        kind=payload.kind,
        format=payload.format,
        summary=payload.summary,
        version=payload.version,
        content_hash=payload.content_hash,
        visibility=payload.visibility,
        personal=payload.personal,
        scope_level=payload.scope_level,
        scope_id=payload.scope_id,
        owner_engineer_id=payload.owner_engineer_id,
        track=payload.track,
        supersedes_id=payload.supersedes_id,
        links=[LinkSpec(s.entity_type, s.entity_id, s.relation) for s in payload.links],
    )
    source = DocSource.agent if scope == TokenScope.agent else DocSource.manual
    try:
        result = await design_docs.register(session, user, data, source=source)
    except DocError as exc:
        raise _http(exc) from exc
    await session.commit()
    await session.refresh(result.doc)
    response.status_code = status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
    await _changed(result.doc)
    return DocRegisterOut(
        doc=await doc_views.design_doc_read(session, result.doc), created=result.created
    )


@router.get("/docs/coverage", response_model=DocCoverageRead)
async def docs_coverage(
    session: SessionDep, _: CurrentUser, scope_level: DocScope, scope_id: int
) -> dict:
    """Which expected doc kinds are present vs missing for a scope (rolled up: a project
    includes its tasks; an initiative includes its projects and their tasks; docs linked there
    count too)."""
    return await doc_graph.coverage(session, scope_level, scope_id)


# --- kind catalog --------------------------------------------------------------------------


async def _kind_reads(session: SessionDep) -> list[DocKindRead]:
    rows = {r.key: r for r in await doc_kinds.catalog_rows(session)}
    counts = await doc_kinds.usage_counts(session)
    catalog = await doc_kinds.load_catalog(session)
    out = []
    for order, (key, info) in enumerate(catalog.items()):
        row = rows.get(key)
        out.append(
            DocKindRead(
                key=key,
                label=info.label,
                stage=info.stage,
                expected=info.expected,
                builtin=row.builtin if row is not None else key in doc_kinds.BUILTIN_KEYS,
                sort_order=row.sort_order if row is not None else 1000 + order,
                doc_count=counts.get(key, 0),
            )
        )
    # kinds in use that the catalog never saw (rows written before the catalog existed)
    for key, count in sorted(counts.items()):
        if key not in catalog:
            info = doc_kinds.fallback_info(key)
            out.append(DocKindRead(key=key, label=info.label, stage=info.stage, expected=False,
                                   builtin=False, sort_order=2000, doc_count=count))
    return out


@router.get("/docs/kinds", response_model=list[DocKindRead])
async def list_kinds(session: SessionDep, _: CurrentUser) -> list[DocKindRead]:
    """The workspace kind catalog: label, lifecycle stage and expected flag per kind, with how
    many docs use each. Any kind is allowed; unknown kinds join under stage `other`."""
    return await _kind_reads(session)


@router.put("/docs/kinds/{key}", response_model=DocKindRead)
async def update_kind(
    session: SessionDep, _: PlannerWriter, key: str, payload: DocKindUpdateIn
) -> DocKindRead:
    row = await doc_kinds.update_kind(
        session,
        key,
        label=payload.label,
        stage=payload.stage,
        expected=payload.expected,
        sort_order=payload.sort_order,
    )
    await session.commit()
    await _changed()
    return next(k for k in await _kind_reads(session) if k.key == row.key)


@router.post("/docs/kinds/{key}/merge", response_model=DocKindMergeOut)
async def merge_kind(
    session: SessionDep, _: AdminUser, key: str, payload: DocKindMergeIn
) -> DocKindMergeOut:
    """Fold one kind into another (every doc of `key` takes `into`). Admin only."""
    try:
        merged = await doc_kinds.merge_kind(session, key, payload.into)
    except doc_kinds.KindMergeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_merge", "message": str(exc)},
        ) from exc
    await session.commit()
    await _changed()
    return DocKindMergeOut(merged=merged, into=doc_kinds.normalize_slug(payload.into))


# --- links -------------------------------------------------------------------------------


@router.get("/docs/links", response_model=list[EntityDocRead])
async def docs_for_entity(
    session: SessionDep,
    user: CurrentUser,
    impersonator: Impersonator,
    entity_type: DocLinkEntity,
    entity_id: int,
) -> list[EntityDocRead]:
    """The docs linked to one entity (an ADR, a spec, a task, a milestone…) with each link's
    relation and pinned version."""
    pairs = await design_docs.docs_for_entity(
        session, user, entity_type, entity_id, impersonator
    )
    return await doc_views.entity_doc_reads(session, pairs)


async def _link_or_404(session: SessionDep, link_id: int) -> DocLink:
    link = await session.get(DocLink, link_id)
    if link is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "Link not found"},
        )
    return link


@router.patch("/docs/links/{link_id}", response_model=DocLinkRead)
async def update_link(
    session: SessionDep, user: CurrentUser, link_id: int, payload: DocLinkUpdateIn
) -> DocLinkRead:
    link = await _link_or_404(session, link_id)
    try:
        updated = await design_docs.update_link(
            session, user, link, relation=payload.relation, pinned_version=payload.pinned_version
        )
    except DocError as exc:
        raise _http(exc) from exc
    await session.commit()
    await session.refresh(updated)
    await _changed()
    return DocLinkRead.model_validate(updated)


@router.delete("/docs/links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_link(session: SessionDep, user: CurrentUser, link_id: int) -> None:
    link = await _link_or_404(session, link_id)
    try:
        await design_docs.unlink(session, user, link)
    except DocError as exc:
        raise _http(exc) from exc
    await session.commit()
    await _changed()


# --- one doc -----------------------------------------------------------------------------


async def _visible(
    session: SessionDep, user: User, doc_id: int, impersonator: User | None = None
) -> DocReference:
    try:
        return await design_docs.get_visible_doc(session, user, doc_id, impersonator)
    except DocError as exc:
        raise _http(exc) from exc


@router.get("/docs/{doc_id}", response_model=DesignDocRead)
async def get_doc(
    session: SessionDep, user: CurrentUser, impersonator: Impersonator, doc_id: int
) -> DesignDocRead:
    """One doc with its links (and, from the review layer, its versions and health)."""
    doc = await _visible(session, user, doc_id, impersonator)
    return await doc_views.design_doc_read(session, doc)


@router.patch("/docs/{doc_id}", response_model=DesignDocRead)
async def update_doc(
    session: SessionDep, user: CurrentUser, doc_id: int, payload: DocReferenceUpdate
) -> DesignDocRead:
    doc = await _visible(session, user, doc_id)
    try:
        await design_docs.ensure_doc_writable(session, user, doc)
        changes = payload.model_dump(exclude_unset=True)
        if changes.get("url"):
            info = design_docs.classify(changes.pop("url"), strict=False)
            doc.url, doc.provider, doc.external_id = (
                info.url, info.provider.value, info.external_id
            )
        if changes.get("kind"):
            doc.kind = await doc_kinds.ensure_kind(session, changes.pop("kind"))
        if "visibility" in changes and changes["visibility"] is not None:
            doc.visibility = DocVisibility(changes.pop("visibility")).value
        for field, value in changes.items():
            if field == "format" and value:
                value = doc_kinds.normalize_slug(value, max_length=doc_kinds.FORMAT_MAX)
            setattr(doc, field, value)
        design_docs.touch(doc)
    except DocError as exc:
        raise _http(exc) from exc
    await session.commit()
    await session.refresh(doc)
    await _changed(doc)
    return await doc_views.design_doc_read(session, doc)


@router.delete("/docs/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_doc(session: SessionDep, user: CurrentUser, doc_id: int) -> None:
    try:
        doc = await design_docs.get_visible_doc(session, user, doc_id)
    except DocError:
        return  # deleting what you cannot see (or what is gone) is a no-op
    try:
        await design_docs.delete_doc(session, user, doc)
    except DocError as exc:
        raise _http(exc) from exc
    await session.commit()
    await _changed()


@router.post(
    "/docs/{doc_id}/links", response_model=DocLinkRead, status_code=status.HTTP_201_CREATED
)
async def link_doc(
    session: SessionDep, user: CurrentUser, doc_id: int, payload: DocLinkIn
) -> DocLinkRead:
    """Link a doc to an entity it serves. `basis` pins the doc's current version (a later
    version raises an alert); `gate` marks work that should wait for approval; `reference` is
    context. Idempotent per doc + entity."""
    doc = await _visible(session, user, doc_id)
    try:
        link = await design_docs.link_doc(
            session, user, doc, payload.entity_type, payload.entity_id,
            payload.relation, payload.pinned_version,
        )
    except DocError as exc:
        raise _http(exc) from exc
    await session.commit()
    await session.refresh(link)
    await _changed(doc)
    labels = await design_docs.entity_labels(session, [(link.entity_type, link.entity_id)])
    read = DocLinkRead.model_validate(link)
    read.label = labels.get((link.entity_type, link.entity_id))
    return read


@router.post("/docs/{doc_id}/promote", response_model=DesignDocRead)
async def promote_doc(
    session: SessionDep, user: CurrentUser, doc_id: int, payload: DocPromoteIn
) -> DesignDocRead:
    """Share a personal doc with the team: file it under a home scope. A Claude doc must be
    shared in Claude first (409 `doc_not_shared`)."""
    doc = await _visible(session, user, doc_id)
    try:
        promoted = await design_docs.promote(
            session, user, doc, scope_level=payload.scope_level, scope_id=payload.scope_id,
            visibility=payload.visibility,
        )
    except DocError as exc:
        raise _http(exc) from exc
    await session.commit()
    await session.refresh(promoted)
    await _changed(promoted)
    return await doc_views.design_doc_read(session, promoted)

