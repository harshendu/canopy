"""The traceability ledger, database side: gather what the pure `traceability.py` judges for one
decision — the tasks that implement it or touch its components, their PRs and reviews, its
fitness functions and the open drift that concerns it."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.models.architecture import (
    ADRComponentLink,
    ADRFitnessFunction,
    ArchitectureComponent,
    ArchitectureDecision,
    DriftEvent,
    TaskComponentLink,
)
from app.models.base import ArtifactKind, TaskType
from app.models.integration import PullRequest
from app.models.project import Task
from app.models.work import TaskArtifact
from app.services import flow, traceability
from app.services.workflow import category_of_task


def _value(raw: Any) -> str:
    return str(raw.value if hasattr(raw, "value") else raw) if raw is not None else ""


def _mentions(checked: Any, adr: ArchitectureDecision) -> bool:
    """Does a review's `checked` list name this decision (by id or as ADR-0001)?"""
    label = f"adr-{adr.number:04d}"
    for item in checked if isinstance(checked, list) else []:
        text = str(item).strip().lower()
        if text in (str(adr.id), label) or text.startswith(label) or f"#{adr.id}" == text:
            return True
    return False


@dataclass
class ProjectContext:
    """What every decision of one project reads alike — loaded once for the whole ledger."""

    plan_components: dict[int, set[int]]  # task id -> components its plans resolved
    open_drift: list[DriftEvent]


async def project_context(session: AsyncSession, project_id: int) -> ProjectContext:
    plan_components: dict[int, set[int]] = {}
    for plan in (await session.execute(
        select(TaskArtifact).join(Task, col(Task.id) == col(TaskArtifact.task_id)).where(
            Task.project_id == project_id, TaskArtifact.kind == ArtifactKind.plan.value)
    )).scalars().all():
        resolved = {int(c) for c in (plan.data or {}).get("resolved_component_ids") or []}
        if resolved:
            plan_components.setdefault(plan.task_id, set()).update(resolved)
    open_drift = list((await session.execute(
        select(DriftEvent).where(DriftEvent.project_id == project_id,
                                 DriftEvent.status == "open")
    )).scalars().all())
    return ProjectContext(plan_components=plan_components, open_drift=open_drift)


async def decision_facts(
    session: AsyncSession, adr: ArchitectureDecision, ctx: ProjectContext | None = None
) -> traceability.DecisionFacts:
    assert adr.id is not None
    if ctx is None:
        ctx = await project_context(session, adr.project_id)
    comp_ids = sorted({
        int(c) for c in (await session.execute(
            select(ADRComponentLink.component_id).where(ADRComponentLink.adr_id == adr.id)
        )).scalars().all()
    })
    names = {c.id: c.name for c in (await session.execute(
        select(ArchitectureComponent).where(col(ArchitectureComponent.id).in_(comp_ids or [-1]))
    )).scalars().all()}
    implementing = {
        t.id: t for t in (await session.execute(
            select(Task).where(Task.implements_adr_id == adr.id)
        )).scalars().all() if t.id is not None
    }
    governed_ids = set((await session.execute(
        select(TaskComponentLink.task_id).where(
            col(TaskComponentLink.component_id).in_(comp_ids or [-1]))
    )).scalars().all())
    # Plans resolve the components their paths touch: work there is governed too.
    governed_ids |= {task_id for task_id, resolved in ctx.plan_components.items()
                     if resolved & set(comp_ids)}
    governed = {
        t.id: t for t in (await session.execute(
            select(Task).where(col(Task.id).in_(sorted(governed_ids) or [-1]))
        )).scalars().all() if t.id is not None and t.type != TaskType.summary
    }
    tasks = {**governed, **implementing}
    task_ids = sorted(tasks)
    prs = (await session.execute(
        select(PullRequest).where(col(PullRequest.task_id).in_(task_ids or [-1]))
    )).scalars().all()
    reviews = (await session.execute(
        select(TaskArtifact).where(col(TaskArtifact.task_id).in_(task_ids or [-1]),
                                   TaskArtifact.kind == ArtifactKind.review.value)
    )).scalars().all()
    open_drift = ctx.open_drift
    fitness = (await session.execute(
        select(ADRFitnessFunction).where(ADRFitnessFunction.adr_id == adr.id)
    )).scalars().all()
    broken = {e.rule_key for e in open_drift if e.kind == "fitness_violation"}
    comp_names = {c.id: c.name for c in (await session.execute(
        select(ArchitectureComponent).where(col(ArchitectureComponent.id).in_(
            [f.source_component_id for f in fitness] + [f.target_component_id for f in fitness]
            or [-1]))
    )).scalars().all()}
    drift = [
        traceability.DriftFact(e.id, e.kind, e.summary) for e in open_drift
        if e.id is not None and (
            (e.kind == "unimplemented_adr" and e.rule_key == f"adr_unimplemented:{adr.number}")
            or (e.kind not in ("fitness_violation", "unimplemented_adr")
                and set(e.affected_component_ids or []) & set(comp_ids))
        )
    ]
    return traceability.DecisionFacts(
        adr_id=adr.id, number=adr.number, title=adr.title, status=_value(adr.status),
        reversibility=_value(adr.reversibility) or None,
        components=[names[c] for c in comp_ids if c in names],
        tasks=[traceability.TaskFact(
            t.id, t.key, t.name, t.status, category_of_task(t) == flow.DONE,
            implements=t.id in implementing, governed=t.id in governed)
            for t in sorted(tasks.values(), key=lambda t: t.id or 0) if t.id is not None],
        prs=[traceability.PrFact(p.task_id, p.repo, p.number, p.url, p.state, bool(p.merged),
                                 p.checks_state, p.review_decision) for p in prs],
        reviews=[traceability.ReviewFact(r.task_id, r.id, r.verdict,
                                         _mentions((r.data or {}).get("checked"), adr))
                 for r in reviews if r.id is not None],
        fitness=[traceability.FitnessFact(
            f.id, f.kind, comp_names.get(f.source_component_id, "?"),
            comp_names.get(f.target_component_id, "?"), f.description,
            violated=f"fitness:{f.id}" in broken) for f in fitness if f.id is not None],
        drift=drift,
    )
