"""Critical Path Method (CPM) scheduler.

Pure, dependency-injected logic so it can be unit-tested without a database.
The CPM passes work in integer working-day offsets; a WorkingCalendar maps those
offsets to calendar dates, skipping weekends/holidays. The default calendar treats
every day as a working day (preserving plain-calendar behavior). Supports FS/SS/FF/SF
dependency types with lag, computes early/late start/finish, total float, and
flags the critical path (float <= 0).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import networkx as nx


@dataclass(frozen=True)
class WorkingCalendar:
    """Defines which days count as working days. Empty sets => every day works."""

    weekend: frozenset[int] = frozenset()  # weekday ints, Mon=0 … Sun=6 (e.g. {5, 6})
    holidays: frozenset[date] = frozenset()

    @property
    def trivial(self) -> bool:
        return not self.weekend and not self.holidays

    def is_working(self, day: date) -> bool:
        return day.weekday() not in self.weekend and day not in self.holidays


def add_working_days(start: date, n: int, calendar: WorkingCalendar | None = None) -> date:
    """The date `n` working days from `start` (n may be negative). Offset 0 == start."""
    cal = calendar or WorkingCalendar()
    if cal.trivial or n == 0:
        return start + timedelta(days=n)
    step = 1 if n > 0 else -1
    remaining = abs(n)
    day = start
    while remaining > 0:
        day += timedelta(days=step)
        if cal.is_working(day):
            remaining -= 1
    return day


def working_days_between(start: date, end: date, calendar: WorkingCalendar | None = None) -> int:
    """Count of working days from `start` to `end` (signed). Inverse of add_working_days."""
    cal = calendar or WorkingCalendar()
    if cal.trivial:
        return (end - start).days
    if end == start:
        return 0
    step = 1 if end > start else -1
    count = 0
    day = start
    while day != end:
        day += timedelta(days=step)
        if cal.is_working(day):
            count += step
    return count


@dataclass
class SchedTask:
    id: int
    duration: int = 1
    is_summary: bool = False
    pinned_start_offset: int | None = None  # "start no earlier than" constraint


@dataclass
class SchedDep:
    predecessor_id: int
    successor_id: int
    type: str = "FS"
    lag: int = 0


@dataclass
class SchedResult:
    es: int = 0
    ef: int = 0
    ls: int = 0
    lf: int = 0
    total_float: int = 0
    is_critical: bool = False
    start: date | None = None
    end: date | None = None


class CycleError(ValueError):
    """Raised when the dependency graph contains a cycle (cannot be scheduled)."""


def _es_lower_bound(dep: SchedDep, pred: SchedResult, succ_duration: int) -> int:
    """Minimum early-start of the successor implied by one dependency edge."""
    if dep.type == "FS":
        return pred.ef + dep.lag
    if dep.type == "SS":
        return pred.es + dep.lag
    if dep.type == "FF":
        return pred.ef + dep.lag - succ_duration
    if dep.type == "SF":
        return pred.es + dep.lag - succ_duration
    return pred.ef + dep.lag


def _lf_upper_bound(dep: SchedDep, succ: SchedResult, pred_duration: int) -> int:
    """Maximum late-finish of the predecessor implied by one dependency edge."""
    if dep.type == "FS":
        return succ.ls - dep.lag
    if dep.type == "FF":
        return succ.lf - dep.lag
    if dep.type == "SS":
        return (succ.ls - dep.lag) + pred_duration
    if dep.type == "SF":
        return (succ.lf - dep.lag) + pred_duration
    return succ.ls - dep.lag


def compute_cpm(tasks: list[SchedTask], deps: list[SchedDep]) -> dict[int, SchedResult]:
    """Run the forward + backward CPM passes. Returns id -> SchedResult (day offsets)."""
    schedulable = {t.id: t for t in tasks if not t.is_summary}
    results: dict[int, SchedResult] = {tid: SchedResult() for tid in schedulable}

    graph = nx.DiGraph()
    graph.add_nodes_from(schedulable)
    edges_by_succ: dict[int, list[SchedDep]] = {tid: [] for tid in schedulable}
    edges_by_pred: dict[int, list[SchedDep]] = {tid: [] for tid in schedulable}
    for d in deps:
        if d.predecessor_id in schedulable and d.successor_id in schedulable:
            graph.add_edge(d.predecessor_id, d.successor_id)
            edges_by_succ[d.successor_id].append(d)
            edges_by_pred[d.predecessor_id].append(d)

    if not nx.is_directed_acyclic_graph(graph):
        raise CycleError("Dependency graph contains a cycle")

    order = list(nx.topological_sort(graph))

    # Forward pass: earliest start / finish.
    for tid in order:
        task = schedulable[tid]
        es = task.pinned_start_offset or 0
        for dep in edges_by_succ[tid]:
            es = max(es, _es_lower_bound(dep, results[dep.predecessor_id], task.duration))
        es = max(es, 0)
        results[tid].es = es
        results[tid].ef = es + task.duration

    project_finish = max((r.ef for r in results.values()), default=0)

    # Backward pass: latest start / finish.
    for tid in reversed(order):
        task = schedulable[tid]
        succ_edges = edges_by_pred[tid]
        if not succ_edges:
            lf = project_finish
        else:
            lf = min(
                _lf_upper_bound(dep, results[dep.successor_id], task.duration)
                for dep in succ_edges
            )
        results[tid].lf = lf
        results[tid].ls = lf - task.duration
        results[tid].total_float = results[tid].ls - results[tid].es
        results[tid].is_critical = results[tid].total_float <= 0

    return results


def assign_dates(
    tasks: list[SchedTask],
    results: dict[int, SchedResult],
    project_start: date,
    calendar: WorkingCalendar | None = None,
) -> None:
    """Populate start/end dates on each SchedResult, mapping offsets through the calendar."""
    cal = calendar or WorkingCalendar()
    durations = {t.id: t.duration for t in tasks}
    for tid, res in results.items():
        res.start = add_working_days(project_start, res.es, cal)
        res.end = add_working_days(project_start, res.es + durations.get(tid, 0), cal)


def critical_path(results: dict[int, SchedResult]) -> list[int]:
    return [tid for tid, r in results.items() if r.is_critical]
