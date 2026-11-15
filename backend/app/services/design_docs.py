"""Design docs: the session-driven layer over the document graph (USER_FLOWS §V5-§V8).

A Claude session (or a person in the Docs tab) **registers** a document it made or found —
canopy stores the link, its identity at the source (`provider` + `external_id`), a version
label and a short summary, never the content — and **links** it to every entity it serves.
One document is one `DocReference` row however many places use it.

Rules enforced here, not in the routes:

* **Visibility.** A *personal* doc (`private_to_user_id`) is returned only to its owner — not
  to an admin, and not to an admin impersonating the owner. Every doc read goes through
  `visible_clause`.
* **The sharing rule.** A Claude doc joins the shared graph — registered as shared, promoted,
  linked, put up for review or approved — only once it is shared in Claude (`visibility`
  users | org | public). Otherwise 409 `doc_not_shared`. Other providers keep today's
  behaviour (canopy does not track their sharing).
* **Who may write.** A planner who may edit the doc's home scope (`app/services/access.py`); a
  contributor for a doc they registered; anyone for their own personal doc. A link's target
  must be something the caller may edit — a planner's scope, or an engineer's own task — so
  one doc can serve two projects without either team editing the other's plan.

The harvest and proposal apply call `register_core` directly (no per-user checks: the
harvest is planner-gated and proposal apply is a human applying a reviewed change).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import ColumnElement, and_, delete, false, or_, true, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.core.config import settings
from app.models.architecture import ArchitectureComponent, ArchitectureDecision
from app.models.base import (
    SHARED_VISIBILITIES,
    DocFormat,
    DocLinkEntity,
    DocLinkHealth,
    DocProvider,
    DocRelation,
    DocReviewStatus,
    DocScope,
    DocSource,
    DocVisibility,
    UserRole,
    utcnow,
)
from app.models.doc import DocLink, DocReference, DocRevision
from app.models.draft import DraftPlan
from app.models.outcome import Outcome
from app.models.project import Initiative, Milestone, Project, Task
from app.models.proposal import Proposal
from app.models.retro import Retrospective
from app.models.risk_register import RiskItem
from app.models.spec import Spec
from app.models.user import User
from app.services import access
from app.services.doc_health import HealthDoc, HealthFlag, HealthLink, doc_health
from app.services.doc_kinds import FORMAT_MAX, ensure_kind, normalize_slug
from app.services.doc_urls import DocUrlError, DocUrlInfo, classify_doc_url, same_document_key

TITLE_MAX = 255  # `title` is VARCHAR(255) on MySQL
SUMMARY_MAX = 2000
VERSION_MAX = 64

PLANNER_ROLES = frozenset(
    {UserRole.architect, UserRole.engineering_manager, UserRole.member}
)


class DocError(Exception):
    """A refused design-doc operation, mapped by the routes to `{code, message}`."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _not_found(what: str = "Document") -> DocError:
    return DocError(404, "not_found", f"{what} not found")


def _not_shared(doc_title: str | None) -> DocError:
    name = f"'{doc_title}'" if doc_title else "This doc"
    return DocError(
        409,
        "doc_not_shared",
        f"{name} is private in Claude. Share it with your organization (or the people who "
        "need it) in Claude, then record its new visibility before it joins shared work.",
    )


# --- visibility -----------------------------------------------------------------------


def visible_clause(user: User, impersonator: User | None = None) -> ColumnElement[bool]:
    """Shared docs, plus the user's own personal docs (none while impersonated)."""
    shared = col(DocReference.private_to_user_id).is_(None)
    if impersonator is not None or user.id is None:
        return shared
    return or_(shared, col(DocReference.private_to_user_id) == user.id)


def is_personal(doc: DocReference) -> bool:
    return doc.private_to_user_id is not None


def shared_at_source(doc: DocReference) -> bool:
    """Whether the doc may back shared work: always for providers whose sharing canopy does
    not track; for a Claude doc, only once it is shared in Claude."""
    if doc.provider != DocProvider.claude.value:
        return True
    return doc.visibility in {v.value for v in SHARED_VISIBILITIES}


def require_shared(doc: DocReference) -> None:
    if not shared_at_source(doc):
        raise _not_shared(doc.title)


async def require_shareable(
    session: AsyncSession, info: DocUrlInfo, visibility: DocVisibility, title: str | None
) -> None:
    """The sharing rule at registration: a Claude doc filed as shared must be shared in Claude
    — unless the same document is already tracked as shared (someone shared it)."""
    if info.provider != DocProvider.claude or visibility in SHARED_VISIBILITIES:
        return
    if await find_by_identity(session, info, shared_only=True) is None:
        raise _not_shared(title)


async def get_visible_doc(
    session: AsyncSession, user: User, doc_id: int, impersonator: User | None = None
) -> DocReference:
    doc = await session.get(DocReference, doc_id)
    if doc is None:
        raise _not_found()
    if doc.private_to_user_id is not None and (
        impersonator is not None or doc.private_to_user_id != user.id
    ):
        raise _not_found()  # a personal doc does not exist for anyone else
    return doc


# --- permissions ----------------------------------------------------------------------


def _role(user: User) -> UserRole:
    return UserRole(user.role)


async def _own_task(session: AsyncSession, user: User, task: Task) -> bool:
    if task.assignee_engineer_id is None:
        return False
    return task.assignee_engineer_id in await access.engineer_ids_for_user(session, user)


async def ensure_home_writable(
    session: AsyncSession, user: User, scope_level: DocScope, scope_id: int
) -> None:
    """May this user file a shared doc under this home scope? Planners per ownership; a
    contributor under any project (or their own task); viewers never."""
    await _require_scope(session, scope_level, scope_id)
    role = _role(user)
    if role == UserRole.admin:
        return
    if role in PLANNER_ROLES:
        if scope_level == DocScope.initiative:
            await access.ensure_initiative_editable(session, user, scope_id)
        elif scope_level == DocScope.project:
            await access.ensure_project_editable(session, user, scope_id)
        else:
            await access.ensure_task_editable(session, user, scope_id)
        return
    if role == UserRole.engineer:
        if scope_level == DocScope.project:
            return
        if scope_level == DocScope.task:
            task = await session.get(Task, scope_id)
            if task is not None and await _own_task(session, user, task):
                return
        raise DocError(
            403,
            "contributor_scope",
            "Contributors file docs under a project or their own task; ask a planner to file "
            "it under an initiative.",
        )
    raise DocError(403, "read_only", "Viewers can track personal docs only.")


