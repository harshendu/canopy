"""A project's tracking configuration (USER_FLOWS §C12): native (canopy owns every status) or
mirrored from a bound tracker — and switching between them with a previewed plan.

A switch is planned first (`plan_switch`, read-only: what happens to every task) and applied
from the same plan (`apply_switch`), so the preview is exactly what apply does
(`tests/test_tracking_switch.py` pins it). Applying is one local transaction — the old binding
detached (its refs kept as "formerly <KEY>" history), tracker-owned tasks released to canopy
(statuses the native columns lack remapped through the one status writer), the new binding
created, matched tasks adopted, the mode flipped — then two follow-ups that talk to the
tracker: publishing canopy tasks as new items (`publish`; content only, per item, re-runnable
via `publish_canopy_tasks`) and a first sync. canopy never writes a status to a tracker.

Strategies for the work a project already has when it gets a tracker:

- `keep_separate` — it stays canopy-owned (canopy-only work in a mirrored project);
- `match` — tasks whose key or title matches a tracker item are adopted by it (the tracker
  owns their status from then on); the rest stay canopy-owned;
- `publish` — open tasks are created as items in the tracker and adopted (they start in the
  tracker's first status); done/cancelled work stays canopy-owned history.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.connectors import get_connector
from app.connectors.tracker import WorkTracker, tracker_class, tracker_enabled, tracker_label
from app.core.events import publish
from app.models.base import (
    CANOPY_OWNER,
    Provider,
    StatusCategory,
    StatusSource,
    TaskType,
    TrackingMode,
    utcnow,
)
from app.models.integration import Connection, ExternalRef, TrackerBinding
from app.models.project import Project, Task
from app.services import integration_policy, mapping, tracker_sync, workflow
from app.services.tracker_types import KIND_EPIC, KIND_ITEM, ItemDraft, ItemRef, Scope, WorkItem

STRATEGIES = ("keep_separate", "match", "publish")
SWITCH_AUTHOR = "tracking switch"
_OPEN = {StatusCategory.todo.value, StatusCategory.in_progress.value, None}


def default_tracking_mode() -> str:
    """The mode a new project starts in (`TRACKING_DEFAULT_MODE`, native unless set)."""
    from app.core.config import settings

    mode = settings.TRACKING_DEFAULT_MODE.strip().lower()
    return mode if mode in (TrackingMode.native.value, TrackingMode.mirrored.value) else "native"


class TrackingConfigError(Exception):
    """The requested configuration or switch isn't possible (bad connection/scope/strategy)."""


@dataclass
class SwitchAction:
    task_id: int
    name: str
    key: str | None
    # keep | adopt | publish | release | remap
    action: str
    detail: str | None = None


@dataclass
class SwitchPlan:
    project_id: int
    from_mode: str
    to_mode: str
    from_provider: str | None
    to_provider: str | None
    strategy: str
    actions: list[SwitchAction] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # Not serialised: what apply needs beyond the actions.
    matches: dict[int, WorkItem] = field(default_factory=dict, repr=False)
    remaps: dict[int, tuple[str, str]] = field(default_factory=dict, repr=False)

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for a in self.actions:
            out[a.action] = out.get(a.action, 0) + 1
        return out


@dataclass
class SwitchTarget:
    """Where a switch to `mirrored` points: a tracker connection and a scope inside it, with
    the caller's read/write access to it (user-first, per the integration policy)."""

    connection: Connection
    cls: type[WorkTracker]
    scope: dict[str, Any]
    mapping: dict[str, Any]
    sync_iterations: bool
    reader: WorkTracker | None = None  # None: reads aren't direct (MCP/file) or no credential
    writer: WorkTracker | None = None
    write_reason: str = ""


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #


async def active_binding(session: AsyncSession, project_id: int) -> TrackerBinding | None:
    return (
        await session.execute(
            select(TrackerBinding)
            .where(
                TrackerBinding.target_type == "project",
                TrackerBinding.target_id == project_id,
                TrackerBinding.scope_kind != "subtree",
                col(TrackerBinding.active).is_(True),
            )
            .order_by(col(TrackerBinding.id).desc())
        )
    ).scalars().first()


