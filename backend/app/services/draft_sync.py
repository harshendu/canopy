"""Push a reviewed draft plan to Jira: create (or update) tickets from its proposed tasks.

This writes **content only** — summary, description, story points, and the epic→story
parent link. It never writes status (Jira stays the owner of ticket status). canopy also
does not create local `Task`s here: per the chosen direction, the next Jira sync pulls the
new issues back as canopy tasks. We only stamp each draft task with its Jira id/key so a
re-push becomes an idempotent update rather than a duplicate.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.connectors import get_connector
from app.connectors.jira import JiraConnector
from app.core.events import publish
from app.models.base import Provider, utcnow
from app.models.draft import DraftPlan, DraftTask
from app.models.integration import Connection
from app.schemas.entities import DraftPushResult, DraftPushTaskResult


class DraftPushError(Exception):
    """A precondition for pushing a plan failed (no plan, no/ambiguous connection, etc.)."""


async def _resolve_jira_connection(
    session: AsyncSession, project_id: int, connection_id: int | None
) -> Connection:
    if connection_id is not None:
        connection = await session.get(Connection, connection_id)
        if connection is None:
            raise DraftPushError("Connection not found")
        if connection.provider != Provider.jira:
            raise DraftPushError("Connection is not a Jira connection")
        return connection

    rows = await session.execute(
        select(Connection).where(
            Connection.provider == Provider.jira, col(Connection.active).is_(True)
        )
    )
    matches = [c for c in rows.scalars().all() if int(c.config.get("project_id", 0)) == project_id]
    if not matches:
        raise DraftPushError("No active Jira connection is configured for this project")
    if len(matches) > 1:
        raise DraftPushError("Multiple Jira connections match this project — pass connection_id")
    return matches[0]


def _ordered_tasks(tasks: list[DraftTask]) -> list[DraftTask]:
    """Parents before children, so an epic exists (and has a key) before its stories push."""
    by_id = {t.id: t for t in tasks}

    def depth(task: DraftTask) -> int:
        d = 0
        seen: set[int] = set()
        cur = task.parent_id
        while cur is not None and cur in by_id and cur not in seen:
            seen.add(cur)
            d += 1
            cur = by_id[cur].parent_id
        return d

    return sorted(tasks, key=lambda t: (depth(t), t.sort_order, t.id or 0))


async def push_plan_to_jira(
    session: AsyncSession, plan_id: int, connection_id: int | None = None
) -> DraftPushResult:
    plan = await session.get(DraftPlan, plan_id)
    if plan is None:
        raise DraftPushError("Draft plan not found")

    connection = await _resolve_jira_connection(session, plan.project_id, connection_id)
    if not connection.authorized:
        raise DraftPushError("Jira connection is not authorized yet")
    assert connection.id is not None

    connector = get_connector(connection, session)
    if not isinstance(connector, JiraConnector):  # pragma: no cover - defensive
        raise DraftPushError("Connection is not a Jira connection")

    rows = await session.execute(
        select(DraftTask).where(DraftTask.plan_id == plan_id)
    )
    tasks = _ordered_tasks(list(rows.scalars().all()))

    results: list[DraftPushTaskResult] = []
    created = updated = failed = 0
    for task in tasks:
        assert task.id is not None
        parent_key: str | None = None
        if task.parent_id is not None:
            parent = next((t for t in tasks if t.id == task.parent_id), None)
            parent_key = parent.jira_key if parent is not None else None
        try:
            if task.jira_issue_id:
                await connector.update_issue(
                    task.jira_issue_id,
                    summary=task.name,
                    description=task.description,
                    story_points=task.story_points,
                )
                updated += 1
                results.append(
                    DraftPushTaskResult(
                        draft_task_id=task.id,
                        name=task.name,
                        action="updated",
                        jira_key=task.jira_key,
                    )
                )
            else:
                issue = await connector.create_issue(
                    summary=task.name,
                    issue_type=connector.issue_type_for(task.type),
                    description=task.description,
                    story_points=task.story_points,
                    parent_key=parent_key,
                )
                task.jira_issue_id = issue["id"]
                task.jira_key = issue["key"]
                created += 1
                results.append(
                    DraftPushTaskResult(
                        draft_task_id=task.id,
                        name=task.name,
                        action="created",
                        jira_key=issue["key"],
                    )
                )
        except Exception as exc:  # surface per-task failure, keep pushing the rest
            failed += 1
            results.append(
                DraftPushTaskResult(
                    draft_task_id=task.id, name=task.name, action="failed", error=str(exc)
                )
            )

    if failed == 0 and (created or updated):
        plan.status = "synced"
        plan.synced_at = utcnow()
    await session.commit()
    await publish({"type": "draft_push", "project_id": plan.project_id, "plan_id": plan_id})

    return DraftPushResult(
        plan_id=plan_id,
        connection_id=connection.id,
        created=created,
        updated=updated,
        failed=failed,
        results=results,
    )