async def ensure_doc_writable(session: AsyncSession, user: User, doc: DocReference) -> None:
    """May this user change this doc (metadata, links, versions, review requests)?"""
    if doc.private_to_user_id is not None:
        if doc.private_to_user_id != user.id:
            raise _not_found()
        return
    role = _role(user)
    if role == UserRole.admin:
        return
    if role in PLANNER_ROLES:
        if doc.scope_level is None or doc.scope_id is None:
            return
        if doc.scope_level == DocScope.initiative:
            await access.ensure_initiative_editable(session, user, doc.scope_id)
        elif doc.scope_level == DocScope.project:
            await access.ensure_project_editable(session, user, doc.scope_id)
        else:
            await access.ensure_task_editable(session, user, doc.scope_id)
        return
    if role == UserRole.engineer and doc.created_by_user_id == user.id:
        return
    raise DocError(
        403,
        "not_doc_owner",
        "Only a planner on this doc's home, or the contributor who registered it, can change it.",
    )


async def _require_scope(session: AsyncSession, scope_level: DocScope, scope_id: int) -> None:
    model: type[Task] | type[Project] | type[Initiative]
    if scope_level == DocScope.task:
        model = Task
    elif scope_level == DocScope.project:
        model = Project
    else:
        model = Initiative
    if await session.get(model, scope_id) is None:
        raise DocError(404, "not_found", f"{scope_level.value} {scope_id} not found")


@dataclass
class EntityRef:
    """Where a linkable entity sits: its project and/or initiative, plus a display label."""

    entity_type: DocLinkEntity
    entity_id: int
    label: str
    project_id: int | None = None
    initiative_id: int | None = None
    task: Task | None = None


async def resolve_entity(
    session: AsyncSession, entity_type: DocLinkEntity, entity_id: int
) -> EntityRef:
    """Load a link target and work out the project / initiative that governs it (404 if
    missing)."""
    missing = _not_found(entity_type.value.capitalize())
    if entity_type == DocLinkEntity.project:
        project = await session.get(Project, entity_id)
        if project is None:
            raise missing
        return EntityRef(entity_type, entity_id, project.name, project_id=entity_id,
                         initiative_id=project.initiative_id)
    if entity_type == DocLinkEntity.initiative:
        initiative = await session.get(Initiative, entity_id)
        if initiative is None:
            raise missing
        return EntityRef(entity_type, entity_id, initiative.name, initiative_id=entity_id)
    if entity_type == DocLinkEntity.task:
        task = await session.get(Task, entity_id)
        if task is None:
            raise missing
        label = f"{task.key} {task.name}" if task.key else task.name
        return EntityRef(entity_type, entity_id, label, project_id=task.project_id, task=task)
    if entity_type == DocLinkEntity.decision:
        adr = await session.get(ArchitectureDecision, entity_id)
        if adr is None:
            raise missing
        return EntityRef(entity_type, entity_id, f"ADR-{adr.number:04d} {adr.title}",
                         project_id=adr.project_id)
    if entity_type == DocLinkEntity.spec:
        spec = await session.get(Spec, entity_id)
        if spec is None:
            raise missing
        return EntityRef(entity_type, entity_id, spec.title, project_id=spec.project_id)
    if entity_type == DocLinkEntity.milestone:
        milestone = await session.get(Milestone, entity_id)
        if milestone is None:
            raise missing
        return EntityRef(entity_type, entity_id, milestone.name, project_id=milestone.project_id)
    if entity_type == DocLinkEntity.retro:
        retro = await session.get(Retrospective, entity_id)
        if retro is None:
            raise missing
        return EntityRef(entity_type, entity_id, retro.title, project_id=retro.project_id)
    if entity_type == DocLinkEntity.component:
        component = await session.get(ArchitectureComponent, entity_id)
        if component is None:
            raise missing
        return EntityRef(entity_type, entity_id, component.name, project_id=component.project_id)
    if entity_type == DocLinkEntity.outcome:
        outcome = await session.get(Outcome, entity_id)
        if outcome is None:
            raise missing
        statement = outcome.statement if len(outcome.statement) <= 80 else (
            outcome.statement[:77] + "…"
        )
        if str(outcome.scope_level) == "initiative":
            return EntityRef(entity_type, entity_id, statement, initiative_id=outcome.scope_id)
        return EntityRef(entity_type, entity_id, statement, project_id=outcome.scope_id)
    risk = await session.get(RiskItem, entity_id)
    if risk is None:
        raise missing
    level = str(risk.scope_level)
    if level == "initiative":
        return EntityRef(entity_type, entity_id, risk.title, initiative_id=risk.scope_id)
    if level == "project":
        return EntityRef(entity_type, entity_id, risk.title, project_id=risk.scope_id)
    task = await session.get(Task, risk.scope_id)
    return EntityRef(entity_type, entity_id, risk.title,
                     project_id=task.project_id if task is not None else None)


async def ensure_target_writable(
    session: AsyncSession, user: User, target: EntityRef, *, personal_doc: bool
) -> None:
    """May this user hang a doc on this entity? A personal doc links only to the owner's own
    tasks; otherwise planners per ownership, contributors on their own tasks."""
    if personal_doc:
        if (
            target.entity_type == DocLinkEntity.task
            and target.task is not None
            and await _own_task(session, user, target.task)
        ):
            return
        raise DocError(
            409,
            "doc_not_shared",
            "A personal doc links only to your own tasks. Share it in Claude and promote it "
            "to link it to shared work.",
        )
    role = _role(user)
    if role == UserRole.admin:
        return
    if role in PLANNER_ROLES:
        if target.entity_type == DocLinkEntity.initiative or (
            target.project_id is None and target.initiative_id is not None
        ):
            await access.ensure_initiative_editable(session, user, target.initiative_id)
        elif target.project_id is not None:
            await access.ensure_project_editable(session, user, target.project_id)
        return
    if (
        role == UserRole.engineer
        and target.entity_type == DocLinkEntity.task
        and target.task is not None
        and await _own_task(session, user, target.task)
    ):
        return
    raise DocError(
        403,
        "not_link_target_owner",
        "You can link docs only to work you may edit (a contributor: their own tasks).",
    )


