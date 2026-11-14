"""Signed webhooks from any work tracker: `POST /webhooks/{provider}` (USER_FLOWS §J0/§J3).

Same intake contract as every webhook here: verify the HMAC over the raw body **before**
parsing (the tracker's own `verify_webhook`, against `<PROVIDER>_WEBHOOK_SECRET`), fail closed
(403 while the secret is unset, 401 on a missing/forged signature), match the payload to the
connections whose bindings it belongs to (`webhook_scope_hint`), then enqueue `process_webhook`
— never process inline. `/webhooks/jira` keeps its own route (and header) for existing installs.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.connectors.tracker import tracker_class, tracker_enabled
from app.core.config import settings
from app.core.db import async_session_factory
from app.models.base import Provider
from app.models.integration import Connection
from app.services import integration_policy, tracker_sync
from app.services.features import feature_enabled
from app.workers.queue import enqueue

logger = logging.getLogger(__name__)

router = APIRouter()


def secret_setting(provider: str) -> str:
    return f"{provider.upper()}_WEBHOOK_SECRET"


async def matching_connection_ids(
    session: AsyncSession, provider: Provider, hint: dict[str, Any]
) -> list[int]:
    """Active connections of `provider` with a binding the payload's scope hint matches."""
    out: list[int] = []
    for connection in (
        await session.execute(
            select(Connection)
            .where(Connection.provider == provider, col(Connection.active).is_(True))
            .order_by(col(Connection.id))
        )
    ).scalars().all():
        bindings = await tracker_sync.bindings_for_connection(session, connection)
        if connection.id is not None and any(
            tracker_sync.scope_matches(b, hint) for b in bindings
        ):
            out.append(connection.id)
    return out


async def route_payload(
    provider: Provider,
    payload: dict[str, Any],
    hint: dict[str, Any],
    session_factory: Callable[[], Any],
) -> dict[str, Any]:
    """Gate checks, binding match and enqueue for a verified payload."""
    async with session_factory() as session:
        if not await feature_enabled(session, "integrations.webhooks"):
            # Intake is feature-gated off — ACK (so the sender doesn't disable the hook) but
            # ignore.
            return {"enqueued": 0, "ignored": "webhook intake is disabled by feature gate"}
        if not integration_policy.reads_direct(
            await integration_policy.get_setting(session, provider)
        ):
            # This tracker's reads are sourced via MCP/file by policy — ignore its webhooks.
            return {"enqueued": 0}
        ids = await matching_connection_ids(session, provider, hint)
    for connection_id in ids:
        await enqueue("process_webhook", connection_id, payload)
    return {"enqueued": len(ids)}


@router.post("/{provider}", status_code=status.HTTP_202_ACCEPTED)
async def tracker_webhook(provider: str, request: Request) -> dict[str, Any]:
    cls = tracker_class(provider)
    if cls is None or not cls.capabilities.webhooks or not tracker_enabled(provider):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown webhook")
    name = secret_setting(provider)
    secret = str(getattr(settings, name, "") or "")
    body = await request.body()
    if not secret:
        logger.warning("Rejected a webhook: %s is not set, so it can't be verified", name)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Webhook intake is disabled until {name} is configured",
        )
    if not cls.verify_webhook(request.headers, body, secret):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bad signature")
    try:
        payload = json.loads(body)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Bad JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Bad payload")
    return await route_payload(
        Provider(provider), payload, cls.webhook_scope_hint(payload), async_session_factory
    )
