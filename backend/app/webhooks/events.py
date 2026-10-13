from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from app.core.config import settings
from app.core.db import async_session_factory
from app.models.base import ActivityKind
from app.services.activity import record_activity
from app.webhooks.security import require_valid_signature

router = APIRouter()

_KINDS = {k.value for k in ActivityKind}


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def events_webhook(request: Request) -> dict[str, Any]:
    """Generic CI/observability receiver. Body: {project_id, kind|type, summary?,
    component_id?, reference?}. kind is deploy|build_failure|incident_open|incident_close.
    Lightweight enough to record inline (an `incident_open` auto-opens a postmortem)."""
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")
    require_valid_signature(
        "EVENTS_WEBHOOK_SECRET", settings.EVENTS_WEBHOOK_SECRET, body, signature
    )

    payload = await request.json()
    project_id = payload.get("project_id")
    kind = payload.get("kind") or payload.get("type")
    if not isinstance(project_id, int) or kind not in _KINDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="project_id (int) and a valid kind/type are required",
        )
    async with async_session_factory() as session:
        await record_activity(
            session,
            project_id=project_id,
            kind=kind,
            summary=str(payload.get("summary") or kind),
            component_id=payload.get("component_id"),
            source="webhook",
            reference=payload.get("reference"),
        )
    return {"recorded": True}
