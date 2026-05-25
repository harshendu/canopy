from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from sqlmodel import select

from app.core.config import settings
from app.core.db import async_session_factory
from app.models.base import Provider
from app.models.integration import Connection
from app.services import integration_policy
from app.webhooks.security import verify_hmac_sha256
from app.workers.queue import enqueue

router = APIRouter()


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def github_webhook(request: Request) -> dict[str, Any]:
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")
    if not verify_hmac_sha256(settings.GITHUB_WEBHOOK_SECRET, body, signature):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bad signature")

    payload = await request.json()
    full_name = (payload.get("repository") or {}).get("full_name")

    # Match the repo to the canopy connection(s) that track it, then enqueue async
    # processing (verify-before-parse, ACK fast, never process inline).
    enqueued = 0
    async with async_session_factory() as session:
        if not integration_policy.reads_direct(
            await integration_policy.get_setting(session, Provider.github)
        ):
            # GitHub reads are sourced via MCP/file by policy — ignore inbound webhooks.
            return {"enqueued": 0}
        connections = (
            await session.execute(
                select(Connection).where(
                    Connection.provider == Provider.github,
                    Connection.active == True,  # noqa: E712
                )
            )
        ).scalars().all()
    for connection in connections:
        owner = connection.config.get("owner")
        repo = connection.config.get("repo")
        if full_name and f"{owner}/{repo}" != full_name:
            continue
        await enqueue("process_webhook", connection.id, payload)
        enqueued += 1
    return {"enqueued": enqueued}