async def past_bindings(session: AsyncSession, project_id: int) -> list[TrackerBinding]:
    return list(
        (
            await session.execute(
                select(TrackerBinding)
                .where(
                    TrackerBinding.target_type == "project",
                    TrackerBinding.target_id == project_id,
                    TrackerBinding.scope_kind != "subtree",
                    col(TrackerBinding.active).is_(False),
                )
                .order_by(col(TrackerBinding.id).desc())
            )
        ).scalars().all()
    )


async def project_tasks(session: AsyncSession, project_id: int) -> list[Task]:
    return list(
        (
            await session.execute(
                select(Task).where(Task.project_id == project_id).order_by(col(Task.id))
            )
        ).scalars().all()
    )


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


def validated_scope(cls: type[WorkTracker], scope: dict[str, Any] | None) -> dict[str, Any]:
    """The binding scope, checked against the tracker's `scope_schema`."""
    try:
        model = cls.scope_schema.model_validate(scope or {})
    except ValueError as exc:
        raise TrackingConfigError(f"Invalid scope for {cls.label}: {exc}") from exc
    return {k: v for k, v in model.model_dump().items() if v not in (None, "", [], {})}


async def switch_target(
    session: AsyncSession,
    *,
    connection_id: int | None,
    scope: dict[str, Any] | None,
    mapping_in: dict[str, Any] | None,
    sync_iterations: bool | None,
    user_id: int | None = None,
) -> SwitchTarget:
    if connection_id is None:
        raise TrackingConfigError("Pick the tracker connection to mirror from")
    connection = await session.get(Connection, connection_id)
    if connection is None or not connection.active:
        raise TrackingConfigError("Connection not found")
    cls = tracker_class(connection.provider)
    if cls is None:
        raise TrackingConfigError(f"{connection.provider.value} is not a work tracker")
    if not tracker_enabled(connection.provider):
        raise TrackingConfigError(
            f"{cls.label} is not enabled on this instance (TRACKERS_ENABLED)"
        )
    clean_scope = validated_scope(cls, scope)
    reader: WorkTracker | None = None
    read_cred = await integration_policy.resolve_read_credential(session, connection, user_id)
    if read_cred is not None:
        connector = get_connector(read_cred, session)
        reader = connector if isinstance(connector, WorkTracker) else None
    writer: WorkTracker | None = None
    write_cred, reason = await integration_policy.resolve_write_credential(
        session, connection, user_id
    )
    if write_cred is not None:
        connector = get_connector(write_cred, session)
        writer = connector if isinstance(connector, WorkTracker) else None
    return SwitchTarget(
        connection=connection,
        cls=cls,
        scope=clean_scope,
        mapping=dict(mapping_in or {}),
        sync_iterations=bool(sync_iterations) and cls.capabilities.iterations,
        reader=reader,
        writer=writer,
        write_reason=reason,
    )


# --------------------------------------------------------------------------- #
# Plan
# --------------------------------------------------------------------------- #


def _match_items(
    tasks: list[Task], items: list[WorkItem]
) -> dict[int, WorkItem]:
    """Each canopy task → the tracker item with its key, else the only item with its title
    (case-insensitive); an item is adopted at most once, epics only by phases."""
    by_key = {i.key.casefold(): i for i in items if i.key}
    by_title: dict[tuple[bool, str], list[WorkItem]] = {}
    for item in items:
        by_title.setdefault((item.kind == KIND_EPIC, item.title.strip().casefold()), []).append(
            item
        )
    taken: set[str] = set()
    out: dict[int, WorkItem] = {}
    for task in tasks:
        assert task.id is not None
        epic = task.type == TaskType.summary
        found = by_key.get((task.key or "").casefold())
        if found is None or (found.kind == KIND_EPIC) != epic:
            candidates = by_title.get((epic, task.name.strip().casefold()), [])
            found = candidates[0] if len(candidates) == 1 else None
        if found is not None and found.external_id not in taken:
            taken.add(found.external_id)
            out[task.id] = found
    return out


