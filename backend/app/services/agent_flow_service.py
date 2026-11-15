"""Agent-flow metrics, database side: load the facts `agent_flow.compute` reads, for the projects
of a project, an initiative or a team (docs/AGENT_EXECUTION.md §19). Also the readiness facts the
agent-work alerts share (ready work and how long it has waited)."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, func, select

from app.models.base import AgentIntake, ArtifactKind, GateKind, GateStatus, WorkEventKind, utcnow
from app.models.gate import Gate
from app.models.project import Project, Task, TaskStatusHistory
from app.models.work import TaskArtifact, WorkClaim, WorkEvent
from app.services import agent_flow, flow, work_queue, work_service
from app.services.agent_flow import (
    AgentFlowFacts,
    ClaimRow,
    GateRow,
    ReadyRow,
    TaskRow,
    VerdictRow,
)


def _cost(usage: dict[str, object] | None) -> float | None:
    value = (usage or {}).get("cost_usd")
    return float(value) if isinstance(value, int | float) else None


async def scope_project_ids(session: AsyncSession, scope: str, scope_id: int) -> list[int]:
    if scope == "project":
        return [scope_id] if await session.get(Project, scope_id) is not None else []
    if scope == "initiative":
        rows = (await session.execute(
            select(Project.id).where(Project.initiative_id == scope_id)
        )).scalars().all()
        return [r for r in rows if r is not None]
    from app.services.org import team_project_ids

    return await team_project_ids(session, scope_id)


async def ready_work(
    session: AsyncSession, project_ids: list[int], now: datetime | None = None
) -> list[ReadyRow]:
    """Delegated tasks ready for some role right now (projects with intake on), with how long
    each has waited since anything last happened to it — a team's view, not one caller's."""
    now = now or utcnow()
    out: list[ReadyRow] = []
    neutral = work_queue.CallerFacts(may_plan=True, engineer_id=0)
    for project_id in project_ids:
        project = await session.get(Project, project_id)
        if project is None or project.agent_intake != AgentIntake.on.value:
            continue
        work = await work_service.load_project_work(session, project)
        if not work.tasks:
            continue
        task_ids = [t.id for t in work.tasks if t.id is not None]
        last_event: dict[int, datetime] = {
            int(task_id): at for task_id, at in (await session.execute(
                select(WorkEvent.task_id, func.max(WorkEvent.at))
                .where(col(WorkEvent.task_id).in_(task_ids)).group_by(col(WorkEvent.task_id))
            )).all() if task_id is not None
        }
        for task in work.tasks:
            assert task.id is not None
            for role in work.pipeline.roles():
                verdict = work_queue.readiness(
                    work.facts[task.id], work.pipeline, role, intake=project.agent_intake,
                    caller=neutral, now=now,
                )
                if verdict.ready:
                    since = last_event.get(task.id) or task.delegated_at or now
                    out.append(ReadyRow(task.id, role,
                                        max(0.0, (now - since).total_seconds() / 3600)))
    return out


async def load_facts(
    session: AsyncSession, project_ids: list[int], *, since: datetime, now: datetime
) -> AgentFlowFacts:
    if not project_ids:
        return AgentFlowFacts()
    task_ids = select(col(Task.id)).where(col(Task.project_id).in_(project_ids))
    claims = (await session.execute(
        select(WorkClaim).where(col(WorkClaim.task_id).in_(task_ids))
    )).scalars().all()
    claim_rows = [
        ClaimRow(c.task_id, c.role, c.outcome, c.claimed_at, c.finished_at, _cost(c.usage))
        for c in claims
    ]
    gates = (await session.execute(
        select(Gate).where(col(Gate.project_id).in_(project_ids))
    )).scalars().all()
    gate_rows = [
        GateRow(g.task_id, g.kind, g.origin, g.status, g.decision, g.created_at, g.decided_at,
                [str(r) for r in g.reasons or []], g.remind_at, g.escalate_at,
                g.escalation_level)
        for g in gates
    ]
    verdicts = (await session.execute(
        select(TaskArtifact).where(
            col(TaskArtifact.task_id).in_(task_ids),
            col(TaskArtifact.kind).in_([ArtifactKind.review.value,
                                         ArtifactKind.qa_report.value]),
            col(TaskArtifact.created_at) >= since,
        )
    )).scalars().all()
    verdict_rows = [VerdictRow(a.task_id, a.kind, a.verdict, a.created_at) for a in verdicts]
    worked = sorted({c.task_id for c in claims})
    returned: dict[int, int] = {
        int(task_id): int(count) for task_id, count in (await session.execute(
            select(WorkEvent.task_id, func.count())
            .where(col(WorkEvent.task_id).in_(worked or [-1]),
                   WorkEvent.kind == WorkEventKind.returned.value)
            .group_by(col(WorkEvent.task_id))
        )).all() if task_id is not None
    }
    done: dict[int, datetime] = {
        int(task_id): at for task_id, at in (await session.execute(
            select(TaskStatusHistory.task_id, func.max(TaskStatusHistory.changed_at))
            .where(col(TaskStatusHistory.task_id).in_(worked or [-1]),
                   TaskStatusHistory.to_category == flow.DONE,
                   col(TaskStatusHistory.changed_at) >= since)
            .group_by(col(TaskStatusHistory.task_id))
        )).all()
    }
    task_rows = [TaskRow(t, done.get(t), int(returned.get(t, 0))) for t in worked]
    held: dict[str, int] = {}
    parked = 0
    for g in gates:
        if g.status != GateStatus.open.value:
            continue
        if g.kind == GateKind.escalation.value and g.origin == "system":
            parked += 1
        else:
            held[g.kind] = held.get(g.kind, 0) + 1
    return AgentFlowFacts(
        claims=claim_rows, gates=gate_rows, verdicts=verdict_rows, tasks=task_rows,
        ready=await ready_work(session, project_ids, now), held=held, parked=parked,
    )


async def agent_flow_for(
    session: AsyncSession, scope: str, scope_id: int, weeks: int
) -> dict[str, object]:
    now = utcnow()
    since = now - timedelta(weeks=max(1, min(weeks, 52)))
    project_ids = await scope_project_ids(session, scope, scope_id)
    facts = await load_facts(session, project_ids, since=since, now=now)
    result = agent_flow.compute(facts, now=now, since=since)
    return {"scope": scope, "scope_id": scope_id, "weeks": weeks, "since": since,
            "projects": len(project_ids), **result}
