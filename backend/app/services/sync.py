"""Orchestrates connector sync runs."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors import SyncResult, get_connector
from app.models.integration import Connection


async def _load_connection(session: AsyncSession, connection_id: int) -> Connection:
    connection = await session.get(Connection, connection_id)
    if connection is None:
        raise ValueError(f"Connection {connection_id} not found")
    return connection


async def run_full_sync(session: AsyncSession, connection_id: int) -> SyncResult:
    connection = await _load_connection(session, connection_id)
    connector = get_connector(connection, session)
    return await connector.full_sync()


async def run_incremental_sync(session: AsyncSession, connection_id: int) -> SyncResult:
    connection = await _load_connection(session, connection_id)
    connector = get_connector(connection, session)
    return await connector.incremental_sync()
