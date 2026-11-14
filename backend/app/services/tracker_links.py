"""Tracker links: attach one tracker item and its descendant subtree to a canopy project or
initiative (USER_FLOWS §J9). A link is a `TrackerBinding` with `scope_kind = "subtree"`.

- target = project    → every item becomes a task in that project (epics → summary tasks),
  parented within the project.
- target = initiative → each epic becomes a project under the initiative and its items become
  tasks in it (tracker initiative → epic → story onto initiative → project → task).

Re-syncing is an idempotent update. Unlinking deactivates the binding: what was mapped stays
(its tasks keep their history and their link to the tracker item). Status stays the tracker's.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.connectors import get_connector
from app.connectors.tracker import WorkTracker, is_tracker
from app.core.events import publish
from app.models.base import Provider, utcnow
from app.models.integration import Connection, JiraLink, TrackerBinding
from app.models.project import Initiative, Project
from app.services import tracker_sync
from app.services.tracker_types import Scope


class TrackerLinkError(Exception):
    """A precondition for linking failed (bad connection/target, item not found, etc.)."""


async def _tracker(session: AsyncSession, connection_id: int) -> tuple[Connection, WorkTracker]:
    connection = await session.get(Connection, connection_id)
    if connection is None:
        raise TrackerLinkError("Connection not found")
    if not is_tracker(connection.provider):
        raise TrackerLinkError(f"{connection.provider.value} is not a work tracker")
    connector = get_connector(connection, session)
    assert isinstance(connector, WorkTracker)
    if not connector.capabilities.direct_read or not connector.capabilities.hierarchy:
        raise TrackerLinkError(f"{connection.provider.value} can't be linked directly")
    if not connection.authorized:
        raise TrackerLinkError(f"The {connection.provider.value} connection is not authorized yet")
    return connection, connector


async def _validate_target(session: AsyncSession, target_type: str, target_id: int) -> None:
    if target_type == "project":
        if await session.get(Project, target_id) is None:
            raise TrackerLinkError("Project not found")
    elif target_type == "initiative":
        if await session.get(Initiative, target_id) is None:
            raise TrackerLinkError("Initiative not found")
    else:
        raise TrackerLinkError(f"Unknown target_type {target_type!r}")


async def upsert_subtree_binding(
    session: AsyncSession,
    *,
    connection_id: int,
    provider: Provider,
    root_id: str,
    root_key: str,
    root_type: str | None,
    target_type: str,
    target_id: int,
) -> TrackerBinding:
    """The subtree binding for a root item (one per connection + root; re-pointing reuses it)."""
    rows = (
        await session.execute(
            select(TrackerBinding).where(
                TrackerBinding.connection_id == connection_id,
                TrackerBinding.scope_kind == "subtree",
            )
        )
    ).scalars().all()
    binding = next((b for b in rows if str((b.scope or {}).get("root_id")) == root_id), None)
    if binding is None:
        binding = TrackerBinding(
            connection_id=connection_id,
            provider=provider,
            target_type=target_type,
            target_id=target_id,
            scope_kind="subtree",
        )
        session.add(binding)
    binding.scope = {"root_id": root_id, "root_key": root_key, "root_type": root_type}
    binding.target_type = target_type
    binding.target_id = target_id
    binding.active = True
    binding.detached_at = None
    await session.flush()
    return binding


async def _map(
    session: AsyncSession, connector: WorkTracker, binding: TrackerBinding
) -> tracker_sync.LinkMapResult:
    scope = tracker_sync.scope_of(binding)
    root_key = str(scope.get("root_key") or "")
    items = await connector.fetch_subtree(scope, root_key)
    if not items:
        raise TrackerLinkError(f"{binding.provider} item {root_key} not found")
    result = await tracker_sync.map_subtree(
        session,
        provider=Provider(str(binding.provider)),
        connection_id=binding.connection_id,
        items=items,
        target_type=binding.target_type,
        target_id=binding.target_id,
    )
    binding.last_synced_at = utcnow()
    await session.commit()
    await session.refresh(binding)
    await publish(
        {"type": "tracker_link", "target_type": binding.target_type, "target_id": binding.target_id}
    )
    return result


async def create_or_sync(
    session: AsyncSession, *, connection_id: int, root_key: str, target_type: str, target_id: int
) -> tuple[TrackerBinding, tracker_sync.LinkMapResult]:
    connection, connector = await _tracker(session, connection_id)
    await _validate_target(session, target_type, target_id)
    scope = Scope(kind="subtree", values={"root_key": root_key})
    root = await connector.fetch_item(scope, root_key)
    if root is None:
        raise TrackerLinkError(f"{connection.provider.value} item {root_key} not found")
    binding = await upsert_subtree_binding(
        session,
        connection_id=connection_id,
        provider=Provider(str(connection.provider)),
        root_id=root.external_id,
        root_key=root.key or root_key,
        root_type=root.raw_type,
        target_type=target_type,
        target_id=target_id,
    )
    return binding, await _map(session, connector, binding)


async def resync(
    session: AsyncSession, binding_id: int
) -> tuple[TrackerBinding, tracker_sync.LinkMapResult]:
    binding = await session.get(TrackerBinding, binding_id)
    if binding is None or binding.scope_kind != "subtree":
        raise TrackerLinkError("Link not found")
    _, connector = await _tracker(session, binding.connection_id)
    await _validate_target(session, binding.target_type, binding.target_id)
    return binding, await _map(session, connector, binding)


async def unlink(session: AsyncSession, binding_id: int) -> None:
    """Deactivate a link. What it mapped stays (canopy keeps the tasks and their history)."""
    binding = await session.get(TrackerBinding, binding_id)
    if binding is None or binding.scope_kind != "subtree":
        return
    binding.active = False
    binding.detached_at = utcnow()
    await session.commit()


async def list_links(
    session: AsyncSession, *, target_type: str, target_id: int
) -> list[TrackerBinding]:
    rows = await session.execute(
        select(TrackerBinding)
        .where(
            TrackerBinding.scope_kind == "subtree",
            TrackerBinding.target_type == target_type,
            TrackerBinding.target_id == target_id,
            col(TrackerBinding.active).is_(True),
        )
        .order_by(col(TrackerBinding.id))
    )
    return list(rows.scalars().all())


async def mirror_jira_link(session: AsyncSession, link: JiraLink) -> None:
    """Keep a legacy `JiraLink` (the `/jira-links` alias) mirrored as a subtree binding, so
    `/tracker-links` lists every link while the alias lives."""
    binding = await upsert_subtree_binding(
        session,
        connection_id=link.connection_id,
        provider=Provider.jira,
        root_id=link.jira_issue_id,
        root_key=link.jira_key,
        root_type=link.jira_issue_type,
        target_type=link.target_type,
        target_id=link.target_id,
    )
    binding.last_synced_at = link.last_synced_at


async def unmirror_jira_link(session: AsyncSession, link: JiraLink) -> None:
    rows = (
        await session.execute(
            select(TrackerBinding).where(
                TrackerBinding.connection_id == link.connection_id,
                TrackerBinding.scope_kind == "subtree",
            )
        )
    ).scalars().all()
    for binding in rows:
        if str((binding.scope or {}).get("root_id")) == link.jira_issue_id:
            binding.active = False
            binding.detached_at = utcnow()
