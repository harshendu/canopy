"""A project's tracking: native or mirrored from a tracker, its binding, and switching between
them (USER_FLOWS §C12). The logic lives in `app/services/tracking.py`.

Reading is open; changing is planner-gated and ownership-scoped (§R6). A switch previews by
default (`dry_run`) and applying it is human-only — it re-assigns who owns every task's status,
and `publish` writes to the tracker. canopy never writes a status to a tracker.
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, status

from app.api.deps import (
    CurrentUser,
    FeatureGate,
    HumanOnly,
    PlannerWriter,
    SessionDep,
    TokenScopeDep,
    is_planner,
)
from app.connectors import get_connector
from app.connectors.tracker import (
    WorkTracker,
    enabled_tracker_keys,
    tracker_class,
    tracker_label,
)
from app.core.events import publish
from app.models.base import CANOPY_OWNER, TokenScope, TrackingMode
from app.models.integration import Connection, TrackerBinding
from app.models.project import Project
from app.schemas.entities import (
    ProjectTrackingRead,
    ProjectTrackingUpdate,
    TrackerBindingRead,
    TrackingPublishRead,
    TrackingSwitchActionRead,
    TrackingSwitchRequest,
    TrackingSwitchResult,
    TrackingSyncResult,
)
from app.services import integration_policy, tracker_sync
from app.services import tracking as tracking_service
from app.services.access import ensure_project_editable, project_can_edit

router = APIRouter()


async def _project(session: SessionDep, project_id: int) -> Project:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


async def binding_read(session: SessionDep, binding: TrackerBinding) -> TrackerBindingRead:
    assert binding.id is not None
    cls = tracker_class(binding.provider)
    connection = await session.get(Connection, binding.connection_id)
    return TrackerBindingRead(
        id=binding.id,
        connection_id=binding.connection_id,
        connection_name=connection.name if connection is not None else None,
        provider=str(binding.provider),
        label=cls.label if cls is not None and cls.label else str(binding.provider),
        scope_kind=binding.scope_kind,
        scope=dict(binding.scope or {}),
        mapping=dict(binding.mapping or {}),
        status_map=list(binding.status_map or []),
        sync_iterations=binding.sync_iterations,
        active=binding.active,
        last_synced_at=binding.last_synced_at,
        detached_at=binding.detached_at,
        created_at=binding.created_at,
    )


async def _tracking_read(
    session: SessionDep, user: CurrentUser, project: Project
) -> ProjectTrackingRead:
    assert project.id is not None
    binding = await tracking_service.active_binding(session, project.id)
    cls = tracker_class(binding.provider) if binding is not None else None
    tasks = await tracking_service.project_tasks(session, project.id)
    canopy_owned = sum(1 for t in tasks if t.status_owner == CANOPY_OWNER)
    return ProjectTrackingRead(
        project_id=project.id,
        mode=project.tracking_mode,
        binding=await binding_read(session, binding) if binding is not None else None,
        history=[
            await binding_read(session, b)
            for b in await tracking_service.past_bindings(session, project.id)
        ],
        capabilities=asdict(cls.capabilities) if cls is not None else None,
        canopy_owned=canopy_owned,
        tracker_owned=len(tasks) - canopy_owned,
        can_edit=is_planner(user) and await project_can_edit(session, user, project),
        trackers_enabled=enabled_tracker_keys(),
    )


@router.get("/projects/{project_id}/tracking", response_model=ProjectTrackingRead)
async def get_tracking(
    session: SessionDep, user: CurrentUser, project_id: int
) -> ProjectTrackingRead:
    """How the project is tracked: its mode, its tracker binding (and the trackers it used
    before), what that tracker supports and who owns how many statuses."""
    return await _tracking_read(session, user, await _project(session, project_id))


@router.put(
    "/projects/{project_id}/tracking",
    response_model=ProjectTrackingRead,
    dependencies=[FeatureGate("integrations")],
)
async def update_tracking(
    session: SessionDep, user: PlannerWriter, project_id: int, payload: ProjectTrackingUpdate
) -> ProjectTrackingRead:
    """Adjust the active binding in place (scope, type/field mapping, sprint mirroring). A new
    scope resets the binding's watermark and status map: the next sync is a full one."""
    project = await _project(session, project_id)
    await ensure_project_editable(session, user, project_id)
    binding = await tracking_service.active_binding(session, project_id)
    if binding is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "not_bound", "message": "The project has no tracker binding"},
        )
    cls = tracker_class(binding.provider)
    if cls is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Unknown tracker")
    try:
        if payload.scope is not None:
            scope = tracking_service.validated_scope(cls, payload.scope)
            if scope != dict(binding.scope or {}):
                binding.scope = scope
                binding.watermark = None
                binding.status_map = []
    except tracking_service.TrackingConfigError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if payload.mapping is not None:
        binding.mapping = dict(payload.mapping)
    if payload.sync_iterations is not None:
        binding.sync_iterations = payload.sync_iterations and cls.capabilities.iterations
    await session.commit()
    await publish({"type": "tracking", "project_id": project_id, "mode": project.tracking_mode})
    return await _tracking_read(session, user, project)


