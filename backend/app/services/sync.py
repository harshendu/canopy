"""Orchestrates connector sync runs.

A sync triggered by a user runs against *their* credential when they've connected one (and the
provider allows per-user connect), otherwise the shared service token — resolved by the
integration policy. Background syncs (the reconciliation poll) pass no user and use the shared
token directly.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors import SyncResult, get_connector
from app.models.integration import Connection
from app.services import integration_policy


class SyncUnavailableError(ValueError):
    """The connection can't be synced directly: policy routes its reads via MCP/file, or no
    usable credential is available (neither a shared token nor the caller's own)."""


async def _load_connection(session: AsyncSession, connection_id: int) -> Connection:
    connection = await session.get(Connection, connection_id)
    if connection is None:
        raise ValueError(f"Connection {connection_id} not found")
    return connection


async def run_full_sync(
    session: AsyncSession, connection_id: int, user_id: int | None = None
) -> SyncResult:
    connection = await _load_connection(session, connection_id)
    credential = await integration_policy.resolve_read_credential(session, connection, user_id)
    if credential is None:
        raise SyncUnavailableError(
            f"{connection.provider.value} reads are not available directly for this connection"
        )
    return await get_connector(credential, session).full_sync()


async def run_incremental_sync(
    session: AsyncSession, connection_id: int, user_id: int | None = None
) -> SyncResult:
    connection = await _load_connection(session, connection_id)
    credential = await integration_policy.resolve_read_credential(session, connection, user_id)
    if credential is None:
        raise SyncUnavailableError(
            f"{connection.provider.value} reads are not available directly for this connection"
        )
    return await get_connector(credential, session).incremental_sync()
