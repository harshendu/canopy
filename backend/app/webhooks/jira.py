from fastapi import APIRouter, Request, status
from sqlmodel import select

from app.core.config import settings
from app.core.db import async_session_factory
from app.models.base import Provider
from app.models.integration import Connection
from app.services import integration_policy
from app.services.features import feature_enabled
from app.webhooks.security import require_valid_signature
from app.workers.queue import enqueue

router = APIRouter()


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def jira_webhook(request: Request) -> dict:
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature")
    require_valid_signature(
        "JIRA_WEBHOOK_SECRET", settings.JIRA_WEBHOOK_SECRET, body, signature
    )

    payload = await request.json()
    issue = payload.get("issue") or {}
    issue_key = issue.get("key", "")
    project_key = issue_key.split("-")[0] if "-" in issue_key else None

    # Match the issue to the canopy connection(s) that sync its Jira project, then
    # enqueue async processing (never process inline).
    enqueued = 0
    async with async_session_factory() as session:
        if not await feature_enabled(session, "integrations.webhooks"):
            # Webhook intake is feature-gated off — ACK (so the sender doesn't disable the
            # hook) but ignore.
            return {"enqueued": 0, "ignored": "webhook intake is disabled by feature gate"}
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