# --- identity + registration -----------------------------------------------------------


def classify(url: str, *, strict: bool = True) -> DocUrlInfo:
    try:
        return classify_doc_url(url, strict=strict)
    except DocUrlError as exc:
        raise DocError(422, "invalid_url", str(exc)) from exc


async def find_by_identity(
    session: AsyncSession,
    info: DocUrlInfo,
    *,
    shared_only: bool = False,
    owner_user_id: int | None = None,
) -> DocReference | None:
    """The existing record of the same document: a shared one first, else (when
    `owner_user_id` is given) that person's personal one."""
    provider, key = same_document_key(info)
    if info.external_id:
        match: ColumnElement[bool] = and_(
            col(DocReference.provider) == provider, col(DocReference.external_id) == key
        )
    else:
        bare = info.url.split("#", 1)[0]
        match = or_(col(DocReference.url) == bare, col(DocReference.url) == info.url)
    rows = (
        await session.execute(
            select(DocReference).where(match).order_by(col(DocReference.id))
        )
    ).scalars().all()
    shared = [r for r in rows if r.private_to_user_id is None]
    if shared:
        return shared[0]
    if shared_only or owner_user_id is None:
        return None
    return next((r for r in rows if r.private_to_user_id == owner_user_id), None)


def _clip(text: str | None, limit: int) -> str | None:
    if text is None:
        return None
    text = text.strip()
    if not text:
        return None
    return text if len(text) <= limit else text[: limit - 1] + "…"


@dataclass
class LinkSpec:
    entity_type: DocLinkEntity
    entity_id: int
    relation: DocRelation = DocRelation.reference


@dataclass
class RegisterInput:
    url: str
    title: str | None = None
    kind: str | None = None
    format: str | None = None
    summary: str | None = None
    version: str | None = None
    content_hash: str | None = None
    visibility: DocVisibility = DocVisibility.unknown
    personal: bool = False
    scope_level: DocScope | None = None
    scope_id: int | None = None
    owner_engineer_id: int | None = None
    track: bool = True
    supersedes_id: int | None = None
    links: list[LinkSpec] = field(default_factory=list)


@dataclass
class RegisterResult:
    doc: DocReference
    created: bool
    links: list[DocLink] = field(default_factory=list)


