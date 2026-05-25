"""Connection lifecycle: list (with per-provider policy) + create/delete (architect-gated)."""

from __future__ import annotations

from fastapi import APIRouter, status
from sqlmodel import col, select

from app.api.deps import ArchitectWriter, CurrentUser, SessionDep
from app.core.crypto import encrypt_token
from app.models.base import ReadStrategy, WriteStrategy
from app.models.integration import Connection, IntegrationSetting, UserConnection
from app.schemas.entities import ConnectionCreate, ConnectionRead

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


@router.post("/connections", response_model=ConnectionRead, status_code=status.HTTP_201_CREATED)
async def create_connection(
    session: SessionDep, _: ArchitectWriter, payload: ConnectionCreate
) -> Connection:
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
    await session.commit()
    await session.refresh(connection)
    return connection


@router.delete("/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connection(session: SessionDep, _: ArchitectWriter, connection_id: int) -> None:
    connection = await session.get(Connection, connection_id)
    if connection is not None:
        await session.delete(connection)
        await session.commit()
