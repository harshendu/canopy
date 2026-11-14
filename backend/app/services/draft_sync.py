"""Finalise a reviewed draft plan (USER_FLOWS §C10): turn its proposed tasks into real work.

Where the work lands follows the project's tracking mode:

- **native** — canopy tasks are created in one transaction (summary tasks for epics, parents
  wired, `duration` from `estimate_days`, story points, a key and a first status), then the
  project is replanned. Each draft task is stamped with its `task_id`, so finalising again
  updates instead of duplicating.
- **mirrored** — the plan's content is pushed to the project's tracker through
  `WorkTracker.create_item` / `update_item` (parents first, so an epic exists before its
  stories). Content only: summary, description, story points and the epic→story parent —
  **never status**. canopy does not create local tasks here: the next sync pulls the new items
  back. Each draft task is stamped with the item's id/key (`external_*`, and `jira_*` for Jira).
- `write_strategy=mcp` — Claude creates the items with its own connector and records the ids
  through `record_external_push`.

`push_plan_to_jira` stays as the pre-tracker entry point (the `/push-to-jira` alias).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.connectors import get_connector
from app.connectors.tracker import WorkTracker
from app.core.events import publish
from app.models.base import Provider, TaskType, TrackingMode, utcnow
from app.models.draft import DraftPlan, DraftTask
from app.models.integration import Connection
from app.models.project import Project, Task
from app.schemas.entities import (
    DraftFinalizeResult,
    DraftPushRecord,
    DraftPushResult,
    DraftPushTaskResult,
    DraftRecordPushResult,
)
from app.services import integration_policy, tracker_sync
from app.services.features import feature_enabled
from app.services.tracker_types import KIND_EPIC, KIND_ITEM, ItemDraft, ItemPatch, ItemRef, Scope
from app.services.workflow import TrackingError, initialise_native_task


class DraftPushError(Exception):
    """A precondition for finalising a plan failed (no plan, no/ambiguous connection, etc.)."""


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


async def _plan_tasks(session: AsyncSession, plan_id: int) -> list[DraftTask]:
    rows = await session.execute(select(DraftTask).where(DraftTask.plan_id == plan_id))
    return _ordered_tasks(list(rows.scalars().all()))


def _mark_synced(plan: DraftPlan) -> None:
    plan.status = "synced"
    plan.synced_at = utcnow()


# --------------------------------------------------------------------------- #
# Tracker push (mirrored projects)
# --------------------------------------------------------------------------- #


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
    binding = await tracker_sync.binding_for_project(session, project_id)
    if binding is not None and binding.provider == Provider.jira:
        found = await session.get(Connection, binding.connection_id)
        if found is not None:
            return found
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


async def _scope_for(session: AsyncSession, connection: Connection, project_id: int) -> Scope:
    binding = await tracker_sync.binding_for_project(session, project_id)
    if binding is not None and binding.connection_id == connection.id:
        return binding.scope
    legacy = tracker_sync.legacy_binding(connection)
    if legacy is not None:
        return legacy.scope
    return Scope(kind="project", values=dict(connection.config or {}))


def _existing_ref(task: DraftTask) -> ItemRef | None:
    ext_id = task.external_id or task.jira_issue_id
    if not ext_id:
        return None
    return ItemRef(external_id=ext_id, key=task.external_key or task.jira_key)


async def push_plan_to_tracker(
    session: AsyncSession,
    plan: DraftPlan,
    connection: Connection,
    user_id: int | None,
) -> tuple[int, int, int, list[DraftPushTaskResult]]:
    """Create/update the plan's items in the connection's tracker. Returns counts + results."""
    credential, reason = await integration_policy.resolve_write_credential(
        session, connection, user_id
    )
    if credential is None:
        raise DraftPushError(reason)
    tracker = get_connector(credential, session)
    if not isinstance(tracker, WorkTracker) or not tracker.capabilities.create_items:
        raise DraftPushError(
            f"{connection.provider.value} can't create items — use record-push after creating "
            "them with your own connector"
        )
    scope = await _scope_for(session, connection, plan.project_id)
    tasks = await _plan_tasks(session, plan.id or 0)
    by_id = {t.id: t for t in tasks}
    provider = str(connection.provider.value)
    results: list[DraftPushTaskResult] = []
    created = updated = failed = 0
    for task in tasks:
        assert task.id is not None
        parent = by_id.get(task.parent_id) if task.parent_id is not None else None
        try:
            ref = _existing_ref(task)
            if ref is not None:
                await tracker.update_item(
                    scope,
                    ref,
                    ItemPatch(
                        title=task.name, description=task.description, estimate=task.story_points
                    ),
                )
                updated += 1
                action = "updated"
            else:
                ref = await tracker.create_item(
                    scope,
                    ItemDraft(
                        title=task.name,
                        kind=KIND_EPIC if task.type == TaskType.summary else KIND_ITEM,
                        description=task.description,
                        estimate=task.story_points,
                        parent=_existing_ref(parent) if parent is not None else None,
                    ),
                )
                task.external_provider = provider
                task.external_id = ref.external_id
                task.external_key = ref.key
                if connection.provider == Provider.jira:
                    task.jira_issue_id = ref.external_id
                    task.jira_key = ref.key
                created += 1
                action = "created"
            results.append(
                DraftPushTaskResult(
                    draft_task_id=task.id,
                    name=task.name,
                    action=action,
                    jira_key=task.jira_key,
                    external_key=task.external_key or task.jira_key,
                )
            )
        except Exception as exc:  # surface per-task failure, keep pushing the rest
            failed += 1
            results.append(
                DraftPushTaskResult(
                    draft_task_id=task.id, name=task.name, action="failed", error=str(exc)
                )
            )
    return created, updated, failed, results


async def push_plan_to_jira(
    session: AsyncSession,
    plan_id: int,
    connection_id: int | None = None,
    user_id: int | None = None,
) -> DraftPushResult:
    """The pre-tracker push (`POST /draft-plans/{id}/push-to-jira`)."""
    plan = await session.get(DraftPlan, plan_id)
    if plan is None:
        raise DraftPushError("Draft plan not found")
    connection = await _resolve_jira_connection(session, plan.project_id, connection_id)
    assert connection.id is not None
    created, updated, failed, results = await push_plan_to_tracker(
        session, plan, connection, user_id
    )
    if failed == 0 and (created or updated):
        _mark_synced(plan)
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


# --------------------------------------------------------------------------- #
# Native materialisation
# --------------------------------------------------------------------------- #


async def materialize_native(
    session: AsyncSession, plan: DraftPlan, *, author: str | None
) -> tuple[int, int, list[DraftPushTaskResult]]:
    """Create (or update) a canopy task per draft task, parents first, then replan."""
    tasks = await _plan_tasks(session, plan.id or 0)
    native = await feature_enabled(session, "tracking.native")
    task_for: dict[int, int] = {}
    results: list[DraftPushTaskResult] = []
    created = updated = 0
    for draft in tasks:
        assert draft.id is not None
        parent_task = task_for.get(draft.parent_id) if draft.parent_id is not None else None
        existing = await session.get(Task, draft.task_id) if draft.task_id is not None else None
        if existing is not None and existing.project_id == plan.project_id:
            existing.name = draft.name
            existing.description = draft.description
            existing.duration = max(draft.estimate_days, 0)
            existing.story_points = draft.story_points
            if parent_task is not None:
                existing.parent_id = parent_task
            task = existing
            updated += 1
            action = "updated"
        else:
            task = Task(
                project_id=plan.project_id,
                parent_id=parent_task,
                name=draft.name,
                description=draft.description,
                type=draft.type,
                duration=max(draft.estimate_days, 0 if draft.type == TaskType.summary else 1),
                story_points=draft.story_points,
            )
            session.add(task)
            await session.flush()
            try:
                await initialise_native_task(
                    session, task, status=None, native_enabled=native, author=author
                )
            except TrackingError as exc:
                raise DraftPushError(exc.message) from exc
            draft.task_id = task.id
            created += 1
            action = "created"
        assert task.id is not None
        task_for[draft.id] = task.id
        results.append(
            DraftPushTaskResult(
                draft_task_id=draft.id,
                name=draft.name,
                action=action,
                task_id=task.id,
                external_key=task.key,
            )
        )
    await session.flush()
    await tracker_sync.replan(session, {plan.project_id})
    return created, updated, results


async def finalize_plan(
    session: AsyncSession,
    plan_id: int,
    *,
    connection_id: int | None,
    user_id: int | None,
    author: str | None,
) -> DraftFinalizeResult:
    """Finalise a plan into native tasks or the project's tracker (see the module docstring)."""
    plan = await session.get(DraftPlan, plan_id)
    if plan is None:
        raise DraftPushError("Draft plan not found")
    project = await session.get(Project, plan.project_id)
    if project is None:
        raise DraftPushError("Project not found")

    connection: Connection | None = None
    if connection_id is not None:
        connection = await session.get(Connection, connection_id)
        if connection is None:
            raise DraftPushError("Connection not found")
    elif project.tracking_mode == TrackingMode.mirrored.value:
        binding = await tracker_sync.binding_for_project(session, project.id or 0)
        if binding is None:
            raise DraftPushError(
                "This mirrored project has no tracker binding — bind one, or pass connection_id"
            )
        connection = await session.get(Connection, binding.connection_id)
        if connection is None:
            raise DraftPushError("The project's tracker connection is gone")

    if connection is not None:
        write = await integration_policy.resolve_write(session, connection.provider)
        if not write.allowed:
            raise DraftPushError(write.reason)
        created, updated, failed, results = await push_plan_to_tracker(
            session, plan, connection, user_id
        )
        if failed == 0 and (created or updated):
            _mark_synced(plan)
        await session.commit()
        await publish({"type": "draft_push", "project_id": plan.project_id, "plan_id": plan_id})
        return DraftFinalizeResult(
            plan_id=plan_id,
            mode="tracker",
            provider=connection.provider.value,
            connection_id=connection.id,
            created=created,
            updated=updated,
            failed=failed,
            results=results,
        )

    created, updated, results = await materialize_native(session, plan, author=author)
    _mark_synced(plan)
    await session.commit()
    await publish({"type": "draft_push", "project_id": plan.project_id, "plan_id": plan_id})
    await publish({"type": "replan", "project_id": plan.project_id})
    return DraftFinalizeResult(
        plan_id=plan_id,
        mode="native",
        created=created,
        updated=updated,
        failed=0,
        results=results,
    )


