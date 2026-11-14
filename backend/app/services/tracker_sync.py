"""The tracker sync engine — the only caller of a `WorkTracker` (USER_FLOWS §J0).

A tracker fetches and normalizes (`app/connectors/tracker.py`); everything else happens here,
once, for every tracker: resolving the bindings a connection feeds, upserting items as canopy
tasks (`ingest.upsert_task_from_external` — which records status history on every change),
wiring parents, epic → project mapping for initiatives, watermarks, the tracker's status map,
changelog backfill, sprint/cycle mirroring, auto-replan and the live-refresh event.

Bindings (`TrackerBinding`) attach a project or initiative to a scope in a connection. A legacy
connection that still carries `config.project_id` (pre-bindings) is synced through an in-memory
binding built from that config, so existing installs keep working until the binding is saved.
"""

from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.connectors.base import EffectiveCredential, SyncResult
from app.core.events import publish
from app.models.base import Provider, StatusSource, utcnow
from app.models.integration import Connection, ExternalRef, TrackerBinding
from app.models.project import Project, Task, TaskStatusHistory
from app.models.sprint import Sprint
from app.services import ingest, mapping, sprint_service, workflow
from app.services.org import project_team_id
from app.services.tracker_types import (
    KIND_EPIC,
    ItemRef,
    Iteration,
    Scope,
    StatusDef,
    WorkItem,
)

if TYPE_CHECKING:
    from app.connectors.tracker import WorkTracker

logger = logging.getLogger(__name__)

# Changelog backfill is bounded per run (a nightly job tops up the rest).
BACKFILL_PER_RUN = 50


@dataclass
class LinkMapResult:
    """Outcome of mapping tracker items onto canopy entities (a sync, a link, an import)."""

    tasks_created: int = 0
    tasks_updated: int = 0
    projects_created: int = 0
    projects_linked: int = 0
    skipped: int = 0
    created_project_ids: list[int] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    created_task_ids: list[int] = field(default_factory=list)
    # Every project the mapping wrote into (an initiative's epic projects; the target project).
    project_ids: set[int] = field(default_factory=set)


@dataclass
class BindingView:
    """A resolved binding: a persisted `TrackerBinding`, or one derived from a legacy
    connection's config (`row is None`)."""

    connection_id: int
    provider: Provider
    target_type: str  # project | initiative
    target_id: int
    scope: Scope
    sync_iterations: bool = False
    row: TrackerBinding | None = None

    @property
    def id(self) -> int | None:
        return self.row.id if self.row is not None else None


# --------------------------------------------------------------------------- #
# Bindings
# --------------------------------------------------------------------------- #


def scope_of(row: TrackerBinding) -> Scope:
    return Scope(kind=row.scope_kind, values=dict(row.scope or {}), mapping=dict(row.mapping or {}))


def view_of(row: TrackerBinding) -> BindingView:
    return BindingView(
        connection_id=row.connection_id,
        provider=Provider(str(row.provider)),
        target_type=row.target_type,
        target_id=row.target_id,
        scope=scope_of(row),
        sync_iterations=row.sync_iterations,
        row=row,
    )


def legacy_mapping(config: dict[str, Any]) -> dict[str, Any]:
    """The type/field mapping a pre-bindings Jira connection kept in its config."""
    out: dict[str, Any] = {}
    if config.get("epic_issue_type"):
        out["epic_types"] = [str(config["epic_issue_type"])]
    if config.get("story_issue_type"):
        out["item_type"] = str(config["story_issue_type"])
    if config.get("story_point_field"):
        out["estimate_field"] = str(config["story_point_field"])
    return out


def legacy_scope(config: dict[str, Any]) -> dict[str, Any]:
    """The tracker scope a pre-bindings connection kept in its config (Jira project key…)."""
    values: dict[str, Any] = {}
    if config.get("jira_project_key"):
        values["project_key"] = str(config["jira_project_key"])
    for key in ("project_key", "team_key", "board_id", "jql"):
        if config.get(key) and key not in values:
            values[key] = config[key]
    return values