async def plan_switch(
    session: AsyncSession,
    project: Project,
    *,
    to_mode: str,
    target: SwitchTarget | None,
    strategy: str,
) -> SwitchPlan:
    """What a switch would do to every task. Read-only (`match` reads the tracker's items)."""
    assert project.id is not None
    if to_mode not in (TrackingMode.native.value, TrackingMode.mirrored.value):
        raise TrackingConfigError(f"Unknown tracking mode {to_mode!r}")
    if strategy not in STRATEGIES:
        raise TrackingConfigError(f"Unknown strategy {strategy!r}")
    current = await active_binding(session, project.id)
    legacy = (
        await tracker_sync.binding_for_project(session, project.id) if current is None else None
    )
    from_provider = (
        str(current.provider) if current is not None
        else legacy.provider.value if legacy is not None
        else None
    )
    to_provider = str(target.connection.provider) if target is not None else None
    plan = SwitchPlan(
        project_id=project.id,
        from_mode=project.tracking_mode,
        to_mode=to_mode,
        from_provider=from_provider,
        to_provider=to_provider,
        strategy=strategy if to_mode == TrackingMode.mirrored.value else "keep_separate",
    )
    if to_mode == TrackingMode.mirrored.value and target is None:
        raise TrackingConfigError("Pick the tracker connection to mirror from")
    same_binding = (
        to_mode == TrackingMode.mirrored.value
        and target is not None
        and current is not None
        and current.connection_id == target.connection.id
        and dict(current.scope or {}) == target.scope
    )
    if to_mode == project.tracking_mode and (
        to_mode == TrackingMode.native.value or same_binding
    ):
        raise TrackingConfigError("The project already tracks this way")

    if (
        to_mode == TrackingMode.mirrored.value
        and target is not None
        and current is not None
        and current.connection_id == target.connection.id
        and not same_binding
    ):
        raise TrackingConfigError(
            "Same tracker connection — change the binding's scope with PUT /tracking instead"
        )

    if to_mode == TrackingMode.mirrored.value and target is not None:
        await _refuse_shared_scope(session, project.id, target)

    tasks = await project_tasks(session, project.id)
    releasing = {t.id for t in tasks if t.status_owner != CANOPY_OWNER}
    # Columns a released task must fit: the project's own/team/template workflow (a tracker's
    # status map only arrives with the new tracker's first sync).
    native_view = await workflow.resolve_workflow(session, project, ignore_tracker=True)
    remaps: dict[int, tuple[str, str]] = {}
    for task in tasks:
        if task.id not in releasing or task.type == TaskType.summary or not task.status:
            continue
        if native_view.column(task.status) is not None:
            continue
        category = workflow.category_of_task(task) or StatusCategory.todo.value
        column = native_view.first_of(category) or native_view.first_of(
            StatusCategory.todo.value
        )
        if column is not None and task.id is not None:
            remaps[task.id] = (column.name, column.category)

    matches: dict[int, WorkItem] = {}
    publishing: set[int] = set()
    if to_mode == TrackingMode.mirrored.value and target is not None:
        caps, label = target.cls.capabilities, target.cls.label
        if plan.strategy == "match":
            if not caps.direct_read or target.reader is None:
                raise TrackingConfigError(
                    f"canopy can't read {label} directly here — match needs its items"
                )
            scope = Scope(kind="project", values=target.scope, mapping=target.mapping)
            page = await target.reader.fetch_items(scope, None)
            matches = _match_items(tasks, page.items)
        elif plan.strategy == "publish":
            if not caps.create_items:
                raise TrackingConfigError(f"{label} can't create items")
            if target.writer is None:
                raise TrackingConfigError(target.write_reason)
            publishing = {t.id for t in tasks if t.id is not None and _publishable(t)}
            started = sum(
                1
                for t in tasks
                if t.id in publishing
                and workflow.category_of_task(t) == StatusCategory.in_progress.value
            )
            if started:
                plan.warnings.append(
                    f"{started} started task(s) will start in {label}'s first status — "
                    "canopy never writes status; move them there after publishing."
                )
    plan.matches = matches

    for task in tasks:
        assert task.id is not None
        if task.id in matches:
            item = matches[task.id]
            action = SwitchAction(task.id, task.name, task.key, "adopt", f"matched {item.key}")
        elif task.id in publishing:
            action = SwitchAction(task.id, task.name, task.key, "publish")
        elif task.id in remaps:
            plan.remaps[task.id] = remaps[task.id]
            action = SwitchAction(
                task.id, task.name, task.key, "remap", f"{task.status} → {remaps[task.id][0]}"
            )
        elif task.id in releasing:
            action = SwitchAction(task.id, task.name, task.key, "release", task.status_owner)
        else:
            action = SwitchAction(task.id, task.name, task.key, "keep")
        plan.actions.append(action)
    if releasing and from_provider:
        plan.warnings.append(
            f"{len(releasing)} task(s) leave {tracker_label(from_provider)}: canopy owns their "
            "status from now on; their links are kept as history."
        )
    return plan


