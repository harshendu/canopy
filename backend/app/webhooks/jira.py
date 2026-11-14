"""Jira webhooks (`/webhooks/jira`, `X-Hub-Signature`) — the route existing installs point at.
Other trackers use the generic `/webhooks/{provider}` (`app/webhooks/trackers.py`)."""

from fastapi import APIRouter, Request, status

from app.core.config import settings
from app.core.db import async_session_factory
from app.models.base import Provider
from app.webhooks.security import require_valid_signature
from app.webhooks.trackers import route_payload

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

    # Match the issue to the canopy connection(s) whose bindings cover its Jira project (or a
    # legacy connection's `jira_project_key`), then enqueue async processing (never inline).
    hint = {"project_key": project_key} if project_key else {}
    # `async_session_factory` is read here (not in the shared helper) so tests can swap it.
    return await route_payload(Provider.jira, payload, hint, async_session_factory)
