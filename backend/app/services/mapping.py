"""Idempotent mapping between external objects and canopy entities."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.base import Provider
from app.models.integration import ExternalRef


async def get_ref(
    session: AsyncSession, provider: Provider, external_id: str, entity_type: str
) -> ExternalRef | None:
    result = await session.execute(
        select(ExternalRef).where(
            ExternalRef.provider == provider,
            ExternalRef.external_id == external_id,
            ExternalRef.entity_type == entity_type,
        )
    )
    return result.scalar_one_or_none()


async def upsert_ref(
    session: AsyncSession,
    *,
    provider: Provider,
    external_id: str,
    entity_type: str,
    entity_id: int,
    external_key: str | None = None,
    remote_updated: str | None = None,
) -> ExternalRef:
    ref = await get_ref(session, provider, external_id, entity_type)
    now = datetime.now(UTC)
    if ref is None:
        ref = ExternalRef(
            provider=provider,
            external_id=external_id,
            entity_type=entity_type,
            entity_id=entity_id,
            external_key=external_key,
            remote_updated=remote_updated,
            last_synced_at=now,
        )
        session.add(ref)
    else:
        ref.entity_id = entity_id
        ref.external_key = external_key
        ref.remote_updated = remote_updated
        ref.last_synced_at = now
    return ref


def is_stale(ref: ExternalRef | None, remote_updated: str | None) -> bool:
    """True if the incoming payload is newer than what we last synced (or new)."""
    if ref is None or ref.remote_updated is None or remote_updated is None:
        return True
    return remote_updated > ref.remote_updated