def legacy_binding(connection: Connection) -> BindingView | None:
    """A binding derived from a legacy connection's `config.project_id` (pre-bindings)."""
    config = connection.config or {}
    try:
        project_id = int(config.get("project_id"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if connection.id is None:
        return None
    return BindingView(
        connection_id=connection.id,
        provider=Provider(str(connection.provider)),
        target_type="project",
        target_id=project_id,
        scope=Scope(kind="project", values=legacy_scope(config), mapping=legacy_mapping(config)),
        sync_iterations=bool(config.get("board_id")),
    )


async def has_binding_rows(session: AsyncSession, connection_id: int | None) -> bool:
    """Whether the connection has any binding row (active or detached) — once it does, its
    legacy `config.project_id` no longer binds anything (a detached project stays detached)."""
    if connection_id is None:
        return False
    return (
        await session.execute(
            select(TrackerBinding.id).where(TrackerBinding.connection_id == connection_id)
        )
    ).first() is not None


async def bindings_for_connection(
    session: AsyncSession, connection: Connection, *, kinds: tuple[str, ...] = ("project", "query")
) -> list[BindingView]:
    """The active bindings a connection feeds (subtree links are re-synced explicitly), else the
    legacy config binding of a connection that never had binding rows."""
    rows = (
        await session.execute(
            select(TrackerBinding).where(
                TrackerBinding.connection_id == connection.id,
                col(TrackerBinding.active).is_(True),
                col(TrackerBinding.scope_kind).in_(kinds),
            )
        )
    ).scalars().all()
    if rows:
        return [view_of(r) for r in rows]
    if await has_binding_rows(session, connection.id):
        return []
    legacy = legacy_binding(connection)
    return [legacy] if legacy is not None else []


async def binding_for_project(session: AsyncSession, project_id: int) -> BindingView | None:
    """The project's active (non-subtree) binding, else a legacy connection pointing at it."""
    row = (
        await session.execute(
            select(TrackerBinding).where(
                TrackerBinding.target_type == "project",
                TrackerBinding.target_id == project_id,
                col(TrackerBinding.active).is_(True),
                TrackerBinding.scope_kind != "subtree",
            )
        )
    ).scalars().first()
    if row is not None:
        return view_of(row)
    for connection in (
        await session.execute(select(Connection).where(col(Connection.active).is_(True)))
    ).scalars().all():
        legacy = legacy_binding(connection)
        if legacy is None or legacy.target_id != project_id:
            continue
        from app.connectors.tracker import is_tracker

        if is_tracker(legacy.provider) and not await has_binding_rows(session, connection.id):
            return legacy
    return None


def _watermark(tracker: WorkTracker, binding: BindingView) -> str | None:
    # A user's own credential carries its own cursor (a narrow-access pull mustn't move the
    # service cursor); the service credential uses the binding's (or, legacy, the connection's).
    if isinstance(tracker.connection, EffectiveCredential) or binding.row is None:
        return tracker.connection.watermark
    return binding.row.watermark


def _set_watermark(tracker: WorkTracker, binding: BindingView, value: str | None) -> None:
    if value is None:
        return
    if isinstance(tracker.connection, EffectiveCredential) or binding.row is None:
        tracker.connection.watermark = value
    else:
        binding.row.watermark = value


# --------------------------------------------------------------------------- #
# Items → tasks
# --------------------------------------------------------------------------- #


async def upsert_item(
    session: AsyncSession,
    *,
    provider: Provider,
    connection_id: int | None,
    project_id: int,
    item: WorkItem,
    force_leaf: bool = False,
    columns: list[Any] | None = None,
) -> tuple[str, int]:
    """One normalized item as a mirrored canopy task (idempotent via `ExternalRef`)."""
    category = item.status_category
    if category is None and columns:
        category = workflow.resolve_category(item.status_name, columns=columns)
    assignee = item.assignee
    return await ingest.upsert_task_from_external(
        session,
        project_id=project_id,
        provider=provider,
        external_id=item.external_id,
        external_key=item.key,
        summary=item.title or item.key or item.external_id,
        status=item.status_name,
        is_epic=item.kind == KIND_EPIC,
        updated=item.updated,
        force_leaf=force_leaf,
        assignee_account_id=assignee.account_id if assignee else None,
        assignee_name=assignee.name if assignee else None,
        assignee_email=assignee.email if assignee else None,
        status_category=category,
        connection_id=connection_id,
        estimate=item.estimate,
    )


async def map_items_into_project(
    session: AsyncSession,
    *,
    provider: Provider,
    connection_id: int | None,
    items: list[WorkItem],
    project_id: int,
    parents_within: bool = False,
    columns: list[Any] | None = None,
) -> LinkMapResult:
    """Every item onto a task in `project_id` (epics → summary tasks), then parents. With
    `parents_within`, only parents inside `items` are wired (a subtree link)."""
    result = LinkMapResult()
    imported = {i.external_id for i in items}
    parent_links: list[tuple[str, str]] = []
    for item in items:
        action, task_id = await upsert_item(
            session,
            provider=provider,
            connection_id=connection_id,
            project_id=project_id,
            item=item,
            columns=columns,
        )
        _count(result, action, task_id)
        parent = item.parent_external_id
        if parent and (not parents_within or parent in imported):
            parent_links.append((item.external_id, parent))
    await ingest.wire_parents(session, provider, parent_links, connection_id=connection_id)
    return result


def _count(result: LinkMapResult, action: str, task_id: int) -> None:
    if action == "created":
        result.tasks_created += 1
        result.created_task_ids.append(task_id)
    elif action == "updated":
        result.tasks_updated += 1
    else:
        result.skipped += 1


def _nearest_epic(item: WorkItem, by_id: dict[str, WorkItem]) -> str | None:
    seen: set[str] = set()
    cur = item.parent_external_id
    while cur is not None and cur in by_id and cur not in seen:
        seen.add(cur)
        node = by_id[cur]
        if node.kind == KIND_EPIC:
            return cur
        cur = node.parent_external_id
    return None


async def _unique_project_key(session: AsyncSession, base: str) -> str:
    candidate, n = base, 1
    while (
        await session.execute(select(Project).where(Project.key == candidate))
    ).scalar_one_or_none() is not None:
        n += 1
        candidate = f"{base}-{n}"
    return candidate


async def _upsert_epic_project(
    session: AsyncSession,
    provider: Provider,
    connection_id: int | None,
    item: WorkItem,
    initiative_id: int,
) -> tuple[int, str]:
    ref = await mapping.get_ref(
        session, provider, item.external_id, "project", connection_id=connection_id
    )
    project = await session.get(Project, ref.entity_id) if ref is not None else None
    title = item.title or item.key or item.external_id
    if project is None:
        project = Project(
            key=await _unique_project_key(session, item.key or item.external_id),
            name=title,
            initiative_id=initiative_id,
            tracking_mode="mirrored",
        )
        session.add(project)
        action = "created"
    else:
        project.name = title
        if project.initiative_id is None:
            project.initiative_id = initiative_id
        action = "linked"
    await session.flush()
    assert project.id is not None
    await mapping.upsert_ref(
        session,
        provider=provider,
        external_id=item.external_id,
        entity_type="project",
        entity_id=project.id,
        external_key=item.key,
        remote_updated=item.updated,
        connection_id=connection_id,
    )
    return project.id, action


async def map_items_into_initiative(
    session: AsyncSession,
    *,
    provider: Provider,
    connection_id: int | None,
    items: list[WorkItem],
    initiative_id: int,
) -> LinkMapResult:
    """Epics → projects under the initiative; every other item → a task in its nearest epic's
    project (initiative → epic → story mirrored onto initiative → project → task)."""
    result = LinkMapResult()
    by_id = {i.external_id: i for i in items}
    epic_project: dict[str, int] = {}
    for item in items:
        if item.kind == KIND_EPIC:
            pid, action = await _upsert_epic_project(
                session, provider, connection_id, item, initiative_id
            )
            epic_project[item.external_id] = pid
            result.project_ids.add(pid)
            if action == "created":
                result.projects_created += 1
                result.created_project_ids.append(pid)
            else:
                result.projects_linked += 1
    parent_links: list[tuple[str, str]] = []
    for item in items:
        if item.kind == KIND_EPIC:
            continue
        epic_id = _nearest_epic(item, by_id)
        if epic_id is None:
            result.skipped += 1
            result.notes.append(f"{item.key or item.external_id}: no epic ancestor — not mapped")
            continue
        action, task_id = await upsert_item(
            session,
            provider=provider,
            connection_id=connection_id,
            project_id=epic_project[epic_id],
            item=item,
            force_leaf=True,
        )
        _count(result, action, task_id)
        parent = item.parent_external_id
        # Wire only a non-epic parent in the same project (a task under the epic is top-level:
        # the epic *is* the project).
        if parent and parent in by_id and by_id[parent].kind != KIND_EPIC:
            parent_links.append((item.external_id, parent))
    await ingest.wire_parents(session, provider, parent_links, connection_id=connection_id)
    return result


async def replan(session: AsyncSession, project_ids: set[int]) -> None:
    """Best-effort reschedule after new tasks arrived (a cyclic imported graph keeps dates)."""
    from app.services.planner import reschedule_project
    from app.services.scheduling import CycleError

    for pid in sorted(project_ids):
        with contextlib.suppress(CycleError):
            await reschedule_project(session, pid)


# --------------------------------------------------------------------------- #
# Sync
# --------------------------------------------------------------------------- #


async def board_columns_for(session: AsyncSession, binding: BindingView) -> list[Any] | None:
    """The status map a mirrored project resolves categories against (None = heuristic)."""
    if binding.row is None or not binding.row.status_map:
        return None
    from app.services.flow import ColumnDef

    return [
        ColumnDef(
            name=str(s["name"]),
            category=str(s["category"]),
            position=int(s.get("position", i)),
        )
        for i, s in enumerate(binding.row.status_map)
        if isinstance(s, dict) and s.get("name") and s.get("category")
    ]


async def refresh_status_map(tracker: WorkTracker, binding: BindingView) -> None:
    """Store the tracker's statuses (category + order) on the binding — the mirrored board's
    columns."""
    if binding.row is None or not tracker.capabilities.status_categories:
        return
    statuses: list[StatusDef] = await tracker.list_statuses(binding.scope)
    if statuses:
        binding.row.status_map = [
            {"name": s.name, "category": s.category, "position": s.position} for s in statuses
        ]


async def sync_binding(
    tracker: WorkTracker, binding: BindingView, *, full: bool, since: str | None = None
) -> SyncResult:
    """Pull one binding's items (all on a full sync, else since its watermark) into canopy."""
    session = tracker.session
    result = SyncResult(provider=binding.provider.value)
    if full:
        await refresh_status_map(tracker, binding)
    cursor = None if full else (since or _watermark(tracker, binding))
    page = await tracker.fetch_items(binding.scope, cursor)
    columns = await board_columns_for(session, binding)
    if binding.target_type == "initiative":
        mapped = await map_items_into_initiative(
            session,
            provider=binding.provider,
            connection_id=binding.connection_id,
            items=page.items,
            initiative_id=binding.target_id,
        )
        touched = mapped.project_ids
    else:
        mapped = await map_items_into_project(
            session,
            provider=binding.provider,
            connection_id=binding.connection_id,
            items=page.items,
            project_id=binding.target_id,
            columns=columns,
        )
        touched = {binding.target_id}
    result.created += mapped.tasks_created
    result.updated += mapped.tasks_updated
    result.skipped += mapped.skipped
    _set_watermark(tracker, binding, page.watermark)
    result.watermark = _watermark(tracker, binding)
    if binding.row is not None:
        binding.row.last_synced_at = utcnow()
    await session.commit()

    if tracker.capabilities.status_history and mapped.created_task_ids:
        for task_id in mapped.created_task_ids[:BACKFILL_PER_RUN]:
            try:
                await backfill_task_history(tracker, binding, task_id, commit=False)
            except Exception:  # best-effort (e.g. no changelog access): the nightly job retries
                logger.warning(
                    "Changelog backfill skipped for %s binding %s",
                    binding.provider.value,
                    binding.id,
                    exc_info=True,
                )
                break
        await session.commit()
    if binding.sync_iterations and tracker.capabilities.iterations:
        result.merge(await sync_iterations(tracker, binding))
    if mapped.tasks_created or mapped.created_project_ids:
        await replan(session, touched)
    await publish(
        {
            "type": "tracker_sync",
            "provider": binding.provider.value,
            "target_type": binding.target_type,
            "target_id": binding.target_id,
        }
    )
    return result


async def sync_connection(
    tracker: WorkTracker, *, full: bool, since: str | None = None
) -> SyncResult:
    """Sync every binding the tracker's connection feeds."""
    connection = await _connection_of(tracker)
    result = SyncResult(provider=str(tracker.provider))
    if connection is None:
        return result
    for binding in await bindings_for_connection(tracker.session, connection):
        result.merge(await sync_binding(tracker, binding, full=full, since=since))
    return result


async def _connection_of(tracker: WorkTracker) -> Connection | None:
    cred = tracker.connection
    if isinstance(cred, EffectiveCredential):
        return cred._connection
    return cred


# --------------------------------------------------------------------------- #
# Ingest (items an agent or a file fed — the twin of a direct sync)
# --------------------------------------------------------------------------- #


class IngestTargetError(ValueError):
    """The connection's items have nowhere (or nowhere unambiguous) to go."""


async def ingest_target(
    session: AsyncSession, connection: Connection, project_id: int | None = None
) -> BindingView:
    """The binding fed items land in: the one named by `project_id`, else the connection's only
    binding (or its legacy `config.project_id`)."""
    bindings = await bindings_for_connection(session, connection)
    if project_id is not None:
        for binding in bindings:
            if binding.target_type == "project" and binding.target_id == project_id:
                return binding
        raise IngestTargetError(f"connection is not bound to project {project_id}")
    if not bindings:
        raise IngestTargetError(
            "connection has no binding (or configured project_id) to ingest into"
        )
    if len(bindings) > 1:
        raise IngestTargetError("connection feeds several targets — pass project_id")
    return bindings[0]


async def ingest_items(
    session: AsyncSession,
    connection: Connection,
    items: list[WorkItem],
    *,
    project_id: int | None = None,
    binding: BindingView | None = None,
) -> SyncResult:
    """Upsert normalized items an agent (MCP) or a file fed for a tracker connection — how a
    tracker canopy can't read itself (`direct_read=False`) is kept in sync, and the MCP twin of
    a direct sync for the rest. Idempotent; epics become summary tasks (or projects, for an
    initiative binding); status stays the tracker's."""
    if binding is None:
        binding = await ingest_target(session, connection, project_id)
    result = SyncResult(provider=binding.provider.value)
    if binding.target_type == "initiative":
        mapped = await map_items_into_initiative(
            session,
            provider=binding.provider,
            connection_id=binding.connection_id,
            items=items,
            initiative_id=binding.target_id,
        )
        touched = mapped.project_ids
    else:
        mapped = await map_items_into_project(
            session,
            provider=binding.provider,
            connection_id=binding.connection_id,
            items=items,
            project_id=binding.target_id,
            columns=await board_columns_for(session, binding),
        )
        touched = {binding.target_id}
    result.created += mapped.tasks_created
    result.updated += mapped.tasks_updated
    result.skipped += mapped.skipped
    if binding.row is not None:
        binding.row.last_synced_at = utcnow()
    await session.commit()
    if mapped.tasks_created or mapped.created_project_ids:
        await replan(session, touched)
    await publish(
        {
            "type": "tracker_sync",
            "provider": binding.provider.value,
            "target_type": binding.target_type,
            "target_id": binding.target_id,
        }
    )
    return result


# --------------------------------------------------------------------------- #
# Webhooks
# --------------------------------------------------------------------------- #


def scope_matches(binding: BindingView, hint: dict[str, Any]) -> bool:
    """A webhook's scope hint matches a binding when every key both name agrees."""
    for key, value in hint.items():
        mine = binding.scope.get(key)
        if mine is not None and value is not None and str(mine) != str(value):
            return False
    return True


async def apply_webhook(tracker: WorkTracker, payload: dict[str, Any]) -> SyncResult:
    """Upsert the item a verified webhook carries into each matching binding's project."""
    session = tracker.session
    result = SyncResult(provider=str(tracker.provider))
    event = tracker.parse_webhook(payload)
    connection = await _connection_of(tracker)
    if event is None or event.item is None or connection is None:
        return result
    for binding in await bindings_for_connection(session, connection):
        if binding.target_type != "project" or not scope_matches(binding, event.scope_hint):
            continue
        action, _task_id = await upsert_item(
            session,
            provider=binding.provider,
            connection_id=binding.connection_id,
            project_id=binding.target_id,
            item=event.item,
            columns=await board_columns_for(session, binding),
        )
        setattr(result, action, getattr(result, action) + 1)
        if event.item.parent_external_id:
            await ingest.wire_parents(
                session,
                binding.provider,
                [(event.item.external_id, event.item.parent_external_id)],
                connection_id=binding.connection_id,
            )
    await session.commit()
    return result


# --------------------------------------------------------------------------- #
# Status history backfill (exact transitions from the changelog)
# --------------------------------------------------------------------------- #


async def backfill_task_history(
    tracker: WorkTracker, binding: BindingView, task_id: int, *, commit: bool = True
) -> int:
    """Replace a mirrored task's approximate `sync` history rows with the tracker's exact
    changelog (rows canopy recorded itself are kept). Returns rows added."""
    session = tracker.session
    ref = (
        await session.execute(
            select(ExternalRef).where(
                ExternalRef.entity_type == "task",
                ExternalRef.entity_id == task_id,
                ExternalRef.provider == binding.provider,
            )
        )
    ).scalars().first()
    if ref is None:
        return 0
    changes = await tracker.fetch_status_changes(
        binding.scope, ItemRef(external_id=ref.external_id, key=ref.external_key)
    )
    if not changes:
        return 0
    columns = await board_columns_for(session, binding)
    await session.execute(
        delete(TaskStatusHistory).where(
            col(TaskStatusHistory.task_id) == task_id,
            col(TaskStatusHistory.source) == StatusSource.sync.value,
        )
    )
    existing = {
        (h.changed_at, h.to_status)
        for h in (
            await session.execute(
                select(TaskStatusHistory).where(TaskStatusHistory.task_id == task_id)
            )
        ).scalars().all()
    }
    added = 0
    for change in changes:
        if (change.at, change.to_status) in existing:
            continue
        session.add(
            TaskStatusHistory(
                task_id=task_id,
                from_status=change.from_status,
                to_status=change.to_status,
                to_category=workflow.resolve_category(
                    change.to_status, explicit=change.to_category, columns=columns
                ),
                changed_at=change.at,
                author=change.author,
                source=StatusSource.backfill.value,
            )
        )
        existing.add((change.at, change.to_status))
        added += 1
    if commit:
        await session.commit()
    return added


async def backfill_pending(
    tracker: WorkTracker, binding: BindingView, *, limit: int = BACKFILL_PER_RUN
) -> int:
    """The nightly top-up: replay the changelog of the next `limit` mirrored tasks of the
    binding's connection past its backfill cursor (wrapping round once every task was seen), so
    a large import ends up with exact history without a long first sync. Returns rows added."""
    if binding.row is None or not tracker.capabilities.status_history:
        return 0
    session = tracker.session
    cursor = binding.row.backfill_cursor or 0
    refs = (
        await session.execute(
            select(ExternalRef)
            .where(
                ExternalRef.entity_type == "task",
                ExternalRef.provider == binding.provider,
                col(ExternalRef.detached_at).is_(None),
                (col(ExternalRef.connection_id) == binding.connection_id)
                | col(ExternalRef.connection_id).is_(None),
                col(ExternalRef.id) > cursor,
            )
            .order_by(col(ExternalRef.id))
            .limit(limit)
        )
    ).scalars().all()
    added = 0
    for ref in refs:
        added += await backfill_task_history(tracker, binding, ref.entity_id, commit=False)
    binding.row.backfill_cursor = refs[-1].id if refs else None  # None: start over next night
    await session.commit()
    return added


# --------------------------------------------------------------------------- #
# Sprints / cycles
# --------------------------------------------------------------------------- #


async def _upsert_sprint(
    session: AsyncSession, binding: BindingView, iteration: Iteration, team_id: int
) -> Sprint:
    ref = await mapping.get_ref(
        session,
        binding.provider,
        iteration.external_id,
        "sprint",
        connection_id=binding.connection_id,
    )
    row = await session.get(Sprint, ref.entity_id) if ref is not None else None
    if row is None:
        row = Sprint(team_id=team_id, name=iteration.name, owner=binding.provider.value)
        session.add(row)
    row.name = iteration.name or row.name
    row.goal = iteration.goal or row.goal
    row.start_date = iteration.start or row.start_date
    row.end_date = iteration.end or row.end_date
    row.state = iteration.state
    row.owner = binding.provider.value
    await session.flush()
    assert row.id is not None
    await mapping.upsert_ref(
        session,
        provider=binding.provider,
        external_id=iteration.external_id,
        entity_type="sprint",
        entity_id=row.id,
        external_key=iteration.name,
        connection_id=binding.connection_id,
    )
    return row


async def sync_iterations(tracker: WorkTracker, binding: BindingView) -> SyncResult:
    """Mirror the tracker's sprints/cycles as tracker-owned canopy sprints of the project's team
    and their members' membership (recorded). A project in no team only gets the legacy sprint
    name of its active iteration on its tasks."""
    session = tracker.session
    result = SyncResult(provider=binding.provider.value)
    if binding.target_type != "project":
        return result
    project = await session.get(Project, binding.target_id)
    if project is None:
        return result
    team_id = await project_team_id(session, project)
    for iteration in await tracker.fetch_iterations(binding.scope):
        row = (
            await _upsert_sprint(session, binding, iteration, team_id)
            if team_id is not None
            else None
        )
        for ext_id in iteration.item_external_ids:
            ref = await mapping.get_ref(
                session, binding.provider, ext_id, "task", connection_id=binding.connection_id
            )
            task = await session.get(Task, ref.entity_id) if ref is not None else None
            if task is None:
                continue
            if row is not None:
                if sprint_service.record_membership(
                    session, task, row, source=StatusSource.sync
                ) is not None:
                    result.updated += 1
            elif iteration.state == "active" and task.sprint != iteration.name:
                task.sprint = iteration.name
                result.updated += 1
    await session.commit()
    return result


# --------------------------------------------------------------------------- #
# Subtree links ("tracker links")
# --------------------------------------------------------------------------- #


async def map_subtree(
    session: AsyncSession,
    *,
    provider: Provider,
    connection_id: int | None,
    items: list[WorkItem],
    target_type: str,
    target_id: int,
) -> LinkMapResult:
    """Map a linked item + its descendants into a project (parents inside the subtree only)
    or an initiative (epics → projects), commit, and replan what got new tasks."""
    if target_type == "project":
        result = await map_items_into_project(
            session,
            provider=provider,
            connection_id=connection_id,
            items=items,
            project_id=target_id,
            parents_within=True,
        )
        touched = {target_id} if result.tasks_created else set()
    else:
        result = await map_items_into_initiative(
            session,
            provider=provider,
            connection_id=connection_id,
            items=items,
            initiative_id=target_id,
        )
        touched = result.project_ids if result.tasks_created else set()
    await session.commit()
    await replan(session, touched)
    return result
