"""Connection lifecycle: list (with per-provider policy) + create/delete (architect-gated).
A tracker connection created with a canopy project binds it (USER_FLOWS §J1/§C12)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from sqlmodel import col, select

from app.api.deps import ArchitectWriter, CurrentUser, SessionDep
from app.connectors.tracker import is_tracker, tracker_class, tracker_enabled, tracker_label
from app.core.crypto import encrypt_token
from app.models.base import Provider, ReadStrategy, TrackingMode, WriteStrategy, utcnow
from app.models.integration import (
    Connection,
    ExternalRef,
    IntegrationSetting,
    TrackerBinding,
    UserConnection,
)
from app.models.project import Project
from app.schemas.entities import ConnectionCreate, ConnectionRead
from app.services import tracker_sync
from app.services import tracking as tracking_service

router = APIRouter()


@router.get("/connections", response_model=list[ConnectionRead])
async def list_connections(session: SessionDep, user: CurrentUser) -> list[ConnectionRead]:
    connections = list((await session.execute(select(Connection))).scalars().all())
    # Per-provider policy (allow_user_connect + read/write strategy) + which connections the
    # caller has connected their own account to.
    settings_rows = list((await session.execute(select(IntegrationSetting))).scalars().all())
    allow_by_provider = {s.provider: s.allow_user_connect for s in settings_rows}
    setting_by_provider = {s.provider: s for s in settings_rows}
    my_connected = {
        uc.connection_id
        for uc in (
            await session.execute(
                select(UserConnection).where(
                    UserConnection.user_id == user.id, col(UserConnection.active).is_(True)
                )
            )
        ).scalars().all()
        if uc.authorized
    }
    return [
        ConnectionRead(
            id=c.id if c.id is not None else 0,
            provider=c.provider,
            name=c.name,
            config=c.config,
            watermark=c.watermark,
            active=c.active,
            authorized=c.authorized,
            allow_user_connect=allow_by_provider.get(c.provider, False),
            user_connected=c.id in my_connected,
            read_strategy=(
                setting_by_provider[c.provider].read_strategy
                if c.provider in setting_by_provider
                else ReadStrategy.direct
            ),
            write_strategy=(
                setting_by_provider[c.provider].write_strategy
                if c.provider in setting_by_provider
                else WriteStrategy.direct
            ),
        )
        for c in connections
    ]


def _scope_from_config(provider: Provider, config: dict) -> dict[str, Any]:
    """The binding scope a new tracker connection's config describes: every key of the
    tracker's `scope_schema` found in it (plus Jira's `jira_project_key` → `project_key`),
    validated."""
    scope = tracker_sync.config_scope(config)
    cls = tracker_class(provider)
    if cls is None:
        return scope
    for name in cls.scope_schema.model_fields:
        if name not in scope and config.get(name) not in (None, ""):
            scope[name] = config[name]
    try:
        return tracking_service.validated_scope(cls, scope)
    except tracking_service.TrackingConfigError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/connections", response_model=ConnectionRead, status_code=status.HTTP_201_CREATED)
async def create_connection(
    session: SessionDep, _: ArchitectWriter, payload: ConnectionCreate
) -> Connection:
    """Create a connection. A tracker connection given a canopy `project_id` (the Connectors
    form's project picker) also binds that project to it — mirrored from the tracker's project
    in the config — the same as a switch that keeps the project's existing work separate."""
    if is_tracker(payload.provider) and "project_id" in (payload.config or {}):
        # The pre-binding shape (retired): refused rather than silently not binding anything.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="config.project_id is not read — pass project_id beside config to mirror "
            "a project from this tracker connection",
        )
    target_id = payload.project_id
    if target_id is not None and not is_tracker(payload.provider):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Only a work tracker connection mirrors a project, not "
            f"{payload.provider.value}",
        )
    if target_id is not None and not tracker_enabled(payload.provider):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{tracker_label(payload.provider)} is not enabled on this instance "
            "(TRACKERS_ENABLED) — it can't mirror a project",
        )
    project = await session.get(Project, target_id) if target_id is not None else None
    if target_id is not None and project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if project is not None and project.id is not None:
        bound = await tracking_service.active_binding(session, project.id)
        if bound is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "project_already_bound",
                    "message": f"{project.key} is already mirrored from "
                    f"{tracker_label(bound.provider)} — switch its tracking instead",
                },
            )
    connection = Connection(
        provider=payload.provider,
        name=payload.name,
        config=payload.config,
        encrypted_token=encrypt_token(payload.token) if payload.token else None,
        encrypted_refresh_token=(
            encrypt_token(payload.refresh_token) if payload.refresh_token else None
        ),
    )
    session.add(connection)
    await session.flush()
    if project is not None and project.id is not None and connection.id is not None:
        session.add(
            TrackerBinding(
                connection_id=connection.id,
                provider=payload.provider,
                target_type="project",
                target_id=project.id,
                scope_kind="project",
                scope=_scope_from_config(payload.provider, payload.config),
                mapping=tracker_sync.config_mapping(payload.config),
                sync_iterations=bool(payload.config.get("board_id")),
            )
        )
        project.tracking_mode = TrackingMode.mirrored.value
    await session.commit()
    await session.refresh(connection)
    return connection


@router.delete("/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connection(session: SessionDep, _: ArchitectWriter, connection_id: int) -> None:
    """Remove a connection. One that still feeds a project is refused (409
    `connection_in_use` — switch those projects to native or another tracker first). One that
    other records still name (synced refs, past bindings, links, personal credentials) is
    deactivated rather than deleted, so that history keeps its meaning; else it is deleted."""
    connection = await session.get(Connection, connection_id)
    if connection is None:
        return
    feeding = (
        await session.execute(
            select(TrackerBinding).where(
                TrackerBinding.connection_id == connection_id,
                TrackerBinding.scope_kind != "subtree",
                col(TrackerBinding.active).is_(True),
            )
        )
    ).scalars().all()
    if feeding:
        projects = sorted({b.target_id for b in feeding})
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "connection_in_use",
                "message": "Projects are still mirrored from this connection — switch their "
                "tracking first",
                "project_ids": projects,
            },
        )
    referenced = False
    for model, column in (
        (TrackerBinding, TrackerBinding.connection_id),
        (ExternalRef, ExternalRef.connection_id),
        (UserConnection, UserConnection.connection_id),
    ):
        if (await session.execute(select(model).where(column == connection_id))).first():
            referenced = True
            break
    if referenced:
        now = utcnow()
        for link in (
            await session.execute(
                select(TrackerBinding).where(
                    TrackerBinding.connection_id == connection_id,
                    col(TrackerBinding.active).is_(True),
                )
            )
        ).scalars().all():
            link.active = False
            link.detached_at = now
        connection.active = False
    else:
        await session.delete(connection)
    await session.commit()
