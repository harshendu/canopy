"""Project (re)scheduling: load graph, run CPM with the project's working calendar,
optionally apply duration overrides (what-if), optionally persist, and report
deadline violations. Shared by the replan endpoint and connector auto-replan.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.base import TaskType
from app.models.project import Dependency, Holiday, Project, Task
from app.services.scheduling import (
    SchedDep,
    SchedResult,
    SchedTask,
    WorkingCalendar,
    assign_dates,
    compute_cpm,
    critical_path,
    working_days_between,
)


@dataclass
class PlanOutcome:
    scheduled_tasks: int
    critical_path: list[int]
    project_end: date | None
    deadline_violations: list[int]


@dataclass
class SchedInput:
    """A task as the scheduler needs it, decoupled from the ORM so the pure pass can run over
    live `Task`s or scenario rows alike. `duration` is already the *effective* duration."""

    task_id: int
    duration: int
    type: TaskType
    parent_id: int | None = None
    pinned_start: date | None = None
    deadline: date | None = None


def effective_duration(task_type: TaskType, duration: int, override: int | None = None) -> int:
    """The duration the scheduler should use: an explicit override wins; milestones are
    zero-duration markers; everything else clamps to a non-negative day count."""
    if override is not None:
        return override
    return 0 if task_type == TaskType.milestone else max(duration, 0)


def compute_schedule(
    tasks: list[SchedInput],
    deps: list[SchedDep],
    *,
    project_start: date,
    calendar: WorkingCalendar,
) -> dict[int, SchedResult]:
    """The pure middle of (re)scheduling: build SchedTasks, run CPM, map offsets to dates.
    Shared by `reschedule_project` and the scenario engine. Raises CycleError on a cycle."""
    sched_tasks = [
        SchedTask(
            id=t.task_id,
            duration=t.duration,
            is_summary=t.type == TaskType.summary,
            pinned_start_offset=(
                working_days_between(project_start, t.pinned_start, calendar)
                if t.pinned_start
                else None
            ),
        )
        for t in tasks
    ]
    results = compute_cpm(sched_tasks, deps)
    assign_dates(sched_tasks, results, project_start, calendar)
    return results


def schedule_outcome(
    inputs: list[SchedInput], results: dict[int, SchedResult]
) -> tuple[date | None, list[int]]:
    """Derive (project_end, deadline_violations) from a computed schedule — pure."""
    deadlines = {i.task_id: i.deadline for i in inputs}
    project_end: date | None = None
    violations: list[int] = []
    for tid, res in results.items():
        if res.end and (project_end is None or res.end > project_end):
            project_end = res.end
        deadline = deadlines.get(tid)
        if deadline and res.end and res.end > deadline:
            violations.append(tid)
    return project_end, violations


def infer_project_start(start_date: date | None, task_starts: list[date]) -> date:
    """The schedule's day-zero: the project's own start date, else its earliest scheduled
    task, else today. Pure — shared with the proposal preview so a simulated plan anchors
    exactly where a real replan would."""
    if start_date:
        return start_date
    return min(task_starts) if task_starts else date.today()


def _project_start(project: Project, tasks: list[Task]) -> date:
    return infer_project_start(project.start_date, [t.start for t in tasks if t.start])


@dataclass
class RollupNode:
    """A WBS node as the summary roll-up needs it (decoupled from the ORM)."""

    id: int
    parent_id: int | None
    is_summary: bool
    start: date | None
    end: date | None


def rollup_summaries(nodes: list[RollupNode]) -> dict[int, tuple[date | None, date | None]]:
    """Span every summary (phase) over its direct children: earliest child start → latest
    child end. Pure. Works **bottom-up** so a nested phase is rolled up before its parent
    reads it — a single pass in arbitrary order would hand the parent last run's span.
    Returns `id -> (start, end)` for each summary that has children; a childless summary is
    left out (its dates are whatever the caller already holds)."""
    by_id = {n.id: n for n in nodes}
    children: dict[int, list[int]] = {}
    for n in nodes:
        if n.parent_id is not None and n.parent_id in by_id:
            children.setdefault(n.parent_id, []).append(n.id)

    def depth(node_id: int) -> int:
        seen: set[int] = set()
        level, cur = 0, by_id[node_id]
        while cur.parent_id is not None and cur.parent_id in by_id and cur.id not in seen:
            seen.add(cur.id)
            level += 1
            cur = by_id[cur.parent_id]
        return level

    spans: dict[int, tuple[date | None, date | None]] = {n.id: (n.start, n.end) for n in nodes}
    rolled: dict[int, tuple[date | None, date | None]] = {}
    summaries = [n for n in nodes if n.is_summary and n.id in children]
    for node in sorted(summaries, key=lambda n: depth(n.id), reverse=True):
        starts = [s for s in (spans[c][0] for c in children[node.id]) if s]
        ends = [e for e in (spans[c][1] for c in children[node.id]) if e]
        span = (min(starts) if starts else None, max(ends) if ends else None)
        spans[node.id] = span
        rolled[node.id] = span
    return rolled


async def _load(
    session: AsyncSession, project_id: int
) -> tuple[list[Task], list[Dependency], list[Holiday]]:
    tasks = list(
        (await session.execute(select(Task).where(Task.project_id == project_id))).scalars().all()
    )
    task_ids = {t.id for t in tasks}
    all_deps = (await session.execute(select(Dependency))).scalars().all()
    deps = [d for d in all_deps if d.predecessor_id in task_ids and d.successor_id in task_ids]
    holidays = list(
        (
            await session.execute(select(Holiday).where(Holiday.project_id == project_id))
        ).scalars().all()
    )
    return tasks, deps, holidays


def _persist(tasks: list[Task], results: dict[int, SchedResult]) -> None:
    by_id = {t.id: t for t in tasks}
    for tid, res in results.items():
        task = by_id[tid]
        task.start = res.start
        task.end = res.end
        task.is_critical = res.is_critical
        task.total_float = res.total_float
    # Roll up summary tasks from their children (bottom-up, so nested phases stay current).
    rolled = rollup_summaries(
        [
            RollupNode(
                id=t.id,
                parent_id=t.parent_id,
                is_summary=t.type == TaskType.summary,
                start=t.start,
                end=t.end,
            )
            for t in tasks
            if t.id is not None
        ]
    )
    for t in tasks:
        if t.id in rolled:
            t.start, t.end = rolled[t.id]
            if t.start and t.end:
                t.duration = (t.end - t.start).days


async def reschedule_project(
    session: AsyncSession,
    project_id: int,
    *,
    persist: bool = True,
    commit: bool = True,
    duration_overrides: dict[int, int] | None = None,
) -> PlanOutcome | None:
    """Recompute the schedule. None if the project is missing; raises CycleError on a cycle.

    `persist` mutates the loaded `Task` rows; `commit` flushes the transaction (set
    `commit=False` to fold the replan into a larger transaction, e.g. scenario apply)."""
    project = await session.get(Project, project_id)
    if project is None:
        return None
    tasks, deps, holidays = await _load(session, project_id)
    calendar = WorkingCalendar(
        weekend=frozenset({5, 6}) if project.skip_weekends else frozenset(),
        holidays=frozenset(h.day for h in holidays),
    )
    start_ref = _project_start(project, tasks)
    overrides = duration_overrides or {}

    inputs = [
        SchedInput(
            task_id=t.id,
            duration=effective_duration(t.type, t.duration, overrides.get(t.id)),
            type=t.type,
            parent_id=t.parent_id,
            # Pin only from an explicit user constraint, never the last run's computed start —
            # otherwise the schedule ratchets forward-only and what-if can't pull work earlier.
            pinned_start=t.constraint_start,
            deadline=t.deadline,
        )
        for t in tasks
        if t.id is not None
    ]
    sched_deps = [SchedDep(d.predecessor_id, d.successor_id, d.type.value, d.lag) for d in deps]

    results = compute_schedule(inputs, sched_deps, project_start=start_ref, calendar=calendar)
    project_end, violations = schedule_outcome(inputs, results)

    if persist:
        _persist(tasks, results)
        if commit:
            await session.commit()

    return PlanOutcome(
        scheduled_tasks=len(results),
        critical_path=critical_path(results),
        project_end=project_end,
        deadline_violations=violations,
    )
