"""Cross-project critical path for an initiative (pure, unit-testable).

Per-project scheduling stays project-local; this layer answers the initiative question:
across the sub-projects, which chain of dependent work is the longest, and which
dependency edges are the *cross-project hand-offs* on it? The hand-offs between teams are
where initiatives actually slip, so we surface them explicitly.

It reuses the same `compute_cpm` pass as per-project scheduling, run over the *union* of the
initiative's tasks + dependencies, working in dependency-driven working-day offsets (no
calendar mapping — a structural critical path, independent of each project's calendar)."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.scheduling import SchedDep, SchedTask, compute_cpm


@dataclass
class CPTask:
    id: int
    project_id: int
    duration: int = 1
    is_summary: bool = False


@dataclass
class CPDep:
    predecessor_id: int
    successor_id: int
    type: str = "FS"
    lag: int = 0


@dataclass
class CPNode:
    task_id: int
    project_id: int
    es: int
    ef: int
    duration: int


@dataclass
class CPHandoff:
    predecessor_id: int
    successor_id: int
    from_project_id: int
    to_project_id: int


@dataclass
class CrossProjectCP:
    total_working_days: int
    nodes: list[CPNode] = field(default_factory=list)  # the critical chain, earliest-first
    handoffs: list[CPHandoff] = field(default_factory=list)  # cross-project critical edges

    @property
    def spans_projects(self) -> bool:
        return len({n.project_id for n in self.nodes}) > 1


def cross_project_critical_path(tasks: list[CPTask], deps: list[CPDep]) -> CrossProjectCP:
    """Critical path over the union graph. Raises CycleError on a cyclic dependency."""
    results = compute_cpm(
        [SchedTask(id=t.id, duration=t.duration, is_summary=t.is_summary) for t in tasks],
        [SchedDep(d.predecessor_id, d.successor_id, d.type, d.lag) for d in deps],
    )
    project_of = {t.id: t.project_id for t in tasks}
    critical = {tid for tid, r in results.items() if r.is_critical}
    nodes = [
        CPNode(
            task_id=tid,
            project_id=project_of[tid],
            es=results[tid].es,
            ef=results[tid].ef,
            duration=results[tid].ef - results[tid].es,
        )
        for tid in sorted(critical, key=lambda tid: (results[tid].es, results[tid].ef))
    ]
    handoffs = [
        CPHandoff(
            predecessor_id=d.predecessor_id,
            successor_id=d.successor_id,
            from_project_id=project_of[d.predecessor_id],
            to_project_id=project_of[d.successor_id],
        )
        for d in deps
        if d.predecessor_id in critical
        and d.successor_id in critical
        and project_of.get(d.predecessor_id) != project_of.get(d.successor_id)
    ]
    total = max((r.ef for r in results.values()), default=0)
    return CrossProjectCP(total_working_days=total, nodes=nodes, handoffs=handoffs)
