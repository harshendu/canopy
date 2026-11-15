"""The organization artifact sync (USER_FLOWS §V11): metadata for the Claude docs canopy tracks.

Optional and off by default. An admin adds a `claude` connection holding the organization's
Compliance API key; the worker then lists the organization's artifacts (metadata only — the
connector never downloads content) and, for each **tracked** doc it can pair with a listed
artifact, records:

* the live version (`published_version_id`, else the newest listed version) — appended to the
  doc's version log with `source="sync"` — which also stamps the check;
* who can open it (`read_mode` → `visibility`), so `restricted` flags when a shared doc goes
  private again;
* for a Claude Doc or Sheet (no version ids), when it last changed (`source_updated_at`), so a
  session is asked to look and an edit after approval flags;
* existence: a paired artifact missing from a complete, unfiltered listing is marked `broken`.

Artifacts nobody tracks are **never stored**. A person may ask for their own untracked
artifacts (`suggestions_for`) — answered live, filtered to their own, never registered on
their behalf. Pairings and the owner ↔ canopy-user identities live in `ExternalRef`
(`entity_type` "doc" / "user"). The tagged ids the Compliance API returns are not documented
to equal the id in a claude.ai link, so pairing tries the id forms in
`claude_artifacts.candidate_ids`, records a pairing once found, and the report counts the
tracked docs that stayed unmatched (a person registering from a suggestion pairs explicitly).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.connectors.base import get_connector
from app.connectors.claude_artifacts import (
    ArtifactListing,
    ArtifactMeta,
    ClaudeArtifactsConnector,
    candidate_ids,
    parse_time,
)
from app.models.base import (
    DocFormat,
    DocProvider,
    DocReviewStatus,
    DocVisibility,
    Provider,
    utcnow,
)
from app.models.doc import DocReference
from app.models.integration import Connection, ExternalRef
from app.models.user import User
from app.services import design_docs, integration_policy, mapping
from app.services.design_docs import SYNC_DOC_ENTITY, DocError

USER_ENTITY = "user"
# The Compliance API's time filter matches an eventually-consistent index: re-read a generous
# window behind the watermark and dedupe by id.
OVERLAP = timedelta(hours=2)

_READ_MODES: dict[str, DocVisibility] = {
    "owner": DocVisibility.owner,
    "users": DocVisibility.users,
    "org": DocVisibility.org,
    "public": DocVisibility.public,
}
# The medium each artifact type implies (`format` is an open slug; the session may refine it).
TYPE_FORMATS: dict[str, str] = {
    "claude_docs": DocFormat.document.value,
    "code": DocFormat.page.value,
    "claude_slides": DocFormat.deck.value,
    "claude_design": DocFormat.canvas.value,
    "claude_design_systems": DocFormat.canvas.value,
    "claude_sheets": DocFormat.sheet.value,
    "claude_dashboards": DocFormat.page.value,
    "claude_motion": DocFormat.other.value,
}
_QUIET = (DocReviewStatus.superseded.value, DocReviewStatus.archived.value)


def visibility_for(read_mode: str) -> DocVisibility:
    return _READ_MODES.get(read_mode, DocVisibility.unknown)


@dataclass
class SyncReport:
    """What one run saw and changed — stored (counts only) on the connection's config."""

    full: bool  # an unfiltered listing (deletions and sharing changes are only visible then)
    complete: bool = True  # False when the page cap cut the listing short
    listed: int = 0
    paired: int = 0  # tracked docs this listing covered
    newly_paired: int = 0
    updated: int = 0  # docs whose metadata changed
    new_versions: int = 0
    sharing_changed: int = 0
    missing: int = 0  # paired docs no longer listed → marked broken (full, complete runs only)
    unmatched: int | None = None  # tracked shared Claude docs never paired (full runs only)
    identities: int = 0  # artifact owners newly matched to canopy users
    ran_at: str = ""

    def as_config(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class _Index:
    docs: dict[int, DocReference] = field(default_factory=dict)
    by_external: dict[str, list[int]] = field(default_factory=dict)
    paired: dict[str, int] = field(default_factory=dict)  # artifact id → primary doc id

    def family(self, doc_id: int) -> set[int]:
        """A doc and every row sharing its identity at the source (personal copies)."""
        doc = self.docs.get(doc_id)
        if doc is None:
            return set()
        return {doc_id, *(self.by_external.get(doc.external_id, []) if doc.external_id else [])}

    def targets(self, artifact_id: str) -> set[int]:
        """Docs one artifact covers: its recorded pairing (with that doc's copies), and rows
        whose link id is a form of the artifact id."""
        out: set[int] = set()
        primary = self.paired.get(artifact_id)
        if primary is not None:
            out.update(self.family(primary))
        for key in candidate_ids(artifact_id):
            out.update(self.by_external.get(key, []))
        return out

    def primary_for(self, doc_ids: set[int]) -> int:
        """The row a new pairing records: a shared doc before a personal copy, oldest first."""
        return min(doc_ids, key=lambda i: (self.docs[i].private_to_user_id is not None, i))


def _connection_id(connector: ClaudeArtifactsConnector) -> int | None:
    credential = connector.connection
    return credential.id if isinstance(credential, Connection) else None


async def _index(session: AsyncSession, connection_id: int | None) -> _Index:
    index = _Index()
    for doc in (
        await session.execute(
            select(DocReference).where(DocReference.provider == DocProvider.claude.value)
        )
    ).scalars().all():
        if doc.id is None:
            continue
        index.docs[doc.id] = doc
        if doc.external_id:
            index.by_external.setdefault(doc.external_id, []).append(doc.id)
    for ref in await _refs(session, SYNC_DOC_ENTITY, connection_id):
        index.paired.setdefault(ref.external_id, ref.entity_id)
    return index


async def _refs(
    session: AsyncSession, entity_type: str, connection_id: int | None
) -> list[ExternalRef]:
    rows = (
        await session.execute(
            select(ExternalRef)
            .where(ExternalRef.provider == Provider.claude, ExternalRef.entity_type == entity_type)
            .order_by(col(ExternalRef.id))
        )
    ).scalars().all()
    return [r for r in rows if r.connection_id in (None, connection_id)]


async def _record_pair(
    session: AsyncSession, artifact: ArtifactMeta, doc_id: int, connection_id: int | None
) -> bool:
    """Record that `doc_id` is `artifact`, unless the artifact is already paired."""
    if await mapping.get_ref(session, Provider.claude, artifact.id, SYNC_DOC_ENTITY,
                             connection_id) is not None:
        return False
    await mapping.upsert_ref(
        session, provider=Provider.claude, external_id=artifact.id,
        entity_type=SYNC_DOC_ENTITY, entity_id=doc_id,
        remote_updated=artifact.updated_at.isoformat() if artifact.updated_at else None,
        connection_id=connection_id,
    )
    await session.flush()
    return True


async def pair(
    session: AsyncSession, doc: DocReference, artifact: ArtifactMeta, connection_id: int | None
) -> design_docs.SourceUpdate:
    """Record that `doc` is `artifact` (idempotent) and apply what the listing says — the
    explicit pairing of a registration made from a suggestion."""
    assert doc.id is not None
    await _record_pair(session, artifact, doc.id, connection_id)
    return await _apply(session, doc, artifact)


async def _apply(
    session: AsyncSession, doc: DocReference, artifact: ArtifactMeta
) -> design_docs.SourceUpdate:
    return await design_docs.apply_source_metadata(
        session,
        doc,
        version=artifact.version_label,
        visibility=visibility_for(artifact.read_mode),
        source_updated_at=artifact.updated_at,
        title=artifact.title,
    )


async def record_identities(
    session: AsyncSession, artifacts: list[ArtifactMeta], connection_id: int | None
) -> int:
    """Map artifact owners (a Claude user id + email) onto canopy users by email, once each —
    so a person's own artifacts can later be listed with an owner filter."""
    owners = {
        a.owner_user_id: a.owner_email for a in artifacts if a.owner_user_id and a.owner_email
    }
    if not owners:
        return 0
    known = {r.external_id for r in await _refs(session, USER_ENTITY, connection_id)}
    wanted = {uid: email for uid, email in owners.items() if uid not in known}
    if not wanted:
        return 0
    users = (
        await session.execute(
            select(User).where(func.lower(col(User.email)).in_(sorted(set(wanted.values()))))
        )
    ).scalars().all()
    by_email = {u.email.strip().lower(): u for u in users if u.id is not None}
    added = 0
    for claude_user_id, email in wanted.items():
        user = by_email.get(email)
        if user is None or user.id is None:
            continue
        await mapping.upsert_ref(
            session, provider=Provider.claude, external_id=claude_user_id,
            entity_type=USER_ENTITY, entity_id=user.id, external_key=email,
            connection_id=connection_id,
        )
        added += 1
    return added


async def apply_listing(
    session: AsyncSession,
    listing: ArtifactListing,
    *,
    connection_id: int | None,
    full: bool,
    now: datetime | None = None,
) -> SyncReport:
    """Apply one listing to the tracked docs (the testable core of a run)."""
    when = now or utcnow()
    report = SyncReport(full=full, complete=listing.complete, listed=len(listing.items),
                        ran_at=when.isoformat())
    index = await _index(session, connection_id)
    covered: set[int] = set()
    listed_ids: set[str] = set()
    for artifact in listing.items:
        if artifact.id in listed_ids:  # overlap windows can repeat an artifact
            continue
        listed_ids.add(artifact.id)
        targets = index.targets(artifact.id) - covered
        if not targets:
            continue
        if artifact.id not in index.paired:
            primary = index.primary_for(targets)
            index.paired[artifact.id] = primary
            if await _record_pair(session, artifact, primary, connection_id):
                report.newly_paired += 1
        for doc_id in sorted(targets):
            covered.add(doc_id)
            result = await _apply(session, index.docs[doc_id], artifact)
            report.paired += 1
            report.updated += int(result.changed)
            report.new_versions += int(result.new_version)
            report.sharing_changed += int(result.visibility_changed)
    report.identities = await record_identities(session, listing.items, connection_id)

    if full and listing.complete:
        # Only an unfiltered, complete listing proves absence.
        for artifact_id, primary in index.paired.items():
            if artifact_id in listed_ids:
                continue
            for doc_id in index.family(primary) - covered:
                if design_docs.mark_source_missing(index.docs[doc_id], now=when):
                    report.missing += 1
                    report.updated += 1
        paired_docs = {d for primary in index.paired.values() for d in index.family(primary)}
        report.unmatched = sum(
            1 for doc_id, doc in index.docs.items()
            if doc_id not in covered
            and doc_id not in paired_docs
            and doc.private_to_user_id is None
            and doc.review_status not in _QUIET
        )
    await session.flush()
    return report


async def sync_connection(connector: ClaudeArtifactsConnector, *, full: bool) -> SyncReport:
    """One run: list (everything, or what changed since the watermark less the overlap),
    apply, move the watermark, store the report's counts on the connection."""
    session = connector.session
    credential = connector.connection
    mark = parse_time(credential.watermark) if credential.watermark else None
    since = mark - OVERLAP if (mark is not None and not full) else None
    listing = await connector.list_artifacts(updated_since=since)
    report = await apply_listing(
        session, listing, connection_id=_connection_id(connector), full=since is None
    )
    newest = max((a.updated_at for a in listing.items if a.updated_at), default=None)
    if newest is not None and (mark is None or newest > mark):
        credential.watermark = newest.isoformat()
    if isinstance(credential, Connection):
        credential.config = {**(credential.config or {}), "last_sync": report.as_config()}
    await session.commit()
    return report


# --- for the routes ------------------------------------------------------------------------


async def active_connection(session: AsyncSession) -> Connection | None:
    """The organization's artifact sync connection, when one is configured, authorized and
    allowed to read directly by the integration policy."""
    setting = await integration_policy.get_setting(session, Provider.claude)
    if not integration_policy.reads_direct(setting):
        return None
    usable = await integration_policy.usable_direct_connections(session, Provider.claude)
    return min(usable, key=lambda c: c.id or 0) if usable else None


def connector_for(connection: Connection, session: AsyncSession) -> ClaudeArtifactsConnector:
    connector = get_connector(connection, session)
    assert isinstance(connector, ClaudeArtifactsConnector)
    return connector


async def own_artifacts(
    session: AsyncSession, user: User, connector: ClaudeArtifactsConnector
) -> ArtifactListing:
    """The artifacts this person owns — listed live with an owner filter once their Claude
    identity is known, else from one unfiltered listing (which also learns the identities).
    Nothing about other people's artifacts is kept."""
    connection_id = _connection_id(connector)
    email = (user.email or "").strip().lower()
    mine = [r.external_id for r in await _refs(session, USER_ENTITY, connection_id)
            if r.entity_id == user.id]
    if mine:
        listing = await connector.list_artifacts(user_ids=mine)
    else:
        listing = await connector.list_artifacts()
        await record_identities(session, listing.items, connection_id)
        await session.commit()
    keep = set(mine)
    return ArtifactListing(
        items=[a for a in listing.items
               if (a.owner_user_id in keep) or (email and a.owner_email == email)],
        complete=listing.complete,
    )


async def suggestions_for(
    session: AsyncSession, user: User, connector: ClaudeArtifactsConnector
) -> ArtifactListing:
    """The person's own artifacts that no doc they can see tracks yet, newest first. Another
    person's *personal* tracking of the same artifact does not hide it (it is invisible here)."""
    listing = await own_artifacts(session, user, connector)
    index = await _index(session, _connection_id(connector))
    visible = {
        doc_id for doc_id, doc in index.docs.items()
        if doc.private_to_user_id is None or doc.private_to_user_id == user.id
    }
    items = [a for a in listing.items if not (index.targets(a.id) & visible)]
    items.sort(key=lambda a: a.updated_at or datetime.min, reverse=True)
    return ArtifactListing(items=items, complete=listing.complete)


async def find_own_artifact(
    session: AsyncSession, user: User, connector: ClaudeArtifactsConnector, artifact_id: str
) -> ArtifactMeta:
    """The listed artifact — only if it is the caller's own (a registration may pair only an
    artifact its owner registers)."""
    for artifact in (await own_artifacts(session, user, connector)).items:
        if artifact.id == artifact_id:
            return artifact
    raise DocError(
        404, "artifact_not_yours",
        "That artifact is not one of yours in the organization's Claude workspace.",
    )
