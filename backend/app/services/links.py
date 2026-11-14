"""A task's external resource links: the tracker item behind it (Jira, Linear…), the GitHub PRs
implementing it, and the design docs (GitHub/Drive) scoped to it. Canopy links out to the systems
that own the work — it does not store the resources themselves (same boundary as the document
graph)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.connectors.tracker import registered_trackers, tracker_class
from app.models.base import DocScope, Provider
from app.models.doc import DocReference
from app.models.integration import Connection, ExternalRef, PullRequest
from app.schemas.entities import (
    DocReferenceRead,
    PullRequestRead,
    TaskExternalLinksRead,
    TrackerItemLink,
)


def jira_browse_url(base_url: str | None, key: str) -> str | None:
    """Build a human Jira *browse* URL from a connection's base_url. OAuth connections store the
    non-browsable API base (``api.atlassian.com/ex/jira/{cloudId}``) from which the site host can't
    be derived, so return None there — the UI then shows the key without a link."""
    if not base_url or "api.atlassian.com" in base_url:
        return None
    return f"{base_url.rstrip('/')}/browse/{key}"


def tracker_item_url(
    connection: Connection | None, provider: Provider | str, key: str
) -> str | None:
    """The browse URL of a tracker item through the connection it was synced from (None when the
    tracker exposes no browsable site)."""
    cls = tracker_class(provider)
    if cls is None or connection is None:
        return None
    return cls.browse_url(connection.config or {}, key)


async def _task_refs(session: AsyncSession, task_ids: list[int]) -> dict[int, ExternalRef]:
    """The live tracker ref behind each task (a detached ref — from a tracker the project no
    longer uses — only when nothing newer exists)."""
    providers = list(registered_trackers())
    if not task_ids or not providers:
        return {}
    refs = (
        await session.execute(
            select(ExternalRef)
            .where(
                ExternalRef.entity_type == "task",
                col(ExternalRef.entity_id).in_(task_ids),
                col(ExternalRef.provider).in_(providers),
            )
            .order_by(col(ExternalRef.id))
        )
    ).scalars().all()
    out: dict[int, ExternalRef] = {}
    for ref in refs:
        current = out.get(ref.entity_id)
        if current is None or current.detached_at is not None or ref.detached_at is None:
            out[ref.entity_id] = ref
    return out


async def _connections_for(
    session: AsyncSession, refs: list[ExternalRef]
) -> tuple[dict[int, Connection], dict[str, Connection]]:
    """Connections by id (refs that name theirs) and the first active one per provider (legacy
    refs synced before refs carried a connection)."""
    ids = {r.connection_id for r in refs if r.connection_id is not None}
    by_id: dict[int, Connection] = {}
    if ids:
        for conn in (
            await session.execute(select(Connection).where(col(Connection.id).in_(ids)))
        ).scalars().all():
            assert conn.id is not None
            by_id[conn.id] = conn
    by_provider: dict[str, Connection] = {}
    if any(r.connection_id is None for r in refs):
        for conn in (
            await session.execute(
                select(Connection)
                .where(col(Connection.active).is_(True))
                .order_by(col(Connection.id))
            )
        ).scalars().all():
            by_provider.setdefault(str(conn.provider), conn)
    return by_id, by_provider


def _connection(
    ref: ExternalRef, by_id: dict[int, Connection], by_provider: dict[str, Connection]
) -> Connection | None:
    if ref.connection_id is not None and ref.connection_id in by_id:
        return by_id[ref.connection_id]
    return by_provider.get(str(ref.provider))


async def external_urls(session: AsyncSession, task_ids: list[int]) -> dict[int, str]:
    """Browse URLs of the tracker items behind mirrored tasks, keyed by task id (tasks whose
    tracker exposes no browsable site are left out)."""
    refs = await _task_refs(session, task_ids)
    if not refs:
        return {}
    by_id, by_provider = await _connections_for(session, list(refs.values()))
    out: dict[int, str] = {}
    for task_id, ref in refs.items():
        url = tracker_item_url(
            _connection(ref, by_id, by_provider), ref.provider, ref.external_key or ref.external_id
        )
        if url:
            out[task_id] = url
    return out


async def tracker_link(session: AsyncSession, task_id: int) -> TrackerItemLink | None:
    """The tracker item a task mirrors (or was pushed to), with its browse URL."""
    ref = (await _task_refs(session, [task_id])).get(task_id)
    if ref is None:
        return None
    by_id, by_provider = await _connections_for(session, [ref])
    key = ref.external_key or ref.external_id
    cls = tracker_class(ref.provider)
    return TrackerItemLink(
        provider=str(ref.provider),
        label=cls.label if cls is not None and cls.label else str(ref.provider),
        key=key,
        url=tracker_item_url(_connection(ref, by_id, by_provider), ref.provider, key),
    )


async def collect_task_links(session: AsyncSession, task_id: int) -> TaskExternalLinksRead:
    tracker = await tracker_link(session, task_id)

    pr_result = await session.execute(
        select(PullRequest)
        .where(PullRequest.task_id == task_id)
        .order_by(col(PullRequest.number).desc())
    )
    prs = [PullRequestRead.model_validate(pr) for pr in pr_result.scalars().all()]

    doc_result = await session.execute(
        select(DocReference)
        .where(
            DocReference.scope_level == DocScope.task,
            DocReference.scope_id == task_id,
        )
        .order_by(col(DocReference.id).desc())
    )
    docs = [DocReferenceRead.model_validate(d) for d in doc_result.scalars().all()]

    return TaskExternalLinksRead(tracker=tracker, pull_requests=prs, docs=docs)
