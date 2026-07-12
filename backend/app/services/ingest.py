"""MCP-orchestrated ingest: Claude reads an external system with its own connectors and pushes
**normalized** data into canopy here, idempotently — the path used when a provider's reads are
set to `mcp`/`file` (so canopy itself doesn't call the provider API). The upsert core is shared
with the direct Jira sync (`app/connectors/jira.py`) so the two paths can't drift.

Ingest never advances a connection's incremental watermark (Claude decides what to send) and is
upsert-only (never deletes), so a partial push can't shrink canopy's state.
"""

from __future__ import annotations

import contextlib

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.connectors.base import SyncResult
from app.models.base import Provider, TaskType
from app.models.integration import Connection, PullRequest
from app.models.project import Task
from app.models.team import Engineer
from app.schemas.entities import IngestIssue, IngestPullRequest
from app.services import mapping

_EPIC_TYPES = {"Epic"}


def epic_type_names(config: dict) -> set[str]:
    """Issue-type names treated as epics — the configured `epic_issue_type` plus `Epic`
    (mirrors `JiraConnector._epic_type_names`)."""
    names = set(_EPIC_TYPES)
    configured = config.get("epic_issue_type")
    if configured:
        names.add(str(configured))
    return names


async def resolve_assignee_engineer(
    session: AsyncSession, account_id: str | None, display_name: str | None
) -> int | None:
    """Map an external (Jira) assignee onto an Engineer, creating one when unknown.

    Match order: exact `jira_account_id`, then exact display name (case-insensitive, which
    also back-fills the account id on the existing row), else a new active Engineer — the
    assignee is a real team member in Jira, so ownership lands on a real row here too.
    """
    if not account_id and not display_name:
        return None
    engineer: Engineer | None = None
    if account_id:
        engineer = (
            await session.execute(select(Engineer).where(Engineer.jira_account_id == account_id))
        ).scalars().first()
    if engineer is None and display_name:
        engineer = (
            await session.execute(
                select(Engineer).where(func.lower(Engineer.name) == display_name.lower())
            )
        ).scalars().first()
        if engineer is not None and account_id and engineer.jira_account_id is None:
            engineer.jira_account_id = account_id
    if engineer is None:
        engineer = Engineer(
            name=display_name or f"jira:{account_id}", jira_account_id=account_id
        )
        session.add(engineer)
        await session.flush()
    assert engineer.id is not None  # guaranteed after flush
    return engineer.id


async def upsert_task_from_external(
    session: AsyncSession,
    *,
    project_id: int,
    provider: Provider,
    external_id: str,
    external_key: str | None,
    summary: str,
    status: str | None,
    is_epic: bool,
    updated: str | None,
    force_leaf: bool = False,
    assignee_account_id: str | None = None,
    assignee_name: str | None = None,
) -> tuple[str, int]:
    """Idempotently upsert one external item as a canopy Task (via `ExternalRef`). Returns
    `(action, task_id)` where action is created|updated|skipped. Shared by the direct Jira sync
    and MCP ingest so both stay consistent."""
    ref = await mapping.get_ref(session, provider, external_id, "task")
    if ref is not None and not mapping.is_stale(ref, updated):
        return "skipped", ref.entity_id

    task_type = TaskType.summary if is_epic and not force_leaf else TaskType.task
    task: Task | None = None
    if ref is not None:
        task = await session.get(Task, ref.entity_id)
    if task is None:  # new item, or dangling ref — create
        task = Task(project_id=project_id, name=summary, type=task_type)
        session.add(task)
        await session.flush()
        action = "created" if ref is None else "updated"
    else:
        action = "updated"
    task.name = summary
    task.status = status
    task.type = task_type
    # Ownership mirrors the upstream assignee when one is set; an unassigned upstream issue
    # leaves any locally-set owner alone (assignment stays usable for canopy-only workflows).
    engineer_id = await resolve_assignee_engineer(session, assignee_account_id, assignee_name)
    if engineer_id is not None:
        task.assignee_engineer_id = engineer_id
    await session.flush()
    assert task.id is not None  # guaranteed after flush

    await mapping.upsert_ref(
        session,
        provider=provider,
        external_id=external_id,
        entity_type="task",
        entity_id=task.id,
        external_key=external_key,
        remote_updated=updated,
    )
    return action, task.id


