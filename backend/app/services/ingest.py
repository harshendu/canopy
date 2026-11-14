"""MCP-orchestrated ingest: Claude reads an external system with its own connectors and pushes
**normalized** data into canopy here, idempotently — the path used when a provider's reads are
set to `mcp`/`file` (so canopy itself doesn't call the provider API). The upsert core is shared
with the direct Jira sync (`app/connectors/jira.py`) so the two paths can't drift.

Ingest never advances a connection's incremental watermark (Claude decides what to send) and is
upsert-only (never deletes), so a partial push can't shrink canopy's state.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.connectors.base import SyncResult
from app.models.base import Provider, StatusSource, TaskType
from app.models.integration import Connection, EngineerIdentity, ExternalRef, PullRequest
from app.models.project import Task
from app.models.team import Engineer
from app.schemas.entities import IngestIssue, IngestPullRequest
from app.services import mapping, workflow

if TYPE_CHECKING:
    from app.services.tracker_types import WorkItem

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
    session: AsyncSession,
    account_id: str | None,
    display_name: str | None,
    provider: Provider = Provider.jira,
    email: str | None = None,
) -> int | None:
    """Map a tracker assignee onto an Engineer, creating one when unknown.

    Match order: the provider's `EngineerIdentity` (the legacy `Engineer.jira_account_id` for
    Jira), then email, then exact display name (case-insensitive) — a match back-fills the
    identity — else a new active Engineer: the assignee is a real team member in the tracker,
    so ownership lands on a real row here too.
    """
    if not account_id and not display_name and not email:
        return None
    engineer: Engineer | None = None
    if account_id:
        identity = (
            await session.execute(
                select(EngineerIdentity).where(
                    EngineerIdentity.provider == provider,
                    EngineerIdentity.external_account_id == account_id,
                )
            )
        ).scalars().first()
        if identity is not None:
            engineer = await session.get(Engineer, identity.engineer_id)
        if engineer is None and provider == Provider.jira:
            engineer = (
                await session.execute(
                    select(Engineer).where(Engineer.jira_account_id == account_id)
                )
            ).scalars().first()
    if engineer is None and email:
        engineer = (
            await session.execute(
                select(Engineer).where(func.lower(Engineer.email) == email.lower())
            )
        ).scalars().first()
    if engineer is None and display_name:
        engineer = (
            await session.execute(
                select(Engineer).where(func.lower(Engineer.name) == display_name.lower())
            )
        ).scalars().first()
    if engineer is None:
        engineer = Engineer(
            name=display_name or email or f"{provider.value}:{account_id}",
            email=email,
            jira_account_id=account_id if provider == Provider.jira else None,
        )
        session.add(engineer)
        await session.flush()
    elif provider == Provider.jira and account_id and engineer.jira_account_id is None:
        engineer.jira_account_id = account_id
    assert engineer.id is not None  # guaranteed after flush
    if account_id:
        await _remember_identity(session, engineer.id, provider, account_id, display_name)
    return engineer.id


async def _remember_identity(
    session: AsyncSession,
    engineer_id: int,
    provider: Provider,
    account_id: str,
    display_name: str | None,
) -> None:
    existing = (
        await session.execute(
            select(EngineerIdentity).where(
                EngineerIdentity.provider == provider,
                EngineerIdentity.external_account_id == account_id,
            )
        )
    ).scalars().first()
    if existing is None:
        session.add(
            EngineerIdentity(
                engineer_id=engineer_id,
                provider=provider,
                external_account_id=account_id,
                display_name=display_name,
            )
        )
        await session.flush()


async def _has_children(session: AsyncSession, task_id: int | None) -> bool:
    if task_id is None:
        return False
    return (
        await session.execute(select(Task.id).where(Task.parent_id == task_id).limit(1))
    ).first() is not None


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
    status_category: str | None = None,
    assignee_email: str | None = None,
    connection_id: int | None = None,
    estimate: float | None = None,
) -> tuple[str, int]:
    """Idempotently upsert one external item as a canopy Task (via `ExternalRef`). Returns
    `(action, task_id)` where action is created|updated|skipped. Shared by the direct Jira sync
    and MCP ingest so both stay consistent.

    The task is mirrored: `status_owner` becomes the provider and its key the external key. Its
    status goes through `workflow.record_transition`, so a changed status appends a history row
    (source `sync`, dated by the item's `updated`) and completion reconciles progress — the
    burndown/forecast/aging views get data from the very first sync."""
    ref = await mapping.get_ref(session, provider, external_id, "task", connection_id)
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
        if (
            task.type == TaskType.summary
            and task_type == TaskType.task
            and not force_leaf
            and await _has_children(session, task.id)
        ):
            # A phase with children stays a phase: an event that can't tell (a tracker webhook
            # without the item's children) must not demote it and orphan the WBS.
            task_type = TaskType.summary
    task.name = summary
    task.type = task_type
    task.status_owner = provider.value
    if external_key:
        task.key = external_key
    if estimate is not None:
        task.story_points = estimate
    # The one status write path: stamps the category, appends history when the status changed,
    # and mirrors completion into progress (a done status ⇒ 100%; leaving done drops a 100% back
    # to 0; other manual partial progress is kept) so every view agrees on one "done".
    category = workflow.resolve_category(status, explicit=status_category)
    workflow.record_transition(
        session,
        task,
        status,
        category=category,
        source=StatusSource.sync,
        at=workflow.parse_remote_time(updated),
    )
    # Ownership mirrors the upstream assignee when one is set; an unassigned upstream issue
    # leaves any locally-set owner alone (assignment stays usable for canopy-only workflows).
    engineer_id = await resolve_assignee_engineer(
        session, assignee_account_id, assignee_name, provider, assignee_email
    )
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
        connection_id=connection_id,
    )
    return action, task.id


async def wire_parents(
    session: AsyncSession,
    provider: Provider,
    parent_links: list[tuple[str, str]],
    connection_id: int | None = None,
) -> None:
    """Second pass: set `Task.parent_id` once every parent has an `ExternalRef` (shared by the
    tracker sync engine and ingest)."""
    for child_ext_id, parent_ext_id in parent_links:
        child_ref = await mapping.get_ref(session, provider, child_ext_id, "task", connection_id)
        parent_ref = await mapping.get_ref(session, provider, parent_ext_id, "task", connection_id)
        if child_ref and parent_ref:
            child = await session.get(Task, child_ref.entity_id)
            if child and child.parent_id != parent_ref.entity_id:
                child.parent_id = parent_ref.entity_id


def item_from_ingest(issue: IngestIssue, epic_types: set[str]) -> WorkItem:
    """A normalized ingest row as the engine's `WorkItem` (an explicit `kind` wins; else the
    issue type decides whether it is an epic)."""
    from app.services.tracker_types import KIND_EPIC, KIND_ITEM, Assignee, WorkItem

    kind = issue.kind or (KIND_EPIC if (issue.issue_type or "") in epic_types else KIND_ITEM)
    has_assignee = issue.assignee_account_id or issue.assignee_name or issue.assignee_email
    return WorkItem(
        external_id=issue.external_id,
        key=issue.external_key,
        title=issue.summary,
        status_name=issue.status,
        status_category=issue.status_category,
        kind=kind,
        parent_external_id=issue.parent_external_id,
        assignee=Assignee(
            account_id=issue.assignee_account_id,
            name=issue.assignee_name,
            email=issue.assignee_email,
        )
        if has_assignee
        else None,
        estimate=issue.estimate,
        updated=issue.updated,
        url=issue.url,
        raw_type=issue.issue_type,
    )


async def ingest_issues(
    session: AsyncSession,
    connection: Connection,
    issues: list[IngestIssue],
    *,
    project_id: int | None = None,
) -> SyncResult:
    """Upsert a batch of normalized items into the connection's bound project as tasks — the
    MCP/file twin of a direct sync, for any tracker. Idempotent; epics become summary tasks."""
    from app.services.tracker_sync import ingest_items, ingest_target

    binding = await ingest_target(session, connection, project_id)
    epic_types = epic_type_names(connection.config or {}) | {
        str(t) for t in binding.scope.mapping.get("epic_types") or []
    }
    items = [item_from_ingest(issue, epic_types) for issue in issues]
    return await ingest_items(session, connection, items, binding=binding)


# An issue key as trackers and canopy write them: PROJ-123 (Jira), ENG-42 (Linear), SHOP-7
# (a native canopy key). Matched case-insensitively in a PR title or branch name.
_ISSUE_KEY_RE = re.compile(r"(?<![A-Za-z0-9])([A-Za-z][A-Za-z0-9]{0,19}-\d{1,9})(?![A-Za-z0-9])")


def issue_keys(*texts: str | None) -> list[str]:
    """Issue keys mentioned in the given texts (upper-cased, first occurrence first)."""
    seen: list[str] = []
    for text in texts:
        for match in _ISSUE_KEY_RE.finditer(text or ""):
            key = match.group(1).upper()
            if key not in seen:
                seen.append(key)
    return seen


async def task_for_keys(session: AsyncSession, keys: list[str]) -> int | None:
    """The task a PR implements, by the first key that names one: a native canopy key
    (`Task.key`) or the key of a tracker item canopy mirrors (any tracker)."""
    for key in keys:
        native = (
            await session.execute(select(Task.id).where(Task.key == key))
        ).scalars().first()
        if native is not None:
            return int(native)
        ref = (
            await session.execute(
                select(ExternalRef.entity_id)
                .where(
                    ExternalRef.entity_type == "task",
                    ExternalRef.external_key == key,
                    col(ExternalRef.detached_at).is_(None),
                )
                .order_by(col(ExternalRef.id).desc())
            )
        ).scalars().first()
        if ref is not None:
            return int(ref)
    return None


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
    branch: str | None = None,
) -> str:
    """Idempotently upsert one PR cache row (keyed on repo+number); returns created|updated.
    Shared by the GitHub webhook and MCP/file ingest so the cache write can't drift. A PR not yet
    tied to a task is matched by the issue key in its title or branch (any tracker's key, or a
    native canopy key)."""
    existing = (
        await session.execute(
            select(PullRequest).where(PullRequest.repo == repo, PullRequest.number == number)
        )
    ).scalar_one_or_none()
    action = "updated"
    if existing is None:
        existing = PullRequest(repo=repo, number=number, title=title, state=state)
        session.add(existing)
        action = "created"
    existing.title = title
    existing.state = state
    existing.url = url
    existing.author = author
    existing.remote_updated = updated
    if existing.task_id is None:
        existing.task_id = await task_for_keys(session, issue_keys(title, branch))
    return action


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
            branch=pr.branch,
        )
        setattr(result, action, getattr(result, action) + 1)
    await session.commit()
    return result
