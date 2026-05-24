"""Link a chosen Jira ticket into canopy and map its descendant subtree onto canopy entities.

The architect picks a Jira ticket (an initiative-level issue, an epic, or a story) and links it
to a canopy **Project** or **Initiative**. canopy then reads that ticket plus its full descendant
subtree from Jira and maps it idempotently (via `ExternalRef`):

- target = project    → every issue becomes a Task in that project (epics → summary tasks).
- target = initiative → each epic becomes a Project under the initiative and its stories become
  tasks in that project (Jira initiative→epic→story mirrored onto canopy initiative→project→task).

Re-running a link is an idempotent update, not a duplicate. Status stays Jira-owned (never written
back) — the same source-of-truth boundary as the rest of sync.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.connectors import get_connector
from app.connectors.jira import JiraConnector, LinkMapResult
from app.core.events import publish
from app.models.base import Provider
from app.models.integration import Connection, JiraLink
from app.models.project import Initiative, Project
from app.schemas.entities import JiraLinkRead, JiraLinkSyncResult


class JiraLinkError(Exception):
    """A precondition for linking failed (bad connection/target, ticket not found, etc.)."""


async def _resolve_jira_connection(session: AsyncSession, connection_id: int) -> Connection:
    connection = await session.get(Connection, connection_id)
    if connection is None:
        raise JiraLinkError("Connection not found")
    if connection.provider != Provider.jira:
        raise JiraLinkError("Connection is not a Jira connection")
    if not connection.authorized:
        raise JiraLinkError("Jira connection is not authorized yet")
    return connection


def _connector(connection: Connection, session: AsyncSession) -> JiraConnector:
    connector = get_connector(connection, session)
    if not isinstance(connector, JiraConnector):  # pragma: no cover - defensive
        raise JiraLinkError("Connection is not a Jira connection")
    return connector


async def _validate_target(session: AsyncSession, target_type: str, target_id: int) -> None:
    if target_type == "project":
        if await session.get(Project, target_id) is None:
            raise JiraLinkError("Project not found")
    elif target_type == "initiative":
        if await session.get(Initiative, target_id) is None:
            raise JiraLinkError("Initiative not found")
    else:
        raise JiraLinkError(f"Unknown target_type {target_type!r}")


async def _upsert_link(
    session: AsyncSession,
    *,
    connection_id: int,
    issue_id: str,
    issue_key: str,
    issue_type: str | None,
    target_type: str,
    target_id: int,
) -> JiraLink:
    existing = (
        await session.execute(
            select(JiraLink).where(
                JiraLink.connection_id == connection_id, JiraLink.jira_issue_id == issue_id
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        link = JiraLink(
            connection_id=connection_id,
            jira_issue_id=issue_id,
            jira_key=issue_key,
            jira_issue_type=issue_type,
            target_type=target_type,
            target_id=target_id,
        )
        session.add(link)
    else:  # re-link: re-point an existing link (previously mapped entities are left in place)
        existing.jira_key = issue_key
        existing.jira_issue_type = issue_type
        existing.target_type = target_type
        existing.target_id = target_id
        link = existing
    await session.flush()
    return link


def _result(link: JiraLink, mapped: LinkMapResult) -> JiraLinkSyncResult:
    return JiraLinkSyncResult(
        link=JiraLinkRead.model_validate(link),
        projects_created=mapped.projects_created,
        projects_linked=mapped.projects_linked,
        tasks_created=mapped.tasks_created,
        tasks_updated=mapped.tasks_updated,
        skipped=mapped.skipped,
        created_project_ids=mapped.created_project_ids,
        notes=mapped.notes,
    )


async def _run_sync(
    session: AsyncSession, connector: JiraConnector, link: JiraLink
) -> JiraLinkSyncResult:
    issues = await connector.fetch_descendant_tree(link.jira_key)
    if not issues:
        raise JiraLinkError(f"Jira issue {link.jira_key} not found")
    if link.target_type == "project":
        mapped = await connector.map_subtree_into_project(issues, link.target_id)
    else:
        mapped = await connector.map_subtree_into_initiative(issues, link.target_id)
    link.last_synced_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(link)
    await publish(
        {"type": "jira_link", "target_type": link.target_type, "target_id": link.target_id}
    )
    return _result(link, mapped)


async def create_or_sync_link(
    session: AsyncSession,
    *,
    connection_id: int,
    jira_key: str,
    target_type: str,
    target_id: int,
) -> JiraLinkSyncResult:
    """Create (or re-point) a link for `jira_key` and immediately map its subtree into canopy."""
    connection = await _resolve_jira_connection(session, connection_id)
    await _validate_target(session, target_type, target_id)
    connector = _connector(connection, session)

    root = await connector.get_issue(jira_key)
    if root is None:
        raise JiraLinkError(f"Jira issue {jira_key} not found")
    issue_type = (root.get("fields", {}).get("issuetype") or {}).get("name")
    link = await _upsert_link(
        session,
        connection_id=connection_id,
        issue_id=str(root["id"]),
        issue_key=str(root["key"]),
        issue_type=issue_type,
        target_type=target_type,
        target_id=target_id,
    )
    return await _run_sync(session, connector, link)


async def resync_link(session: AsyncSession, link_id: int) -> JiraLinkSyncResult:
    """Re-pull a link's Jira subtree and re-map it (idempotent update)."""
    link = await session.get(JiraLink, link_id)
    if link is None:
        raise JiraLinkError("Link not found")
    connection = await _resolve_jira_connection(session, link.connection_id)
    await _validate_target(session, link.target_type, link.target_id)
    connector = _connector(connection, session)
    return await _run_sync(session, connector, link)


async def delete_link(session: AsyncSession, link_id: int) -> None:
    """Remove a link. Entities already mapped into canopy are kept (they're canopy-owned now)."""
    link = await session.get(JiraLink, link_id)
    if link is not None:
        await session.delete(link)
        await session.commit()


async def list_links(
    session: AsyncSession, *, target_type: str, target_id: int
) -> list[JiraLink]:
    rows = await session.execute(
        select(JiraLink)
        .where(JiraLink.target_type == target_type, JiraLink.target_id == target_id)
        .order_by(col(JiraLink.id))
    )
    return list(rows.scalars().all())