async def wire_parents(
    session: AsyncSession, provider: Provider, parent_links: list[tuple[str, str]]
) -> None:
    """Second pass: set `Task.parent_id` once every parent has an `ExternalRef` (shared with the
    Jira sync's `_wire_parents`)."""
    for child_ext_id, parent_ext_id in parent_links:
        child_ref = await mapping.get_ref(session, provider, child_ext_id, "task")
        parent_ref = await mapping.get_ref(session, provider, parent_ext_id, "task")
        if child_ref and parent_ref:
            child = await session.get(Task, child_ref.entity_id)
            if child and child.parent_id != parent_ref.entity_id:
                child.parent_id = parent_ref.entity_id


async def _replan(session: AsyncSession, project_id: int) -> None:
    """Reschedule after new tasks were ingested (best-effort), mirroring the sync's auto-replan."""
    from app.services.planner import reschedule_project
    from app.services.scheduling import CycleError

    with contextlib.suppress(CycleError):
        await reschedule_project(session, project_id)


async def ingest_issues(
    session: AsyncSession, connection: Connection, issues: list[IngestIssue]
) -> SyncResult:
    """Upsert a batch of normalized issues into the connection's configured project as Tasks —
    the MCP twin of the direct Jira sync. Idempotent; epics become summary tasks."""
    if "project_id" not in connection.config:
        raise ValueError("connection has no configured project_id to ingest into")
    project_id = int(connection.config["project_id"])
    epics = epic_type_names(connection.config)

    result = SyncResult(provider="jira")
    parent_links: list[tuple[str, str]] = []
    for issue in issues:
        action, _ = await upsert_task_from_external(
            session,
            project_id=project_id,
            provider=Provider.jira,
            external_id=issue.external_id,
            external_key=issue.external_key,
            summary=issue.summary,
            status=issue.status,
            is_epic=(issue.issue_type or "") in epics,
            updated=issue.updated,
            assignee_account_id=issue.assignee_account_id,
            assignee_name=issue.assignee_name,
        )
        setattr(result, action, getattr(result, action) + 1)
        if issue.parent_external_id:
            parent_links.append((issue.external_id, issue.parent_external_id))
    await wire_parents(session, Provider.jira, parent_links)
    await session.commit()
    if result.created:
        await _replan(session, project_id)
    return result


async def upsert_pull_request(
    session: AsyncSession,
    *,
    repo: str,
    number: int,
    title: str,
    state: str,
    url: str | None = None,
    author: str | None = None,
    updated: str | None = None,
) -> str:
    """Idempotently upsert one PR cache row (keyed on repo+number); returns created|updated.
    Shared by the GitHub webhook and MCP/file ingest so the cache write can't drift."""
    existing = (
        await session.execute(
            select(PullRequest).where(PullRequest.repo == repo, PullRequest.number == number)
        )
    ).scalar_one_or_none()
    if existing is None:
        session.add(
            PullRequest(
                repo=repo,
                number=number,
                title=title,
                state=state,
                url=url,
                author=author,
                remote_updated=updated,
            )
        )
        return "created"
    existing.title = title
    existing.state = state
    existing.url = url
    existing.author = author
    existing.remote_updated = updated
    return "updated"


async def ingest_pull_requests(
    session: AsyncSession, connection: Connection, prs: list[IngestPullRequest]
) -> SyncResult:
    """Upsert a batch of normalized pull requests into the PR cache (the MCP twin of the GitHub
    webhook upsert). Keyed on (repo, number); repo comes from the connection config."""
    owner = connection.config.get("owner")
    repo = connection.config.get("repo")
    if not owner or not repo:
        raise ValueError("connection has no configured owner/repo to ingest into")
    full_name = f"{owner}/{repo}"

    result = SyncResult(provider="github")
    for pr in prs:
        action = await upsert_pull_request(
            session,
            repo=full_name,
            number=pr.number,
            title=pr.title,
            state=pr.state,
            url=pr.url,
            author=pr.author,
            updated=pr.updated,
        )
        setattr(result, action, getattr(result, action) + 1)
    await session.commit()
    return result
