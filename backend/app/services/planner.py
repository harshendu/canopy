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


def _project_start(project: Project, tasks: list[Task]) -> date:
    if project.start_date:
        return project.start_date
    starts = [t.start for t in tasks if t.start]
    return min(starts) if starts else date.today()


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
    # Roll up summary tasks from their direct children.
    children: dict[int, list[Task]] = {}
    for t in tasks:
        if t.parent_id:
            children.setdefault(t.parent_id, []).append(t)
    for t in tasks:
        if t.type == TaskType.summary and t.id in children:
            child_starts = [c.start for c in children[t.id] if c.start]
            child_ends = [c.end for c in children[t.id] if c.end]
            t.start = min(child_starts) if child_starts else None
            t.end = max(child_ends) if child_ends else None
            if t.start and t.end:
                t.duration = (t.end - t.start).days


async def reschedule_project(
    session: AsyncSession,
    project_id: int,
    *,
    persist: bool = True,
    duration_overrides: dict[int, int] | None = None,
) -> PlanOutcome | None:
    """Recompute the schedule. None if the project is missing; raises CycleError on a cycle."""
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

    sched_tasks: list[SchedTask] = []
    for t in tasks:
        if t.id is None:
            continue
        duration = overrides.get(t.id, 0 if t.type == TaskType.milestone else max(t.duration, 0))
        sched_tasks.append(
            SchedTask(
                id=t.id,
                duration=duration,
                is_summary=t.type == TaskType.summary,
                pinned_start_offset=(
                    working_days_between(start_ref, t.start, calendar) if t.start else None
                ),
            )
        )
    sched_deps = [SchedDep(d.predecessor_id, d.successor_id, d.type.value, d.lag) for d in deps]

    results = compute_cpm(sched_tasks, sched_deps)
    assign_dates(sched_tasks, results, start_ref, calendar)

    by_id = {t.id: t for t in tasks}
    project_end: date | None = None
    violations: list[int] = []
    for tid, res in results.items():
        if res.end and (project_end is None or res.end > project_end):
            project_end = res.end
        task = by_id.get(tid)
        if task and task.deadline and res.end and res.end > task.deadline:
            violations.append(tid)

    if persist:
        _persist(tasks, results)
        await session.commit()

    return PlanOutcome(
        scheduled_tasks=len(results),
        critical_path=critical_path(results),
        project_end=project_end,
        deadline_violations=violations,
    )