async def _refuse_shared_scope(
    session: AsyncSession, project_id: int, target: SwitchTarget
) -> None:
    """One tracker scope feeds one project: two projects mirroring the same items would pull
    each item back and forth between them."""
    for other in (
        await session.execute(
            select(TrackerBinding).where(
                TrackerBinding.connection_id == target.connection.id,
                TrackerBinding.target_type == "project",
                TrackerBinding.target_id != project_id,
                TrackerBinding.scope_kind != "subtree",
                col(TrackerBinding.active).is_(True),
            )
        )
    ).scalars().all():
        if target.cls.scope_selection(other.scope or {}) == target.cls.scope_selection(
            target.scope
        ):
            owner = await session.get(Project, other.target_id)
            name = owner.key if owner is not None else f"project {other.target_id}"
            raise TrackingConfigError(
                f"That {target.cls.label} scope already feeds {name} — bind another scope"
            )


def _publishable(task: Task) -> bool:
    """Open work is published; done/cancelled work stays canopy-owned history."""
    if task.type == TaskType.milestone:
        return False
    if task.type == TaskType.summary:
        return True
    return workflow.category_of_task(task) in _OPEN


# --------------------------------------------------------------------------- #
# Apply
# --------------------------------------------------------------------------- #


async def _detach_current(session: AsyncSession, project_id: int, now: Any) -> None:
    """Detach the project's binding. One that lives only in a pre-binding connection's
    `config.project_id` is recorded as a detached row — which also stops that connection's
    legacy fallback from binding the project again."""
    binding = await active_binding(session, project_id)
    if binding is not None:
        binding.active = False
        binding.detached_at = now
        return
    legacy = await tracker_sync.binding_for_project(session, project_id)
    if legacy is not None and legacy.row is None:
        session.add(
            TrackerBinding(
                connection_id=legacy.connection_id,
                provider=legacy.provider,
                target_type="project",
                target_id=project_id,
                scope_kind="project",
                scope=dict(legacy.scope.values),
                mapping=dict(legacy.scope.mapping),
                sync_iterations=legacy.sync_iterations,
                active=False,
                detached_at=now,
            )
        )


async def _release(session: AsyncSession, plan: SwitchPlan, tasks: list[Task], now: Any) -> None:
    ids = [t.id for t in tasks if t.id is not None and t.status_owner != CANOPY_OWNER]
    if not ids:
        return
    for ref in (
        await session.execute(
            select(ExternalRef).where(
                ExternalRef.entity_type == "task",
                col(ExternalRef.entity_id).in_(ids),
                col(ExternalRef.detached_at).is_(None),
            )
        )
    ).scalars().all():
        mapping.detach(ref, now)
    for task in tasks:
        if task.id not in ids:
            continue
        task.status_owner = CANOPY_OWNER
        if task.id in plan.remaps:
            name, category = plan.remaps[task.id]
            workflow.record_transition(
                session, task, name, category=category, source=StatusSource.canopy,
                author=SWITCH_AUTHOR,
            )


async def _adopt(
    session: AsyncSession, binding: TrackerBinding, task: Task, item: WorkItem
) -> None:
    """The tracker item now owns the task: link it, then let the engine apply the item."""
    assert task.id is not None
    await mapping.upsert_ref(
        session,
        provider=Provider(str(binding.provider)),
        external_id=item.external_id,
        entity_type="task",
        entity_id=task.id,
        external_key=item.key,
        connection_id=binding.connection_id,
    )
    ref = await mapping.get_ref(
        session, Provider(str(binding.provider)), item.external_id, "task",
        connection_id=binding.connection_id,
    )
    if ref is not None:
        ref.remote_updated = None  # stale on purpose: the upsert below applies the item
    await tracker_sync.upsert_item(
        session,
        provider=Provider(str(binding.provider)),
        connection_id=binding.connection_id,
        project_id=task.project_id,
        item=item,
        force_leaf=task.type != TaskType.summary,
    )


