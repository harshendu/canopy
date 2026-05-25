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
async def jira_webhook(request: Request) -> dict:
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature")
    if not verify_hmac_sha256(settings.JIRA_WEBHOOK_SECRET, body, signature):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bad signature")

    payload = await request.json()
    issue = payload.get("issue") or {}
    issue_key = issue.get("key", "")
    project_key = issue_key.split("-")[0] if "-" in issue_key else None

    # Match the issue to the canopy connection(s) that sync its Jira project, then
    # enqueue async processing (never process inline).
    enqueued = 0
    async with async_session_factory() as session:
        if not integration_policy.reads_direct(
            await integration_policy.get_setting(session, Provider.jira)
        ):
            # Jira reads are sourced via MCP/file by policy — ignore inbound webhooks.
            return {"enqueued": 0}
        connections = (
            await session.execute(
                select(Connection).where(
                    Connection.provider == Provider.jira, Connection.active == True  # noqa: E712
                )
            )
        ).scalars().all()
    for connection in connections:
        if project_key and connection.config.get("jira_project_key") not in (None, project_key):
            continue
        await enqueue("process_webhook", connection.id, payload)
        enqueued += 1
    return {"enqueued": enqueued}
