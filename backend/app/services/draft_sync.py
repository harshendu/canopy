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
  back. Each draft task is stamped with the item's provider, id and key (`external_*`).
- `write_strategy=mcp` — Claude creates the items with its own connector and records the ids
  through `record_external_push`.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.connectors import get_connector
from app.connectors.tracker import WorkTracker, is_tracker
from app.core.events import publish
from app.models.base import DocLinkEntity, TaskType, TrackingMode, utcnow
from app.models.doc import DocReference
from app.models.draft import DraftPlan, DraftTask
from app.models.integration import Connection
from app.models.project import Project, Task
from app.schemas.entities import (
    DraftFinalizeResult,
    DraftPushRecord,
    DraftPushTaskResult,
    DraftRecordPushResult,
)
from app.services import design_docs, integration_policy, tracker_sync
from app.services.features import feature_enabled
from app.services.tracker_types import KIND_EPIC, KIND_ITEM, ItemDraft, ItemPatch, ItemRef, Scope
from app.services.workflow import TrackingError, initialise_native_task


class DraftPushError(Exception):
    """A precondition for finalising a plan failed (no plan, no/ambiguous connection, etc.)."""


class DraftWriteBlockedError(DraftPushError):
    """The admin's integration policy doesn't let canopy write to this tracker directly
    (`write_strategy` mcp or disabled)."""


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


async def _scope_for(session: AsyncSession, connection: Connection, project_id: int) -> Scope:
    """The project's binding scope when it is bound through this connection, else an empty
    scope (the tracker's own defaults apply)."""
    binding = await tracker_sync.binding_for_project(session, project_id)
    if binding is not None and binding.connection_id == connection.id:
        return binding.scope
    return Scope(kind="project")


def _existing_ref(task: DraftTask, provider: str) -> ItemRef | None:
    """The item a draft task was already created as in this tracker (a re-push updates it)."""
    if not task.external_id or task.external_provider != provider:
        return None
    return ItemRef(external_id=task.external_id, key=task.external_key)


def cite_doc(description: str | None, doc: DocReference | None) -> str | None:
    """A ticket's description with the design doc it was planned from cited at the end (a
    content write — never status). Idempotent: a description that already carries the link is
    left alone. Pure."""
    if doc is None:
        return description
    if description and doc.url in description:
        return description
    line = f"Design doc: {doc.title or doc.url} — {doc.url}"
    return f"{description.rstrip()}\n\n{line}" if description else line


async def plan_source_doc(session: AsyncSession, plan: DraftPlan) -> DocReference | None:
    """The plan's source doc, when it may be cited on shared work: tracked, not personal, and
    shared at its source (a Claude doc shared in Claude)."""
    if plan.source_doc_id is None:
        return None
    doc = await session.get(DocReference, plan.source_doc_id)
    if doc is None or doc.private_to_user_id is not None:
        return None
    return doc if design_docs.shared_at_source(doc) else None


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
    source_doc = await plan_source_doc(session, plan)
    provider = str(connection.provider.value)
    results: list[DraftPushTaskResult] = []
    created = updated = failed = 0
    for task in tasks:
        assert task.id is not None
        parent = by_id.get(task.parent_id) if task.parent_id is not None else None
        try:
            ref = _existing_ref(task, provider)
            if ref is not None:
                await tracker.update_item(
                    scope,
                    ref,
                    ItemPatch(
                        title=task.name,
                        description=cite_doc(task.description, source_doc),
                        estimate=task.story_points,
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
                        description=cite_doc(task.description, source_doc),
                        estimate=task.story_points,
                        parent=_existing_ref(parent, provider) if parent is not None else None,
                    ),
                )
                task.external_provider = provider
                task.external_id = ref.external_id
                task.external_key = ref.key
                created += 1
                action = "created"
            results.append(
                DraftPushTaskResult(
                    draft_task_id=task.id,
                    name=task.name,
                    action=action,
                    external_key=task.external_key,
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
    # The doc the plan came from becomes context on every task it produced (§V9).
    source_doc = await plan_source_doc(session, plan)
    if source_doc is not None:
        for task_id in task_for.values():
            await design_docs.upsert_link(session, source_doc, DocLinkEntity.task, task_id)
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
            raise DraftWriteBlockedError(write.reason)
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
    bound = await tracker_sync.binding_for_project(session, plan.project_id)

    recorded = 0
    for record in records:
        task = by_id.get(record.draft_task_id)
        if task is None:
            raise DraftPushError(f"Draft task {record.draft_task_id} is not in plan {plan_id}")
        provider = record.provider or (bound.provider.value if bound is not None else None)
        if provider is None:
            raise DraftPushError(
                f"Draft task {record.draft_task_id}: name the tracker (provider) — the "
                "project is bound to none"
            )
        if not is_tracker(provider):
            raise DraftPushError(f"{provider} is not a work tracker")
        task.external_provider = provider
        task.external_id = record.external_id
        task.external_key = record.external_key
        recorded += 1

    if recorded:
        _mark_synced(plan)
    await session.commit()
    await publish({"type": "draft_push", "project_id": plan.project_id, "plan_id": plan_id})
    return DraftRecordPushResult(plan_id=plan_id, recorded=recorded, status=plan.status)
