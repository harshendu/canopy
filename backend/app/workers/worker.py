"""arq worker: webhook processing + the Jira reconciliation poll (cron)."""

from __future__ import annotations

from typing import Any, ClassVar

from arq import cron
from sqlmodel import select

from app.connectors import get_connector
from app.core.config import settings
from app.core.db import async_session_factory
from app.models.base import Provider
from app.models.integration import Connection
from app.workers.queue import redis_settings


async def jira_incremental_sync(ctx: dict[str, Any]) -> dict[int, dict[str, int]]:
    """Reconciliation poll — the correctness backstop behind webhooks."""
    summary: dict[int, dict[str, int]] = {}
    async with async_session_factory() as session:
        connections = (
            await session.execute(
                select(Connection).where(
                    Connection.provider == Provider.jira, Connection.active == True  # noqa: E712
                )
            )
        ).scalars().all()
        for connection in connections:
            if connection.id is None:
                continue
            connector = get_connector(connection, session)
            result = await connector.incremental_sync()
            summary[connection.id] = {"created": result.created, "updated": result.updated}
    return summary


async def process_webhook(ctx: dict[str, Any], connection_id: int, payload: dict[str, Any]) -> None:
    async with async_session_factory() as session:
        connection = await session.get(Connection, connection_id)
        if connection is not None:
            await get_connector(connection, session).handle_webhook(payload)


_poll_minutes = set(range(0, 60, max(1, min(settings.JIRA_POLL_MINUTES, 30))))


class WorkerSettings:
    functions: ClassVar = [jira_incremental_sync, process_webhook]
    cron_jobs: ClassVar = [cron(jira_incremental_sync, minute=_poll_minutes, run_at_startup=False)]
    redis_settings = redis_settings()
