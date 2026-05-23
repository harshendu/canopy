"""Activity feed + CI/observability event ingest (§J8). The feed surfaces deploys, build
failures, and incidents; an `incident_open` event auto-opens a postmortem (§P2)."""

from fastapi import APIRouter, HTTPException, status
from sqlmodel import col, select

from app.api.deps import CurrentUser, PlannerWriter, SessionDep
from app.models.activity import ActivityEvent
from app.models.project import Project
from app.schemas.entities import ActivityEventCreate, ActivityEventRead
from app.services.activity import record_activity

router = APIRouter()


@router.get("/projects/{project_id}/activity", response_model=list[ActivityEventRead])
async def list_activity(
    session: SessionDep, _: CurrentUser, project_id: int, limit: int = 100
) -> list[ActivityEvent]:
    result = await session.execute(
        select(ActivityEvent)
        .where(ActivityEvent.project_id == project_id)
        .order_by(col(ActivityEvent.id).desc())
        .limit(limit)
    )
    return list(result.scalars().all())


@router.post(
    "/projects/{project_id}/activity",
    response_model=ActivityEventRead,
    status_code=status.HTTP_201_CREATED,
)
async def ingest_activity(
    session: SessionDep, _: PlannerWriter, project_id: int, payload: ActivityEventCreate
) -> ActivityEvent:
    """Record a CI/observability event (also exposed as an unauthenticated HMAC webhook at
    `/webhooks/events`). An `incident_open` auto-opens a postmortem."""
    if await session.get(Project, project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return await record_activity(
        session,
        project_id=project_id,
        kind=payload.kind,
        summary=payload.summary,
        component_id=payload.component_id,
        source=payload.source,
        reference=payload.reference,
    )
