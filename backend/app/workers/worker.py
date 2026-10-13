"""arq worker: webhook processing + the Jira reconciliation poll (cron)."""

from __future__ import annotations

from typing import Any, ClassVar

from arq import cron

from app.connectors import get_connector
from app.core.config import settings
from app.core.db import async_session_factory
from app.core.startup_checks import ensure_secure_secret_key
from app.models.base import Provider
from app.models.integration import Connection
from app.services import integration_policy
from app.workers.queue import redis_settings


async def jira_incremental_sync(ctx: dict[str, Any]) -> dict[int, dict[str, int]]:
    """Reconciliation poll — the correctness backstop behind webhooks."""
    summary: dict[int, dict[str, int]] = {}
    async with async_session_factory() as session:
        setting = await integration_policy.get_setting(session, Provider.jira)
        if not integration_policy.reads_direct(setting):
            # Jira reads are sourced via MCP/file by policy — canopy's poll stands down.
            return summary
        connections = await integration_policy.usable_direct_connections(session, Provider.jira)
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


async def capture_risk_snapshots(ctx: dict[str, Any]) -> dict[str, int]:
    """Nightly sweep: snapshot every project's risk score so the timeline is a real trend."""
    from app.api.v1.risk import run_risk_snapshots

    async with async_session_factory() as session:
        count = await run_risk_snapshots(session)
    return {"snapshots": count}


async def poll_file_drops(ctx: dict[str, Any]) -> dict[str, dict]:
    """Ingest any export files dropped into the configured shared storage (no-op when unset)."""
    from app.services.file_drop import get_drop_storage, process_drops

    storage = get_drop_storage()
    if storage is None:
        return {}
    async with async_session_factory() as session:
        return await process_drops(session, storage)


async def startup(ctx: dict[str, Any]) -> None:
    """Refuse to run on a guessable SECRET_KEY: the worker encrypts refreshed connector tokens
    with a key derived from it unless TOKEN_ENCRYPTION_KEY is set."""
    ensure_secure_secret_key()


_poll_minutes = set(range(0, 60, max(1, min(settings.JIRA_POLL_MINUTES, 30))))
_drop_minutes = set(range(0, 60, max(1, min(settings.FILE_DROP_POLL_MINUTES, 30))))


class WorkerSettings:
    functions: ClassVar = [
        jira_incremental_sync,
        process_webhook,
        capture_risk_snapshots,
        poll_file_drops,
    ]
    cron_jobs: ClassVar = [
        cron(jira_incremental_sync, minute=_poll_minutes, run_at_startup=False),
        # Nightly risk snapshot (03:00) — the trend matters more than any single value.
        cron(capture_risk_snapshots, hour={3}, minute={0}, run_at_startup=False),
        cron(poll_file_drops, minute=_drop_minutes, run_at_startup=False),
    ]
    on_startup = startup
    redis_settings = redis_settings()