async def apply_switch(
    session: AsyncSession,
    project: Project,
    plan: SwitchPlan,
    *,
    target: SwitchTarget | None,
) -> TrackerBinding | None:
    """Apply a plan in one local transaction (committed here). Returns the new binding."""
    assert project.id is not None
    now = utcnow()
    tasks = await project_tasks(session, project.id)
    await _detach_current(session, project.id, now)
    await _release(session, plan, tasks, now)
    binding: TrackerBinding | None = None
    if plan.to_mode == TrackingMode.mirrored.value and target is not None:
        assert target.connection.id is not None
        binding = TrackerBinding(
            connection_id=target.connection.id,
            provider=Provider(str(target.connection.provider)),
            target_type="project",
            target_id=project.id,
            scope_kind="project",
            scope=target.scope,
            mapping=target.mapping,
            sync_iterations=target.sync_iterations,
        )
        session.add(binding)
        await session.flush()
        by_id = {t.id: t for t in tasks}
        for task_id, item in plan.matches.items():
            task = by_id.get(task_id)
            if task is not None:
                await _adopt(session, binding, task, item)
    project.tracking_mode = plan.to_mode
    await session.commit()
    await publish({"type": "tracking", "project_id": project.id, "mode": plan.to_mode})
    return binding


@dataclass
class PublishResult:
    created: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)
    keys: dict[int, str] = field(default_factory=dict)


async def publish_canopy_tasks(
    session: AsyncSession,
    project: Project,
    binding: TrackerBinding,
    tracker: WorkTracker,
    *,
    only: set[int] | None = None,
) -> PublishResult:
    """Create the project's open canopy-owned tasks as items in its tracker (phases before their
    children), adopting each as it is created — content only, never status. Idempotent: a task
    already linked to this tracker is skipped, so a failed run can be re-run."""
    assert project.id is not None
    result = PublishResult()
    scope = tracker_sync.scope_of(binding)
    tasks = await project_tasks(session, project.id)
    by_id = {t.id: t for t in tasks}
    provider = Provider(str(binding.provider))

    def depth(task: Task) -> int:
        d, cur, seen = 0, task, set()
        while cur.parent_id is not None and cur.parent_id in by_id and cur.parent_id not in seen:
            seen.add(cur.parent_id)
            cur = by_id[cur.parent_id]
            d += 1
        return d

    candidates = [
        t
        for t in sorted(tasks, key=lambda t: (depth(t), t.id or 0))
        if t.status_owner == CANOPY_OWNER
        and _publishable(t)
        and (only is None or t.id in only)
    ]
    item_for: dict[int, ItemRef] = {}
    for task in candidates:
        assert task.id is not None
        existing = (
            await session.execute(
                select(ExternalRef).where(
                    ExternalRef.entity_type == "task",
                    ExternalRef.entity_id == task.id,
                    ExternalRef.provider == provider,
                    col(ExternalRef.detached_at).is_(None),
                )
            )
        ).scalars().first()
        if existing is not None:
            item_for[task.id] = ItemRef(existing.external_id, existing.external_key)
            result.skipped += 1
            continue
        parent = item_for.get(task.parent_id) if task.parent_id is not None else None
        try:
            ref = await tracker.create_item(
                scope,
                ItemDraft(
                    title=task.name,
                    kind=KIND_EPIC if task.type == TaskType.summary else KIND_ITEM,
                    description=task.description,
                    estimate=task.story_points,
                    parent=parent,
                ),
            )
        except Exception as exc:  # report and carry on: a re-run picks up the rest
            result.failed += 1
            result.errors.append(f"{task.key or task.name}: {exc}")
            continue
        item_for[task.id] = ref
        await mapping.upsert_ref(
            session,
            provider=provider,
            external_id=ref.external_id,
            entity_type="task",
            entity_id=task.id,
            external_key=ref.key,
            connection_id=binding.connection_id,
        )
        task.status_owner = provider.value
        if ref.key:
            task.key = ref.key
            result.keys[task.id] = ref.key
        result.created += 1
        await session.commit()  # each created item is recorded at once (no duplicate on retry)
    return result


async def initial_sync(
    tracker: WorkTracker | None, binding: TrackerBinding
) -> tuple[int, int]:
    """A first full pull of a new binding (direct-read trackers). Returns (created, updated)."""
    if tracker is None or not tracker.capabilities.direct_read:
        return 0, 0
    result = await tracker_sync.sync_binding(tracker, tracker_sync.view_of(binding), full=True)
    return result.created, result.updated
