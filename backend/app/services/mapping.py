"""Idempotent mapping between external objects and canopy entities.

An `ExternalRef` is keyed on (provider, external id, entity type, connection): two sites of one
provider may share numeric ids, so a ref names the connection it came from. Legacy rows from
before connections were recorded have a NULL `connection_id` and still match any connection.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.models.base import Provider, utcnow
from app.models.integration import ExternalRef


async def get_ref(
    session: AsyncSession,
    provider: Provider,
    external_id: str,
    entity_type: str,
    connection_id: int | None = None,
) -> ExternalRef | None:
    rows = (
        await session.execute(
            select(ExternalRef)
            .where(
                ExternalRef.provider == provider,
                ExternalRef.external_id == external_id,
                ExternalRef.entity_type == entity_type,
            )
            .order_by(col(ExternalRef.id))
        )
    ).scalars().all()
    if not rows:
        return None
    if connection_id is not None:
        exact = next((r for r in rows if r.connection_id == connection_id), None)
        if exact is not None:
            return exact
        legacy = next((r for r in rows if r.connection_id is None), None)
        return legacy
    return next((r for r in rows if r.connection_id is None), rows[0])


async def upsert_ref(
    session: AsyncSession,
    *,
    provider: Provider,
    external_id: str,
    entity_type: str,
    entity_id: int,
    external_key: str | None = None,
    remote_updated: str | None = None,
    connection_id: int | None = None,
) -> ExternalRef:
    ref = await get_ref(session, provider, external_id, entity_type, connection_id)
    now = utcnow()
    if ref is None:
        ref = ExternalRef(
            provider=provider,
            external_id=external_id,
            entity_type=entity_type,
            entity_id=entity_id,
            external_key=external_key,
            remote_updated=remote_updated,
            last_synced_at=now,
            connection_id=connection_id,
        )
        session.add(ref)
    else:
        ref.entity_id = entity_id
        ref.external_key = external_key
        ref.remote_updated = remote_updated
        ref.last_synced_at = now
        ref.detached_at = None
        if ref.connection_id is None and connection_id is not None:
            ref.connection_id = connection_id
    return ref


def is_stale(ref: ExternalRef | None, remote_updated: str | None) -> bool:
    """True if the incoming payload is newer than what we last synced (or new). A detached ref
    (the project stopped mirroring this tracker, then re-attached) is always refreshed."""
    if ref is None or ref.remote_updated is None or remote_updated is None:
        return True
    if ref.detached_at is not None:
        return True
    return remote_updated > ref.remote_updated


def detach(ref: ExternalRef, when: datetime | None = None) -> None:
    ref.detached_at = when or utcnow()