@router.post(
    "/projects/{project_id}/tracking/switch",
    response_model=TrackingSwitchResult,
    dependencies=[FeatureGate("integrations")],
)
async def switch_tracking(
    session: SessionDep,
    user: PlannerWriter,
    scope: TokenScopeDep,
    project_id: int,
    payload: TrackingSwitchRequest,
) -> TrackingSwitchResult:
    """Switch a project between native and mirrored tracking (or to another tracker). Returns
    the plan — what happens to every task — and, with `dry_run=false`, applies exactly that
    plan (human-only): detach the old binding (links kept as history), release its tasks to
    canopy (remapping statuses the native columns lack), bind the new tracker, adopt matched
    tasks / publish open ones, flip the mode, then run a first sync."""
    project = await _project(session, project_id)
    await ensure_project_editable(session, user, project_id)
    if not payload.dry_run and scope == TokenScope.agent:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Applying a tracking switch is reserved for a human (preview with dry_run).",
        )
    try:
        target = (
            await tracking_service.switch_target(
                session,
                connection_id=payload.connection_id,
                scope=payload.scope,
                mapping_in=payload.mapping,
                sync_iterations=payload.sync_iterations,
                user_id=user.id,
            )
            if payload.to_mode == TrackingMode.mirrored.value
            else None
        )
        plan = await tracking_service.plan_switch(
            session, project, to_mode=payload.to_mode, target=target, strategy=payload.strategy
        )
    except tracking_service.TrackingConfigError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    result = TrackingSwitchResult(
        project_id=project_id,
        from_mode=plan.from_mode,
        to_mode=plan.to_mode,
        from_provider=plan.from_provider,
        to_provider=plan.to_provider,
        strategy=plan.strategy,
        dry_run=payload.dry_run,
        applied=False,
        counts=plan.counts(),
        actions=[TrackingSwitchActionRead(**asdict(a)) for a in plan.actions],
        warnings=list(plan.warnings),
    )
    if payload.dry_run:
        return result

    binding = await tracking_service.apply_switch(session, project, plan, target=target)
    result.applied = True
    if binding is not None and target is not None:
        if plan.strategy == "publish" and target.writer is not None:
            published = await tracking_service.publish_canopy_tasks(
                session,
                project,
                binding,
                target.writer,
                only={a.task_id for a in plan.actions if a.action == "publish"},
            )
            result.published = TrackingPublishRead(
                created=published.created,
                skipped=published.skipped,
                failed=published.failed,
                errors=published.errors,
            )
            if published.failed:
                result.warnings.append(
                    f"{published.failed} task(s) could not be published — run Publish again"
                )
        try:
            created, updated = await tracking_service.initial_sync(target.reader, binding)
            result.synced_created, result.synced_updated = created, updated
        except Exception as exc:  # the switch stands; the next sync catches up
            await session.rollback()
            result.warnings.append(f"First sync failed ({exc}); run Sync now to retry")
        await session.refresh(binding)
        result.binding = await binding_read(session, binding)
    return result


@router.post(
    "/projects/{project_id}/tracking/publish",
    response_model=TrackingPublishRead,
    dependencies=[FeatureGate("integrations")],
)
async def publish_tracking(
    session: SessionDep, user: PlannerWriter, __: HumanOnly, project_id: int
) -> TrackingPublishRead:
    """Create the mirrored project's open canopy-owned tasks as items in its tracker (content
    only) and hand their status to it. Idempotent — re-run after a partial failure."""
    project = await _project(session, project_id)
    await ensure_project_editable(session, user, project_id)
    binding = await tracking_service.active_binding(session, project_id)
    if binding is None or project.tracking_mode != TrackingMode.mirrored.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "not_bound", "message": "The project has no tracker binding"},
        )
    connection = await session.get(Connection, binding.connection_id)
    if connection is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Connection is gone")
    credential, reason = await integration_policy.resolve_write_credential(
        session, connection, user.id
    )
    writer = get_connector(credential, session) if credential is not None else None
    if not isinstance(writer, WorkTracker) or not writer.capabilities.create_items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=reason if credential is None else f"{tracker_label(connection.provider)} "
            "can't create items",
        )
    published = await tracking_service.publish_canopy_tasks(session, project, binding, writer)
    await publish({"type": "tracking", "project_id": project_id, "mode": project.tracking_mode})
    return TrackingPublishRead(
        created=published.created,
        skipped=published.skipped,
        failed=published.failed,
        errors=published.errors,
    )


@router.post(
    "/projects/{project_id}/tracking/sync",
    response_model=TrackingSyncResult,
    dependencies=[FeatureGate("integrations")],
)
async def sync_tracking(
    session: SessionDep, user: PlannerWriter, project_id: int, full: bool = False
) -> TrackingSyncResult:
    """Pull this project's binding now (incremental by default; `full` re-reads everything and
    refreshes the tracker's status map) with the caller's credential when they connected one."""
    await _project(session, project_id)
    view = await tracker_sync.binding_for_project(session, project_id)
    if view is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "not_bound", "message": "The project has no tracker binding"},
        )
    connection = await session.get(Connection, view.connection_id)
    if connection is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Connection is gone")
    credential = await integration_policy.resolve_read_credential(session, connection, user.id)
    tracker = get_connector(credential, session) if credential is not None else None
    if not isinstance(tracker, WorkTracker) or not tracker.capabilities.direct_read:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "not_directly_readable",
                "message": f"canopy doesn't read {tracker_label(connection.provider)} directly "
                "here — its items arrive by MCP or file ingest",
            },
        )
    result = await tracker_sync.sync_binding(tracker, view, full=full)
    return TrackingSyncResult(
        provider=result.provider,
        created=result.created,
        updated=result.updated,
        skipped=result.skipped,
    )
