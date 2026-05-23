"""CI / observability event ingest. Records an ActivityEvent and, for incidents,
auto-opens a postmortem (§P2) — shared by the authenticated API and the webhook receiver."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import ActivityEvent
from app.models.base import ActivityKind, RetrospectiveKind
from app.models.retro import Retrospective

_POSTMORTEM_TEMPLATE = (
    "# Incident postmortem\n\n_Auto-opened from an incident event._\n\n"
    "## Timeline\n\n## Impact\n\n## Root cause\n\n## Action items\n"
)


async def record_activity(
    session: AsyncSession,
    *,
    project_id: int,
    kind: str,
    summary: str,
    component_id: int | None = None,
    source: str = "webhook",
    reference: str | None = None,
) -> ActivityEvent:
    event = ActivityEvent(
        project_id=project_id,
        kind=kind,
        summary=summary,
        component_id=component_id,
        source=source,
        reference=reference,
    )
    session.add(event)
    if kind == ActivityKind.incident_open:
        session.add(
            Retrospective(
                project_id=project_id,
                kind=RetrospectiveKind.incident_postmortem,
                title=f"Postmortem: {summary}"[:200],
                body=_POSTMORTEM_TEMPLATE,
                affected_component_ids=[component_id] if component_id is not None else [],
            )
        )
    await session.commit()
    await session.refresh(event)
    return event