async def _append_revision(
    session: AsyncSession,
    doc: DocReference,
    version: str,
    *,
    content_hash: str | None,
    recorded_by: int | None,
    source: str,
    change_summary: str | None = None,
) -> DocRevision | None:
    """Append a version to the log when it is new; returns the new row (None if seen)."""
    assert doc.id is not None
    existing = (
        await session.execute(
            select(DocRevision).where(
                DocRevision.doc_id == doc.id, DocRevision.version == version
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if content_hash and not existing.content_hash:
            existing.content_hash = content_hash
        return None
    revision = DocRevision(
        doc_id=doc.id,
        version=version,
        content_hash=content_hash,
        change_summary=_clip(change_summary, SUMMARY_MAX),
        recorded_by_user_id=recorded_by,
        source=source,
    )
    session.add(revision)
    await session.flush()
    return revision


async def register_core(
    session: AsyncSession,
    *,
    info: DocUrlInfo,
    kind: str | None,
    title: str | None,
    scope_level: DocScope | None,
    scope_id: int | None,
    source: DocSource,
    created_by: int | None,
    personal_for: int | None = None,
    visibility: DocVisibility = DocVisibility.unknown,
    format_slug: str | None = None,
    summary: str | None = None,
    version: str | None = None,
    content_hash: str | None = None,
    owner_engineer_id: int | None = None,
    track: bool = False,
    supersedes_id: int | None = None,
    link_existing_to_scope: bool = True,
) -> RegisterResult:
    """Find-or-create one document and make it reachable from `scope` (no permission checks).

    An existing shared record of the same document wins: when its home is elsewhere, the
    requested scope gets a reference link instead of a second row. Fields the existing record
    lacks (title, summary, version) are filled; nothing it has is overwritten.
    """
    norm_kind = await ensure_kind(session, kind) if kind is not None else None
    existing = await find_by_identity(
        session, info, shared_only=personal_for is None, owner_user_id=personal_for
    )
    if existing is not None and existing.private_to_user_id is None and personal_for is not None:
        # Already tracked for everyone — no personal copy needed.
        personal_for = None
    if existing is not None:
        assert existing.id is not None
        if title and not existing.title:
            existing.title = _clip(title, TITLE_MAX)
        if summary and not existing.summary:
            existing.summary = _clip(summary, SUMMARY_MAX)
        if norm_kind and existing.kind == "other" and norm_kind != "other":
            existing.kind = norm_kind
        if visibility != DocVisibility.unknown:
            existing.visibility = visibility.value
        if version:
            existing.current_version = version[:VERSION_MAX]
            await _append_revision(
                session, existing, version[:VERSION_MAX], content_hash=content_hash,
                recorded_by=created_by, source="register",
            )
        links: list[DocLink] = []
        same_home = (
            scope_level is not None
            and existing.scope_level == scope_level
            and existing.scope_id == scope_id
        )
        if existing.scope_level is None and scope_level is not None and scope_id is not None:
            existing.scope_level, existing.scope_id = scope_level, scope_id
        elif (
            scope_level is not None
            and scope_id is not None
            and not same_home
            and link_existing_to_scope
            and existing.private_to_user_id is None
        ):
            link = await _upsert_link(
                session, existing, DocLinkEntity(scope_level.value), scope_id,
                DocRelation.reference, pinned_version=None, created_by=created_by,
            )
            links.append(link)
        existing.updated_at = utcnow()
        await session.flush()
        return RegisterResult(existing, created=False, links=links)

    fmt = normalize_slug(format_slug, max_length=FORMAT_MAX, default="") if format_slug else ""
    doc = DocReference(
        scope_level=scope_level,
        scope_id=scope_id,
        kind=norm_kind or "other",
        title=_clip(title, TITLE_MAX),
        url=info.url,
        source=source.value,
        owner_engineer_id=owner_engineer_id,
        provider=info.provider.value,
        external_id=info.external_id,
        format=fmt or (info.format_hint.value if info.format_hint else DocFormat.other.value),
        private_to_user_id=personal_for,
        visibility=visibility.value,
        review_status=(
            DocReviewStatus.draft.value if track and personal_for is None else None
        ),
        current_version=version[:VERSION_MAX] if version else None,
        summary=_clip(summary, SUMMARY_MAX),
        supersedes_id=supersedes_id,
        created_by_user_id=created_by,
    )
    session.add(doc)
    await session.flush()
    if version:
        await _append_revision(
            session, doc, version[:VERSION_MAX], content_hash=content_hash,
            recorded_by=created_by, source="register",
        )
    return RegisterResult(doc, created=True)


async def register(
    session: AsyncSession, user: User, data: RegisterInput, *, source: DocSource
) -> RegisterResult:
    """Register a design doc for this user (checks + the sharing rule), then link it."""
    info = classify(data.url)
    personal = data.personal
    if not personal:
        if data.scope_level is None or data.scope_id is None:
            raise DocError(
                422, "home_required",
                "A shared doc needs a home: a project or initiative (or a task) it is filed "
                "under. Register it as personal to track it for yourself.",
            )
        await ensure_home_writable(session, user, data.scope_level, data.scope_id)
        await require_shareable(session, info, data.visibility, data.title)
    elif data.scope_level is not None and data.scope_id is not None:
        await _require_scope(session, data.scope_level, data.scope_id)
    if data.supersedes_id is not None:
        old = await get_visible_doc(session, user, data.supersedes_id)
        await ensure_doc_writable(session, user, old)

    result = await register_core(
        session,
        info=info,
        kind=data.kind,
        title=data.title,
        scope_level=data.scope_level,
        scope_id=data.scope_id,
        source=source,
        created_by=user.id,
        personal_for=user.id if personal else None,
        visibility=data.visibility,
        format_slug=data.format,
        summary=data.summary,
        version=data.version,
        content_hash=data.content_hash,
        owner_engineer_id=data.owner_engineer_id,
        track=data.track,
        supersedes_id=data.supersedes_id,
    )
    doc = result.doc
    if data.supersedes_id is not None and result.created:
        replaced = await session.get(DocReference, data.supersedes_id)
        if replaced is not None:
            replaced.review_status = DocReviewStatus.superseded.value
            replaced.updated_at = utcnow()
    for spec in data.links:
        result.links.append(
            await link_doc(session, user, doc, spec.entity_type, spec.entity_id, spec.relation)
        )
    await session.flush()
    return result


# --- links ----------------------------------------------------------------------------


async def _upsert_link(
    session: AsyncSession,
    doc: DocReference,
    entity_type: DocLinkEntity,
    entity_id: int,
    relation: DocRelation,
    *,
    pinned_version: str | None,
    created_by: int | None,
) -> DocLink:
    assert doc.id is not None
    link = (
        await session.execute(
            select(DocLink).where(
                DocLink.doc_id == doc.id,
                DocLink.entity_type == entity_type.value,
                DocLink.entity_id == entity_id,
            )
        )
    ).scalar_one_or_none()
    pin = pinned_version
    if relation == DocRelation.basis and pin is None:
        pin = doc.current_version
    if link is None:
        link = DocLink(
            doc_id=doc.id,
            entity_type=entity_type.value,
            entity_id=entity_id,
            relation=relation.value,
            pinned_version=pin if relation == DocRelation.basis else None,
            pinned_at=utcnow() if relation == DocRelation.basis and pin else None,
            created_by_user_id=created_by,
        )
        session.add(link)
    else:
        link.relation = relation.value
        if relation == DocRelation.basis:
            if pin is not None and pin != link.pinned_version:
                link.pinned_version, link.pinned_at = pin, utcnow()
        else:
            link.pinned_version, link.pinned_at = None, None
        link.updated_at = utcnow()
    await session.flush()
    return link


async def upsert_link(
    session: AsyncSession,
    doc: DocReference,
    entity_type: DocLinkEntity,
    entity_id: int,
    relation: DocRelation = DocRelation.reference,
    *,
    created_by: int | None = None,
) -> DocLink:
    """Create or update one link with no permission checks — for proposal apply (a human
    applying a reviewed change) and draft finalise. Callers enforce the sharing rule."""
    return await _upsert_link(
        session, doc, entity_type, entity_id, relation, pinned_version=None,
        created_by=created_by,
    )


async def link_doc(
    session: AsyncSession,
    user: User,
    doc: DocReference,
    entity_type: DocLinkEntity,
    entity_id: int,
    relation: DocRelation = DocRelation.reference,
    pinned_version: str | None = None,
) -> DocLink:
    """Link a doc to an entity (idempotent per doc + entity; a repeat updates the relation)."""
    await ensure_doc_writable(session, user, doc)
    target = await resolve_entity(session, entity_type, entity_id)
    personal = is_personal(doc)
    if personal and relation != DocRelation.reference:
        raise DocError(
            409, "doc_not_shared",
            "A personal doc can only be a reference on your own tasks; promote it to make it "
            "the basis of, or a gate on, shared work.",
        )
    await ensure_target_writable(session, user, target, personal_doc=personal)
    if not personal:
        require_shared(doc)
    return await _upsert_link(
        session, doc, entity_type, entity_id, relation,
        pinned_version=pinned_version, created_by=user.id,
    )


async def update_link(
    session: AsyncSession,
    user: User,
    link: DocLink,
    *,
    relation: DocRelation | None = None,
    pinned_version: str | None = None,
) -> DocLink:
    doc = await get_visible_doc(session, user, link.doc_id)
    return await link_doc(
        session, user, doc, DocLinkEntity(link.entity_type), link.entity_id,
        relation or DocRelation(link.relation), pinned_version,
    )


async def unlink(session: AsyncSession, user: User, link: DocLink) -> None:
    doc = await get_visible_doc(session, user, link.doc_id)
    await ensure_doc_writable(session, user, doc)
    if not is_personal(doc):
        target = await resolve_entity(session, DocLinkEntity(link.entity_type), link.entity_id)
        await ensure_target_writable(session, user, target, personal_doc=False)
    await session.delete(link)
    await session.flush()


# --- promote + delete -----------------------------------------------------------------


async def _move_links(session: AsyncSession, source: DocReference, target: DocReference) -> None:
    """Re-point every link of `source` at `target`, dropping ones `target` already has."""
    assert source.id is not None and target.id is not None
    have = {
        (link.entity_type, link.entity_id)
        for link in (
            await session.execute(select(DocLink).where(DocLink.doc_id == target.id))
        ).scalars().all()
    }
    for link in (
        await session.execute(select(DocLink).where(DocLink.doc_id == source.id))
    ).scalars().all():
        if (link.entity_type, link.entity_id) in have:
            await session.delete(link)
        else:
            link.doc_id = target.id
            have.add((link.entity_type, link.entity_id))
    await session.flush()


async def promote(
    session: AsyncSession,
    user: User,
    doc: DocReference,
    *,
    scope_level: DocScope,
    scope_id: int,
    visibility: DocVisibility | None = None,
) -> DocReference:
    """Turn a personal doc into a shared one filed under `scope` (the sharing rule applies).
    If the same document is already shared, the personal record folds into it."""
    if not is_personal(doc) or doc.private_to_user_id != user.id:
        raise DocError(409, "not_personal", "Only your own personal docs can be promoted.")
    if visibility is not None:
        doc.visibility = visibility.value
    require_shared(doc)
    await ensure_home_writable(session, user, scope_level, scope_id)
    info = classify(doc.url, strict=False)
    shared = await find_by_identity(session, info, shared_only=True)
    if shared is not None and shared.id != doc.id:
        await _move_links(session, doc, shared)
        await _delete_doc_rows(session, doc)
        await session.flush()
        return shared
    doc.private_to_user_id = None
    doc.scope_level, doc.scope_id = scope_level, scope_id
    if doc.review_status is None:
        doc.review_status = DocReviewStatus.draft.value
    doc.updated_at = utcnow()
    await session.flush()
    return doc


async def _delete_doc_rows(session: AsyncSession, doc: DocReference) -> None:
    assert doc.id is not None
    await session.execute(delete(DocLink).where(col(DocLink.doc_id) == doc.id))
    await session.execute(delete(DocRevision).where(col(DocRevision.doc_id) == doc.id))
    # provenance that named the doc outlives it (PG/MySQL enforce these foreign keys)
    await session.execute(
        update(Proposal).where(col(Proposal.source_doc_id) == doc.id).values(source_doc_id=None)
    )
    await session.execute(
        update(DraftPlan).where(col(DraftPlan.source_doc_id) == doc.id).values(source_doc_id=None)
    )
    for successor in (
        await session.execute(select(DocReference).where(DocReference.supersedes_id == doc.id))
    ).scalars().all():
        successor.supersedes_id = None
    await session.flush()
    await session.delete(doc)


async def drop_links_to(
    session: AsyncSession, entity_type: DocLinkEntity, entity_ids: Sequence[int]
) -> None:
    """Remove every doc link that points at entities being deleted (links have no FK)."""
    if not entity_ids:
        return
    await session.execute(
        delete(DocLink).where(
            col(DocLink.entity_type) == entity_type.value,
            col(DocLink.entity_id).in_(list(entity_ids)),
        )
    )


_SCOPE_LINKS = (DocLinkEntity.project.value, DocLinkEntity.initiative.value,
                DocLinkEntity.task.value)


async def release_docs_homed_at(
    session: AsyncSession, scope_level: DocScope, scope_ids: Sequence[int]
) -> None:
    """Docs whose home is being deleted: one document may serve other places, so it moves to
    its first surviving scope link; a personal doc just loses its home; anything else goes.
    Call after `drop_links_to` for every entity being deleted."""
    if not scope_ids:
        return
    docs = (
        await session.execute(
            select(DocReference).where(
                col(DocReference.scope_level) == scope_level,
                col(DocReference.scope_id).in_(list(scope_ids)),
            )
        )
    ).scalars().all()
    for doc in docs:
        if doc.private_to_user_id is not None:
            doc.scope_level, doc.scope_id = None, None
            continue
        survivor = (
            await session.execute(
                select(DocLink)
                .where(DocLink.doc_id == doc.id, col(DocLink.entity_type).in_(_SCOPE_LINKS))
                .order_by(col(DocLink.id))
                .limit(1)
            )
        ).scalar_one_or_none()
        if survivor is not None:
            doc.scope_level = DocScope(survivor.entity_type)
            doc.scope_id = survivor.entity_id
            await session.delete(survivor)
        else:
            await _delete_doc_rows(session, doc)
    await session.flush()


async def delete_doc(session: AsyncSession, user: User, doc: DocReference) -> None:
    await ensure_doc_writable(session, user, doc)
    await _delete_doc_rows(session, doc)
    await session.flush()


# --- reads ----------------------------------------------------------------------------


async def links_for(session: AsyncSession, doc_ids: Sequence[int]) -> dict[int, list[DocLink]]:
    out: dict[int, list[DocLink]] = {d: [] for d in doc_ids}
    if not doc_ids:
        return out
    rows = (
        await session.execute(
            select(DocLink).where(col(DocLink.doc_id).in_(list(doc_ids))).order_by(col(DocLink.id))
        )
    ).scalars().all()
    for link in rows:
        out.setdefault(link.doc_id, []).append(link)
    return out


async def entity_labels(
    session: AsyncSession, pairs: Iterable[tuple[str, int]]
) -> dict[tuple[str, int], str]:
    """Display labels for link targets, one query per entity type."""
    wanted: dict[str, set[int]] = {}
    for entity_type, entity_id in pairs:
        wanted.setdefault(entity_type, set()).add(entity_id)
    out: dict[tuple[str, int], str] = {}
    for entity_type, ids in wanted.items():
        id_list = list(ids)
        if entity_type == DocLinkEntity.project:
            for p in (await session.execute(
                select(Project).where(col(Project.id).in_(id_list))
            )).scalars():
                out[(entity_type, int(p.id or 0))] = p.name
        elif entity_type == DocLinkEntity.initiative:
            for i in (await session.execute(
                select(Initiative).where(col(Initiative.id).in_(id_list))
            )).scalars():
                out[(entity_type, int(i.id or 0))] = i.name
        elif entity_type == DocLinkEntity.task:
            for t in (await session.execute(
                select(Task).where(col(Task.id).in_(id_list))
            )).scalars():
                out[(entity_type, int(t.id or 0))] = f"{t.key} {t.name}" if t.key else t.name
        elif entity_type == DocLinkEntity.decision:
            for a in (await session.execute(
                select(ArchitectureDecision).where(col(ArchitectureDecision.id).in_(id_list))
            )).scalars():
                out[(entity_type, int(a.id or 0))] = f"ADR-{a.number:04d} {a.title}"
        elif entity_type == DocLinkEntity.spec:
            for s in (await session.execute(
                select(Spec).where(col(Spec.id).in_(id_list))
            )).scalars():
                out[(entity_type, int(s.id or 0))] = s.title
        elif entity_type == DocLinkEntity.milestone:
            for m in (await session.execute(
                select(Milestone).where(col(Milestone.id).in_(id_list))
            )).scalars():
                out[(entity_type, int(m.id or 0))] = m.name
        elif entity_type == DocLinkEntity.outcome:
            for o in (await session.execute(
                select(Outcome).where(col(Outcome.id).in_(id_list))
            )).scalars():
                text = o.statement
                out[(entity_type, int(o.id or 0))] = text if len(text) <= 80 else text[:77] + "…"
        elif entity_type == DocLinkEntity.risk:
            for r in (await session.execute(
                select(RiskItem).where(col(RiskItem.id).in_(id_list))
            )).scalars():
                out[(entity_type, int(r.id or 0))] = r.title
        elif entity_type == DocLinkEntity.retro:
            for rt in (await session.execute(
                select(Retrospective).where(col(Retrospective.id).in_(id_list))
            )).scalars():
                out[(entity_type, int(rt.id or 0))] = rt.title
        elif entity_type == DocLinkEntity.component:
            for c in (await session.execute(
                select(ArchitectureComponent).where(col(ArchitectureComponent.id).in_(id_list))
            )).scalars():
                out[(entity_type, int(c.id or 0))] = c.name
    return out


def scope_or_link_clause(
    scope_level: DocScope, scope_id: int, linked_doc_ids: Sequence[int]
) -> ColumnElement[bool]:
    """Docs homed at a scope, or linked to that same entity."""
    home = and_(
        col(DocReference.scope_level) == scope_level, col(DocReference.scope_id) == scope_id
    )
    if not linked_doc_ids:
        return home
    return or_(home, col(DocReference.id).in_(list(linked_doc_ids)))


async def doc_ids_linked_to(
    session: AsyncSession, entity_type: str, entity_ids: Sequence[int]
) -> list[int]:
    if not entity_ids:
        return []
    rows = (
        await session.execute(
            select(DocLink.doc_id).where(
                DocLink.entity_type == entity_type, col(DocLink.entity_id).in_(list(entity_ids))
            )
        )
    ).scalars().all()
    return sorted(set(rows))


@dataclass
class DocQuery:
    scope_level: DocScope | None = None
    scope_id: int | None = None
    kind: str | None = None
    provider: str | None = None
    review_status: str | None = None
    personal: bool | None = None  # True = only mine; False = only shared
    entity_type: DocLinkEntity | None = None
    entity_id: int | None = None
    stage_kinds: list[str] | None = None  # resolved from a stage filter by the route


async def list_docs(
    session: AsyncSession, user: User, query: DocQuery, impersonator: User | None = None
) -> list[DocReference]:
    """Docs the user may see, newest first, filtered."""
    clauses: list[ColumnElement[bool]] = [visible_clause(user, impersonator)]
    if query.scope_level is not None and query.scope_id is not None:
        linked = await doc_ids_linked_to(session, query.scope_level.value, [query.scope_id])
        clauses.append(scope_or_link_clause(query.scope_level, query.scope_id, linked))
    elif query.scope_level is not None:
        clauses.append(col(DocReference.scope_level) == query.scope_level)
    elif query.scope_id is not None:
        clauses.append(col(DocReference.scope_id) == query.scope_id)
    if query.entity_type is not None and query.entity_id is not None:
        linked = await doc_ids_linked_to(session, query.entity_type.value, [query.entity_id])
        clauses.append(col(DocReference.id).in_(linked) if linked else false())
    if query.kind:
        clauses.append(col(DocReference.kind) == normalize_slug(query.kind))
    if query.stage_kinds is not None:
        clauses.append(
            col(DocReference.kind).in_(query.stage_kinds) if query.stage_kinds else false()
        )
    if query.provider:
        clauses.append(col(DocReference.provider) == query.provider)
    if query.review_status:
        if query.review_status == "untracked":
            clauses.append(col(DocReference.review_status).is_(None))
        else:
            clauses.append(col(DocReference.review_status) == query.review_status)
    if query.personal is True:
        clauses.append(col(DocReference.private_to_user_id) == (user.id or -1))
    elif query.personal is False:
        clauses.append(col(DocReference.private_to_user_id).is_(None))
    rows = await session.execute(
        select(DocReference).where(and_(true(), *clauses)).order_by(col(DocReference.id).desc())
    )
    return list(rows.scalars().all())


async def docs_for_entity(
    session: AsyncSession,
    user: User,
    entity_type: DocLinkEntity,
    entity_id: int,
    impersonator: User | None = None,
) -> list[tuple[DocLink, DocReference]]:
    """The docs linked to one entity (with the link), visible to the user."""
    rows = (
        await session.execute(
            select(DocLink, DocReference)
            .join(DocReference, col(DocReference.id) == col(DocLink.doc_id))
            .where(
                DocLink.entity_type == entity_type.value,
                DocLink.entity_id == entity_id,
                visible_clause(user, impersonator),
            )
            .order_by(col(DocLink.id))
        )
    ).all()
    return [(link, doc) for link, doc in rows]


def touch(doc: DocReference, when: datetime | None = None) -> None:
    doc.updated_at = when or utcnow()


# --- versions, review, approval (USER_FLOWS §V8) ------------------------------------------


@dataclass
class RevisionResult:
    doc: DocReference
    revision: DocRevision | None  # the new version-log row (None when the version was seen)
    new_version: bool


async def record_revision(
    session: AsyncSession,
    user: User,
    doc: DocReference,
    *,
    version: str | None,
    content_hash: str | None = None,
    change_summary: str | None = None,
    reachable: bool = True,
    visibility: DocVisibility | None = None,
    snapshot_url: str | None = None,
    source: str = "session",
) -> RevisionResult:
    """Record what a check saw: the version (appended to the log when new), whether the doc
    could be opened, and its sharing level. Every call stamps `last_checked_at`, so "never
    checked" and "checked, unchanged" stay distinguishable."""
    await ensure_doc_writable(session, user, doc)
    now = utcnow()
    doc.last_checked_at = now
    doc.link_health = DocLinkHealth.ok if reachable else DocLinkHealth.broken
    if visibility is not None:
        doc.visibility = visibility.value
    revision: DocRevision | None = None
    new_version = False
    if reachable and version:
        label = version.strip()[:VERSION_MAX]
        new_version = label != doc.current_version
        revision = await _append_revision(
            session, doc, label, content_hash=content_hash, recorded_by=user.id, source=source,
            change_summary=change_summary,
        )
        doc.current_version = label
    if snapshot_url:
        target = revision
        if target is None and doc.current_version:
            target = (
                await session.execute(
                    select(DocRevision).where(
                        DocRevision.doc_id == doc.id, DocRevision.version == doc.current_version
                    )
                )
            ).scalar_one_or_none()
        if target is not None:
            target.snapshot_url = snapshot_url
    doc.updated_at = now
    await session.flush()
    return RevisionResult(doc, revision, new_version)


def _require_reviewable(doc: DocReference) -> None:
    if is_personal(doc):
        raise DocError(
            409, "doc_personal",
            "A personal doc has no review. Share it in Claude and promote it first.",
        )
    if doc.review_status in (DocReviewStatus.superseded.value, DocReviewStatus.archived.value):
        raise DocError(409, "doc_retired", "This doc is superseded or archived.")
    require_shared(doc)


async def request_review(
    session: AsyncSession, user: User, doc: DocReference, *, version: str | None = None
) -> DocReference:
    """Put a version up for review (draft → in_review, or approved → in_review again after a
    material change). Open to the doc's writers, agents included."""
    await ensure_doc_writable(session, user, doc)
    _require_reviewable(doc)
    label = (version or doc.current_version or "").strip()[:VERSION_MAX] or None
    if label and label != doc.current_version:
        await _append_revision(
            session, doc, label, content_hash=None, recorded_by=user.id, source="review"
        )
        doc.current_version = label
    doc.review_status = DocReviewStatus.in_review.value
    doc.review_version = label
    doc.updated_at = utcnow()
    await session.flush()
    return doc


async def ensure_can_approve(session: AsyncSession, user: User, doc: DocReference) -> None:
    """Approval is a planner's call on the doc's home (admins exempt); a contributor — the
    doc's author included — cannot approve."""
    role = _role(user)
    if role != UserRole.admin and role not in PLANNER_ROLES:
        raise DocError(403, "not_approver", "Only a planner on this doc's project approves it.")
    await ensure_doc_writable(session, user, doc)


async def approve(
    session: AsyncSession, user: User, doc: DocReference, *, version: str | None = None
) -> DocReference:
    """Sign off a version — the ONLY writer of the approved state (human-only at the route;
    `tests/test_doc_review_single_writer.py` pins it). The doc must be shared in Claude."""
    await ensure_can_approve(session, user, doc)
    _require_reviewable(doc)
    label = (version or doc.review_version or doc.current_version or "").strip()[:VERSION_MAX]
    if label and label != doc.current_version:
        await _append_revision(
            session, doc, label, content_hash=None, recorded_by=user.id, source="review"
        )
        doc.current_version = label
    now = utcnow()
    doc.review_status = DocReviewStatus.approved.value
    doc.approved_version = label or None
    doc.approved_by_user_id = user.id
    doc.approved_at = now
    doc.review_version = None
    doc.updated_at = now
    await session.flush()
    return doc


async def archive(session: AsyncSession, user: User, doc: DocReference) -> DocReference:
    """Retire a doc from default lists and coverage; its links stay as history."""
    await ensure_doc_writable(session, user, doc)
    doc.review_status = DocReviewStatus.archived.value
    doc.updated_at = utcnow()
    await session.flush()
    return doc


# --- health (USER_FLOWS §V8) -------------------------------------------------------------


async def health_for(
    session: AsyncSession, docs: Sequence[DocReference], *, now: datetime | None = None
) -> dict[int, list[HealthFlag]]:
    """Health flags for a batch of docs (one query for links, one per linked entity type, one
    for gate targets)."""
    when = now or utcnow()
    ids = [d.id for d in docs if d.id is not None]
    links = await links_for(session, ids)
    pairs = [(link.entity_type, link.entity_id) for group in links.values() for link in group]
    labels = await entity_labels(session, pairs)
    gate_milestones = {
        link.entity_id for group in links.values() for link in group
        if link.relation == DocRelation.gate.value and link.entity_type == DocLinkEntity.milestone
    }
    gate_specs = {
        link.entity_id for group in links.values() for link in group
        if link.relation == DocRelation.gate.value and link.entity_type == DocLinkEntity.spec
    }
    milestones = {
        m.id: m for m in (
            await session.execute(select(Milestone).where(col(Milestone.id).in_(gate_milestones)))
        ).scalars().all()
    } if gate_milestones else {}
    specs = {
        s.id: s for s in (
            await session.execute(select(Spec).where(col(Spec.id).in_(gate_specs)))
        ).scalars().all()
    } if gate_specs else {}

    out: dict[int, list[HealthFlag]] = {}
    for doc in docs:
        if doc.id is None:
            continue
        hlinks: list[HealthLink] = []
        for link in links.get(doc.id, []):
            target_date = None
            target_status = None
            if link.entity_type == DocLinkEntity.milestone and link.entity_id in milestones:
                target_date = milestones[link.entity_id].target_date
                target_status = milestones[link.entity_id].status
            elif link.entity_type == DocLinkEntity.spec and link.entity_id in specs:
                target_status = str(specs[link.entity_id].status)
            hlinks.append(HealthLink(
                entity_type=link.entity_type,
                entity_id=link.entity_id,
                relation=link.relation,
                pinned_version=link.pinned_version,
                label=labels.get((link.entity_type, link.entity_id)),
                target_date=target_date,
                target_status=target_status,
            ))
        out[doc.id] = doc_health(
            HealthDoc(
                id=doc.id,
                title=doc.title or doc.url,
                provider=doc.provider,
                visibility=doc.visibility,
                personal=doc.private_to_user_id is not None,
                review_status=doc.review_status,
                current_version=doc.current_version,
                approved_version=doc.approved_version,
                last_checked_at=doc.last_checked_at,
                link_health=str(doc.link_health),
                created_at=doc.created_at,
            ),
            hlinks,
            now=when,
            check_days=settings.DOC_CHECK_DAYS,
            gate_window_days=settings.DOC_GATE_WINDOW_DAYS,
        )
    return out


async def docs_in_project(session: AsyncSession, project_id: int) -> list[DocReference]:
    """Shared docs that bear on a project: filed under it or its tasks, or linked to it, its
    tasks, decisions, specs or milestones."""
    task_ids = [
        t for t in (
            await session.execute(select(col(Task.id)).where(col(Task.project_id) == project_id))
        ).scalars().all() if t is not None
    ]
    adr_ids = [
        a for a in (
            await session.execute(
                select(col(ArchitectureDecision.id)).where(
                    col(ArchitectureDecision.project_id) == project_id
                )
            )
        ).scalars().all() if a is not None
    ]
    spec_ids = [
        s for s in (
            await session.execute(select(col(Spec.id)).where(col(Spec.project_id) == project_id))
        ).scalars().all() if s is not None
    ]
    milestone_ids = [
        m for m in (
            await session.execute(
                select(col(Milestone.id)).where(col(Milestone.project_id) == project_id)
            )
        ).scalars().all() if m is not None
    ]
    linked: set[int] = set()
    for entity_type, ids in (
        (DocLinkEntity.project, [project_id]),
        (DocLinkEntity.task, task_ids),
        (DocLinkEntity.decision, adr_ids),
        (DocLinkEntity.spec, spec_ids),
        (DocLinkEntity.milestone, milestone_ids),
    ):
        linked.update(await doc_ids_linked_to(session, entity_type.value, ids))
    home = and_(
        col(DocReference.scope_level) == DocScope.project,
        col(DocReference.scope_id) == project_id,
    )
    clauses: list[ColumnElement[bool]] = [home]
    if task_ids:
        clauses.append(and_(
            col(DocReference.scope_level) == DocScope.task,
            col(DocReference.scope_id).in_(task_ids),
        ))
    if linked:
        clauses.append(col(DocReference.id).in_(sorted(linked)))
    rows = await session.execute(
        select(DocReference).where(
            or_(*clauses), col(DocReference.private_to_user_id).is_(None)
        ).order_by(col(DocReference.id))
    )
    return list(rows.scalars().all())


async def docs_awaiting_approval(session: AsyncSession, user: User) -> list[DocReference]:
    """Docs in review that this user may approve (a planner on their home)."""
    role = _role(user)
    if role != UserRole.admin and role not in PLANNER_ROLES:
        return []
    rows = (
        await session.execute(
            select(DocReference).where(
                col(DocReference.review_status) == DocReviewStatus.in_review.value,
                col(DocReference.private_to_user_id).is_(None),
            ).order_by(col(DocReference.updated_at).desc())
        )
    ).scalars().all()
    out: list[DocReference] = []
    for doc in rows:
        try:
            await ensure_can_approve(session, user, doc)
        except (DocError, HTTPException):  # 403 / 404 — not theirs to approve
            continue
        out.append(doc)
    return out


# --- lifecycle wiring (USER_FLOWS §V9) ----------------------------------------------------


async def pin_basis_links(
    session: AsyncSession, entity_type: DocLinkEntity, entity_ids: Sequence[int]
) -> int:
    """At a decision point (an ADR accepted, a spec approved, a baseline captured) pin every
    basis link on these entities to its doc's current version, so a later edit is detectable.
    Returns how many links moved."""
    if not entity_ids:
        return 0
    rows = (
        await session.execute(
            select(DocLink, DocReference)
            .join(DocReference, col(DocReference.id) == col(DocLink.doc_id))
            .where(
                col(DocLink.entity_type) == entity_type.value,
                col(DocLink.entity_id).in_(list(entity_ids)),
                col(DocLink.relation) == DocRelation.basis.value,
            )
        )
    ).all()
    moved = 0
    now = utcnow()
    for link, doc in rows:
        if doc.current_version and link.pinned_version != doc.current_version:
            link.pinned_version = doc.current_version
            link.pinned_at = now
            link.updated_at = now
            moved += 1
    await session.flush()
    return moved


async def docs_readiness(
    session: AsyncSession, entity_type: DocLinkEntity, entity_id: int
) -> tuple[bool, list[str]]:
    """Advisory: are the docs this entity rests on (basis) or waits for (gate) approved?
    Returns (ready, titles of the docs that are not)."""
    rows = (
        await session.execute(
            select(DocLink, DocReference)
            .join(DocReference, col(DocReference.id) == col(DocLink.doc_id))
            .where(
                col(DocLink.entity_type) == entity_type.value,
                col(DocLink.entity_id) == entity_id,
                col(DocLink.relation).in_([DocRelation.basis.value, DocRelation.gate.value]),
                col(DocReference.private_to_user_id).is_(None),
            )
            .order_by(col(DocLink.id))
        )
    ).all()
    pending = [
        doc.title or doc.url
        for _, doc in rows
        if doc.review_status not in (DocReviewStatus.approved.value,
                                     DocReviewStatus.superseded.value,
                                     DocReviewStatus.archived.value)
    ]
    return (not pending, pending)
