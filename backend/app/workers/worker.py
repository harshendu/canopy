"""arq worker: webhook processing, the tracker reconciliation poll and nightly jobs (cron)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, ClassVar

from arq import cron
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors import get_connector
from app.connectors.tracker import WorkTracker, enabled_tracker_keys, tracker_class
from app.core.config import settings
from app.core.db import async_session_factory
from app.core.startup_checks import ensure_secure_secret_key
from app.models.base import Provider
from app.models.integration import Connection
from app.services import integration_policy, tracker_sync
from app.services.tracker_types import TrackerCapabilities
from app.workers.queue import redis_settings

logger = logging.getLogger(__name__)


async def _direct_tracker_connections(
    session: AsyncSession, *, needs: Callable[[TrackerCapabilities], bool] | None = None
) -> list[Connection]:
    """Usable connections of every enabled tracker canopy reads directly (policy permitting)."""
    out: list[Connection] = []
    for key in enabled_tracker_keys():
        provider = Provider(key)
        cls = tracker_class(provider)
        if cls is None or not cls.capabilities.direct_read:
            continue
        if needs is not None and not needs(cls.capabilities):
            continue
        if not integration_policy.reads_direct(
            await integration_policy.get_setting(session, provider)
        ):
            # This tracker's reads are sourced via MCP/file by policy — canopy stands down.
            continue
        out.extend(await integration_policy.usable_direct_connections(session, provider))
    return out


async def tracker_incremental_sync(ctx: dict[str, Any]) -> dict[int, dict[str, int]]:
    """Reconciliation poll over every bound tracker — the correctness backstop behind webhooks.
    One failing connection is logged and skipped; it never stops the others."""
    summary: dict[int, dict[str, int]] = {}
    async with async_session_factory() as session:
        for connection in await _direct_tracker_connections(session):
            if connection.id is None:
                continue
            try:
                result = await get_connector(connection, session).incremental_sync()
            except Exception:  # keep polling the rest
                logger.exception("Tracker poll failed for connection %s", connection.id)
                await session.rollback()
                continue
            summary[connection.id] = {"created": result.created, "updated": result.updated}
    return summary


async def tracker_history_backfill(ctx: dict[str, Any]) -> dict[int, int]:
    """Nightly: top up exact status history from each tracker's changelog, bounded per binding."""
    summary: dict[int, int] = {}
    async with async_session_factory() as session:
        for connection in await _direct_tracker_connections(
            session, needs=lambda caps: caps.status_history
        ):
            if connection.id is None:
                continue
            connector = get_connector(connection, session)
            if not isinstance(connector, WorkTracker):
                continue
            try:
                for binding in await tracker_sync.bindings_for_connection(session, connection):
                    added = await tracker_sync.backfill_pending(connector, binding)
                    summary[connection.id] = summary.get(connection.id, 0) + added
            except Exception:  # keep backfilling the rest
                logger.exception("History backfill failed for connection %s", connection.id)
                await session.rollback()
    return summary


async def _claude_sync(full: bool) -> dict[int, dict[str, Any]]:
    """The organization artifact sync (USER_FLOWS §V11) over its connection, if one is
    configured and the integration policy reads it directly. Metadata only."""
    from app.services import claude_sync

    summary: dict[int, dict[str, Any]] = {}
    async with async_session_factory() as session:
        connection = await claude_sync.active_connection(session)
        if connection is None or connection.id is None:
            return summary
        try:
            report = await claude_sync.sync_connection(
                claude_sync.connector_for(connection, session), full=full
            )
        except Exception:  # a failed listing never takes the worker down
            logger.exception("Claude artifact sync failed for connection %s", connection.id)
            await session.rollback()
            return summary
        summary[connection.id] = report.as_config()
    return summary


async def claude_artifact_sync(ctx: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """What changed since the last listing (the watermark less an overlap window)."""
    return await _claude_sync(full=False)


async def claude_artifact_full_sync(ctx: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """Nightly unfiltered listing: the only way to see sharing changes made through folders
    and artifacts that no longer exist."""
    return await _claude_sync(full=True)


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


_poll_minutes = set(range(0, 60, max(1, min(settings.TRACKER_POLL_MINUTES, 30))))
_drop_minutes = set(range(0, 60, max(1, min(settings.FILE_DROP_POLL_MINUTES, 30))))
# Every N minutes below an hour; hourly at :15 at or above it (arq crons are minute/hour sets).
_claude_minutes = (
    set(range(0, 60, settings.CLAUDE_SYNC_MINUTES))
    if 0 < settings.CLAUDE_SYNC_MINUTES < 60
    else {15}
)


class WorkerSettings:
    functions: ClassVar = [
        tracker_incremental_sync,
        tracker_history_backfill,
        process_webhook,
        capture_risk_snapshots,
        poll_file_drops,
        claude_artifact_sync,
        claude_artifact_full_sync,
    ]
    cron_jobs: ClassVar = [
        cron(tracker_incremental_sync, minute=_poll_minutes, run_at_startup=False),
        # Nightly risk snapshot (03:00) — the trend matters more than any single value.
        cron(capture_risk_snapshots, hour={3}, minute={0}, run_at_startup=False),
        # Nightly changelog top-up (03:30), after the snapshot.
        cron(tracker_history_backfill, hour={3}, minute={30}, run_at_startup=False),
        cron(poll_file_drops, minute=_drop_minutes, run_at_startup=False),
        # The organization artifact sync (no-op unless a `claude` connection exists).
        cron(claude_artifact_sync, minute=_claude_minutes, run_at_startup=False),
        cron(claude_artifact_full_sync, hour={4}, minute={0}, run_at_startup=False),
    ]
    on_startup = startup
    redis_settings = redis_settings()
