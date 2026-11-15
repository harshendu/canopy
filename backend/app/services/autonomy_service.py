"""Graduated autonomy, database side (docs/AGENT_EXECUTION.md §21 Phase 4): load the evidence
the pure `autonomy.py` counts — the checkpoint gates, first reviews, rework and parking of a
project's agent-worked tasks — and find the column whose checkpoints it is about."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.models.base import ArtifactKind, GateKind, GateStatus, WorkEventKind, utcnow
from app.models.gate import Gate
from app.models.project import Project, Task
from app.models.work import TaskArtifact, WorkClaim, WorkEvent
from app.services import autonomy, policy_service, stage_policy
from app.services.work_service import keep_for_people_tags


def target_stage(pipeline: stage_policy.Pipeline) -> stage_policy.StageDef | None:
    """The column whose checkpoints graduated autonomy tunes: the implementer's, else the
    first agent column with a checkpoint."""
    with_checkpoints = [s for s in pipeline.stages if s.is_agent_stage and s.checkpoints]
    implementer = [s for s in with_checkpoints if s.worked_by == "implementer"]
    candidates = implementer or with_checkpoints
    return candidates[0] if candidates else None


async def load(
    session: AsyncSession, project: Project, weeks: int = 12, now: datetime | None = None
) -> tuple[stage_policy.StageDef | None, autonomy.AutonomyFacts]:
    assert project.id is not None
    now = now or utcnow()
    since = now - timedelta(weeks=weeks)
    pipeline = await policy_service.resolve_pipeline(session, project)
    stage = target_stage(pipeline)
    task_ids = sorted({
        int(t) for t in (await session.execute(
            select(WorkClaim.task_id).join(Task, col(Task.id) == col(WorkClaim.task_id)).where(
                Task.project_id == project.id, col(WorkClaim.claimed_at) >= since)
        )).scalars().all()
    })
    tasks = (await session.execute(
        select(Task).where(col(Task.id).in_(task_ids or [-1]))
    )).scalars().all()
    returned: dict[int, int] = {}
    for task_id in (await session.execute(
        select(WorkEvent.task_id).where(
            col(WorkEvent.task_id).in_(task_ids or [-1]),
            WorkEvent.kind == WorkEventKind.returned.value, col(WorkEvent.at) >= since)
    )).scalars().all():
        if task_id is not None:
            returned[task_id] = returned.get(task_id, 0) + 1
    gates = (await session.execute(
        select(Gate).where(
            Gate.project_id == project.id, col(Gate.created_at) >= since,
            col(Gate.kind).in_([GateKind.plan_approval.value, GateKind.handoff_approval.value]))
    )).scalars().all()
    parked = {
        g.task_id for g in (await session.execute(
            select(Gate).where(
                Gate.project_id == project.id, Gate.status == GateStatus.open.value,
                Gate.kind == GateKind.escalation.value, Gate.origin == "system")
        )).scalars().all()
    }
    reviews = (await session.execute(
        select(TaskArtifact).where(
            col(TaskArtifact.task_id).in_(task_ids or [-1]),
            TaskArtifact.kind == ArtifactKind.review.value,
            col(TaskArtifact.created_at) >= since)
    )).scalars().all()
    facts = autonomy.AutonomyFacts(
        tasks=[autonomy.TaskRow(t.id, list(t.tags or []), returned.get(t.id, 0), t.id in parked)
               for t in tasks if t.id is not None],
        gates=[autonomy.GateRow(g.task_id, g.kind, g.decision, g.created_at, g.decided_at)
               for g in gates],
        reviews=[autonomy.ReviewRow(r.task_id, r.verdict, r.created_at) for r in reviews],
        pre_approved={name: list(cp.pre_approved)
                      for name, cp in (stage.checkpoints.items() if stage else [])},
        checkpoints=tuple(stage.checkpoints) if stage is not None else (),
        keep_for_people=frozenset(keep_for_people_tags()),
    )
    return stage, facts
