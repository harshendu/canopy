"""The decision queue — the architect's (and engineer's) morning surface.

Aggregates ADRs that need attention across one project or the whole org: proposals
awaiting triage, decisions stuck in discussion, and deferred decisions coming due.
"""

from datetime import UTC, datetime

from fastapi import APIRouter
from sqlmodel import col, select

from app.api.deps import CurrentUser, SessionDep
from app.models.architecture import ArchitectureDecision
from app.models.project import Project
from app.schemas.entities import DecisionQueueItem, DecisionQueueResponse
from app.services.decisions import DecisionQueueInput, build_decision_queue

router = APIRouter()


@router.get("/queue", response_model=DecisionQueueResponse)
async def decision_queue(
    session: SessionDep, _: CurrentUser, project_id: int | None = None
) -> DecisionQueueResponse:
    stmt = select(ArchitectureDecision)
    if project_id is not None:
        stmt = stmt.where(ArchitectureDecision.project_id == project_id)
    adrs = list((await session.execute(stmt)).scalars().all())

    project_ids = {a.project_id for a in adrs}
    sla_by_project: dict[int, int] = {}
    if project_ids:
        rows = (
            await session.execute(
                select(Project).where(col(Project.id).in_(project_ids))
            )
        ).scalars().all()
        sla_by_project = {p.id: p.decision_sla_hours for p in rows if p.id is not None}

    inputs = [
        DecisionQueueInput(
            id=a.id,
            project_id=a.project_id,
            number=a.number,
            title=a.title,
            status=a.status,
            created_at=a.created_at,
            decide_by=a.decide_by,
            sla_hours=sla_by_project.get(a.project_id, 72),
        )
        for a in adrs
        if a.id is not None
    ]
    queue = build_decision_queue(inputs, datetime.now(UTC))
    return DecisionQueueResponse(
        items=[
            DecisionQueueItem(
                id=q.id,
                project_id=q.project_id,
                number=q.number,
                title=q.title,
                status=q.status,
                bucket=q.bucket,
                reason=q.reason,
                overdue=q.overdue,
                decide_by=q.decide_by,
                age_hours=round(q.age_hours, 1),
            )
            for q in queue
        ]
    )