# --------------------------------------------------------------------------- #
# MCP write-back
# --------------------------------------------------------------------------- #


async def record_external_push(
    session: AsyncSession, plan_id: int, records: list[DraftPushRecord]
) -> DraftRecordPushResult:
    """Write-back for `write_strategy=mcp`: Claude created the tracker items itself, so it
    records each draft task's resulting id/key here and we flip the plan to `synced`.
    Idempotent — re-recording the same ids stamps the same values, so a re-push won't
    duplicate tickets."""
    plan = await session.get(DraftPlan, plan_id)
    if plan is None:
        raise DraftPushError("Draft plan not found")

    rows = await session.execute(select(DraftTask).where(DraftTask.plan_id == plan_id))
    by_id = {t.id: t for t in rows.scalars().all()}

    recorded = 0
    for record in records:
        task = by_id.get(record.draft_task_id)
        if task is None:
            raise DraftPushError(f"Draft task {record.draft_task_id} is not in plan {plan_id}")
        ext_id = record.external_id or record.jira_issue_id
        if not ext_id:
            raise DraftPushError(
                f"Draft task {record.draft_task_id}: pass external_id (or jira_issue_id)"
            )
        key = record.external_key or record.jira_key
        provider = record.provider or ("jira" if record.jira_issue_id else None)
        task.external_provider = provider
        task.external_id = ext_id
        task.external_key = key
        if provider in (None, "jira"):
            task.jira_issue_id = ext_id
            task.jira_key = key
        recorded += 1

    if recorded:
        _mark_synced(plan)
    await session.commit()
    await publish({"type": "draft_push", "project_id": plan.project_id, "plan_id": plan_id})
    return DraftRecordPushResult(plan_id=plan_id, recorded=recorded, status=plan.status)
