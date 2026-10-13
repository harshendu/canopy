"""Scenario engine: materialise a scenario's snapshot and run the existing pure analysis
services over it to produce every view. No analysis logic lives here — it only adapts
scenario rows into the dataclasses the pure services already consume, so the scenario views
return the *same* response schemas as the live endpoints (the frontend reuses its components).

Per-project schedules pin each cloned task at its live start (so an unedited scenario
reproduces the live plan); added tasks float from the project start. Board/burndown/forecast
read history from the live task for cloned rows — added tasks have no history (they count as
remaining / not-done), which is honest: a what-if cannot fabricate throughput.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Protocol, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.models.base import TaskType
from app.models.project import Dependency, Holiday, Milestone, Project, Task, TaskStatusHistory
from app.models.scenario import (
    Scenario,
    ScenarioAllocation,
    ScenarioAvailability,
    ScenarioDependency,
    ScenarioMilestone,
    ScenarioProject,
    ScenarioTask,
)
from app.models.team import Allocation, Engineer, EngineerAvailability
from app.schemas.entities import (
    AlertRead,
    AlertsResponse,
    BoardLaneRead,
    BoardResponse,
    BoardTaskRead,
    BurndownPoint,
    BurndownResponse,
    CapacityResponse,
    CapacityRow,
    CriticalPathHandoff,
    CriticalPathNode,
    ForecastResponse,
    GanttLink,
    GanttResponse,
    GanttTask,
    InitiativeCriticalPath,
)
from app.services.alerts import (
    AlertMilestone,
    AlertTask,
    OverAllocation,
    compute_alerts,
)
from app.services.burndown import compute_burndown, done_dates_per_task, is_done_status
from app.services.capacity import (
    AllocationSpan,
    AvailabilitySpan,
    mondays,
    over_allocated_weeks,
    weekly_availability,
    weekly_capacity,
)
from app.services.cross_project import CPDep, CPTask, cross_project_critical_path
from app.services.flow import BoardTaskInput, build_board
from app.services.forecast import monte_carlo_forecast, weekly_throughput
from app.services.planner import SchedInput, compute_schedule, effective_duration
from app.services.scheduling import SchedDep, SchedResult, WorkingCalendar


class _HasRemoved(Protocol):
    removed: bool


_R = TypeVar("_R", bound=_HasRemoved)


def _active(rows: Sequence[_R]) -> list[_R]:
    return [r for r in rows if not r.removed]


@dataclass
class MaterializedScenario:
    scenario: Scenario
    project_keys: dict[int, str]
    live_projects: dict[int, Project]
    project_knobs: dict[int, ScenarioProject]
    holidays_by_project: dict[int, list[date]]
    tasks: list[ScenarioTask]  # non-removed
    deps: list[ScenarioDependency]  # non-removed
    milestones: list[ScenarioMilestone]  # non-removed
    allocations: list[ScenarioAllocation]  # non-removed
    availability: list[ScenarioAvailability]  # non-removed
    live_tasks: dict[int, Task]  # by live task id
    live_history: dict[int, list[TaskStatusHistory]] = field(default_factory=dict)
    engineer_names: dict[int, str] = field(default_factory=dict)


async def snapshot_live_into_scenario(session: AsyncSession, scenario: Scenario) -> None:
    """Clone the initiative's live planning rows into the scenario tables.

    Every cloned row keeps a `live_*_id` so apply can map back to update/delete; rows added in
    the scenario have none. Shared by the create-scenario endpoint and the demo seed loader.
    """
    assert scenario.id is not None
    sid = scenario.id
    live_projects = list(
        (
            await session.execute(
                select(Project).where(Project.initiative_id == scenario.initiative_id)
            )
        ).scalars().all()
    )
    project_ids = {p.id for p in live_projects if p.id is not None}
    for p in live_projects:
        if p.id is None:
            continue
        session.add(
            ScenarioProject(
                scenario_id=sid,
                project_id=p.id,
                start_date=p.start_date,
                target_date=p.target_date,
                skip_weekends=p.skip_weekends,
            )
        )

    live_tasks = (
        list(
            (
                await session.execute(select(Task).where(col(Task.project_id).in_(project_ids)))
            ).scalars().all()
        )
        if project_ids
        else []
    )
    task_rows: dict[int, ScenarioTask] = {}
    for lt in live_tasks:
        if lt.id is None:
            continue
        st = ScenarioTask(
            scenario_id=sid,
            project_id=lt.project_id,
            live_task_id=lt.id,
            name=lt.name,
            description=lt.description,
            type=lt.type,
            duration=lt.duration,
            deadline=lt.deadline,
            percent_complete=lt.percent_complete,
            assignee_engineer_id=lt.assignee_engineer_id,
        )
        session.add(st)
        task_rows[lt.id] = st
    await session.flush()  # assign scenario task ids
    live_to_sid = {lid: st.id for lid, st in task_rows.items() if st.id is not None}
    for lt in live_tasks:
        if lt.id is not None and lt.parent_id is not None and lt.parent_id in live_to_sid:
            task_rows[lt.id].parent_id = live_to_sid[lt.parent_id]

    live_task_ids = set(live_to_sid)
    for d in (await session.execute(select(Dependency))).scalars().all():
        if d.predecessor_id in live_task_ids and d.successor_id in live_task_ids:
            session.add(
                ScenarioDependency(
                    scenario_id=sid,
                    predecessor_id=live_to_sid[d.predecessor_id],
                    successor_id=live_to_sid[d.successor_id],
                    type=d.type,
                    lag=d.lag,
                    live_dep_id=d.id,
                )
            )

    if project_ids:
        ml_rows = await session.execute(
            select(Milestone).where(col(Milestone.project_id).in_(project_ids))
        )
        for ml in ml_rows.scalars().all():
            session.add(
                ScenarioMilestone(
                    scenario_id=sid,
                    project_id=ml.project_id,
                    live_milestone_id=ml.id,
                    name=ml.name,
                    description=ml.description,
                    target_date=ml.target_date,
                    status=ml.status,
                )
            )
        alloc_rows = await session.execute(
            select(Allocation).where(col(Allocation.project_id).in_(project_ids))
        )
        for a in alloc_rows.scalars().all():
            session.add(
                ScenarioAllocation(
                    scenario_id=sid,
                    live_allocation_id=a.id,
                    engineer_id=a.engineer_id,
                    project_id=a.project_id,
                    task_id=live_to_sid.get(a.task_id) if a.task_id is not None else None,
                    percent_allocation=a.percent_allocation,
                    capacity_hours_per_week=a.capacity_hours_per_week,
                    start_date=a.start_date,
                    end_date=a.end_date,
                )
            )

    for av in (await session.execute(select(EngineerAvailability))).scalars().all():
        session.add(
            ScenarioAvailability(
                scenario_id=sid,
                live_availability_id=av.id,
                engineer_id=av.engineer_id,
                start_date=av.start_date,
                end_date=av.end_date,
                capacity_factor=av.capacity_factor,
                note=av.note,
            )
        )
    await session.flush()


async def materialize(session: AsyncSession, scenario_id: int) -> MaterializedScenario | None:
    scenario = await session.get(Scenario, scenario_id)
    if scenario is None:
        return None
    live_projects = {
        p.id: p
        for p in (
            await session.execute(
                select(Project).where(Project.initiative_id == scenario.initiative_id)
            )
        ).scalars().all()
        if p.id is not None
    }
    project_ids = set(live_projects)
    project_keys = {pid: p.key for pid, p in live_projects.items()}

    holidays_by_project: dict[int, list[date]] = {}
    if project_ids:
        for h in (
            await session.execute(select(Holiday).where(col(Holiday.project_id).in_(project_ids)))
        ).scalars().all():
            holidays_by_project.setdefault(h.project_id, []).append(h.day)

    knobs = {
        sp.project_id: sp
        for sp in (
            await session.execute(
                select(ScenarioProject).where(ScenarioProject.scenario_id == scenario_id)
            )
        ).scalars().all()
    }
    tasks = _active(
        list(
            (
                await session.execute(
                    select(ScenarioTask).where(ScenarioTask.scenario_id == scenario_id)
                )
            ).scalars().all()
        )
    )
    deps = _active(
        list(
            (
                await session.execute(
                    select(ScenarioDependency).where(
                        ScenarioDependency.scenario_id == scenario_id
                    )
                )
            ).scalars().all()
        )
    )
    milestones = _active(
        list(
            (
                await session.execute(
                    select(ScenarioMilestone).where(
                        ScenarioMilestone.scenario_id == scenario_id
                    )
                )
            ).scalars().all()
        )
    )
    allocations = _active(
        list(
            (
                await session.execute(
                    select(ScenarioAllocation).where(
                        ScenarioAllocation.scenario_id == scenario_id
                    )
                )
            ).scalars().all()
        )
    )
    availability = _active(
        list(
            (
                await session.execute(
                    select(ScenarioAvailability).where(
                        ScenarioAvailability.scenario_id == scenario_id
                    )
                )
            ).scalars().all()
        )
    )

    live_tasks = {
        t.id: t
        for t in (
            (
                await session.execute(select(Task).where(col(Task.project_id).in_(project_ids)))
            ).scalars().all()
            if project_ids
            else []
        )
        if t.id is not None
    }
    live_history: dict[int, list[TaskStatusHistory]] = {}
    if live_tasks:
        for hist in (
            await session.execute(
                select(TaskStatusHistory).where(
                    col(TaskStatusHistory.task_id).in_(set(live_tasks))
                )
            )
        ).scalars().all():
            live_history.setdefault(hist.task_id, []).append(hist)

    engineer_names = {
        e.id: e.name
        for e in (await session.execute(select(Engineer))).scalars().all()
        if e.id is not None
    }

    return MaterializedScenario(
        scenario=scenario,
        project_keys=project_keys,
        live_projects=live_projects,
        project_knobs=knobs,
        holidays_by_project=holidays_by_project,
        tasks=tasks,
        deps=deps,
        milestones=milestones,
        allocations=allocations,
        availability=availability,
        live_tasks=live_tasks,
        live_history=live_history,
        engineer_names=engineer_names,
    )


def _calendar(m: MaterializedScenario, project_id: int) -> WorkingCalendar:
    knob = m.project_knobs.get(project_id)
    live = m.live_projects.get(project_id)
    skip = knob.skip_weekends if knob is not None else (live.skip_weekends if live else False)
    return WorkingCalendar(
        weekend=frozenset({5, 6}) if skip else frozenset(),
        holidays=frozenset(m.holidays_by_project.get(project_id, [])),
    )


def _pinned_start(m: MaterializedScenario, t: ScenarioTask) -> date | None:
    """A cloned task pins at its live start (so an unedited scenario reproduces live);
    a task added in the scenario floats from the project start."""
    if t.live_task_id is not None:
        live = m.live_tasks.get(t.live_task_id)
        if live is not None:
            return live.start
    return None


def _project_start(m: MaterializedScenario, project_id: int, pins: list[date]) -> date:
    knob = m.project_knobs.get(project_id)
    if knob is not None and knob.start_date is not None:
        return knob.start_date
    live = m.live_projects.get(project_id)
    if live is not None and live.start_date is not None:
        return live.start_date
    return min(pins) if pins else date.today()


def _schedule_project(
    m: MaterializedScenario, project_id: int
) -> tuple[list[ScenarioTask], dict[int, SchedResult]]:
    """Run CPM over one project's scenario tasks. Returns (tasks, results-by-task-id)."""
    tasks = [t for t in m.tasks if t.project_id == project_id and t.id is not None]
    ids = {t.id for t in tasks}
    deps = [
        SchedDep(d.predecessor_id, d.successor_id, d.type.value, d.lag)
        for d in m.deps
        if d.predecessor_id in ids and d.successor_id in ids
    ]
    pins = [p for p in (_pinned_start(m, t) for t in tasks) if p is not None]
    start_ref = _project_start(m, project_id, pins)
    inputs = [
        SchedInput(
            task_id=t.id,  # type: ignore[arg-type]
            duration=effective_duration(t.type, t.duration),
            type=t.type,
            parent_id=t.parent_id,
            pinned_start=_pinned_start(m, t),
            deadline=t.deadline,
        )
        for t in tasks
    ]
    calendar = _calendar(m, project_id)
    results = compute_schedule(inputs, deps, project_start=start_ref, calendar=calendar)
    return tasks, results


def scenario_gantt(m: MaterializedScenario, project_id: int) -> GanttResponse:
    tasks, results = _schedule_project(m, project_id)
    ids = {t.id for t in tasks}
    gantt_tasks = [
        GanttTask(
            id=t.id,
            text=t.name,
            start_date=results[t.id].start if t.id in results else None,
            end_date=results[t.id].end if t.id in results else None,
            baseline_start=None,
            baseline_end=None,
            deadline=t.deadline,
            duration=t.duration,
            progress=round(t.percent_complete / 100.0, 4),
            parent=t.parent_id or 0,
            type=t.type,
            is_critical=results[t.id].is_critical if t.id in results else False,
            total_float=results[t.id].total_float if t.id in results else 0,
        )
        for t in tasks
    ]
    links = [
        GanttLink(
            id=d.id,
            source=d.predecessor_id,
            target=d.successor_id,
            type=d.type,
            lag=d.lag,
        )
        for d in m.deps
        if d.id is not None and d.predecessor_id in ids and d.successor_id in ids
    ]
    return GanttResponse(project_id=project_id, tasks=gantt_tasks, links=links)


def scenario_critical_path(m: MaterializedScenario) -> InitiativeCriticalPath:
    names = {t.id: t.name for t in m.tasks if t.id is not None}
    ids = set(names)
    cp = cross_project_critical_path(
        [
            CPTask(
                id=t.id,
                project_id=t.project_id,
                duration=effective_duration(t.type, t.duration),
                is_summary=t.type == TaskType.summary,
            )
            for t in m.tasks
            if t.id is not None
        ],
        [
            CPDep(d.predecessor_id, d.successor_id, d.type.value, d.lag)
            for d in m.deps
            if d.predecessor_id in ids and d.successor_id in ids
        ],
    )
    return InitiativeCriticalPath(
        initiative_id=m.scenario.initiative_id,
        total_working_days=cp.total_working_days,
        spans_projects=cp.spans_projects,
        tasks=[
            CriticalPathNode(
                task_id=n.task_id,
                name=names.get(n.task_id, f"#{n.task_id}"),
                project_id=n.project_id,
                project_key=m.project_keys.get(n.project_id, f"#{n.project_id}"),
                es=n.es,
                ef=n.ef,
                duration=n.duration,
            )
            for n in cp.nodes
        ],
        handoffs=[
            CriticalPathHandoff(
                predecessor_id=h.predecessor_id,
                successor_id=h.successor_id,
                from_project_key=m.project_keys.get(h.from_project_id, f"#{h.from_project_id}"),
                to_project_key=m.project_keys.get(h.to_project_id, f"#{h.to_project_id}"),
            )
            for h in cp.handoffs
        ],
    )


def _capacity_window(m: MaterializedScenario) -> tuple[date, date]:
    starts = [a.start_date for a in m.allocations if a.start_date]
    ends = [a.end_date for a in m.allocations if a.end_date]
    start = min(starts) if starts else date.today()
    end = max(ends) if ends else start + timedelta(weeks=8)
    return start, (end if end >= start else start)


def scenario_capacity(m: MaterializedScenario, project_id: int | None = None) -> CapacityResponse:
    allocs = [a for a in m.allocations if project_id is None or a.project_id == project_id]
    window_start, window_end = _capacity_window(m)
    grid = weekly_capacity(
        [AllocationSpan(a.engineer_id, a.percent_allocation, a.start_date, a.end_date)
         for a in allocs],
        window_start,
        window_end,
    )
    avail_grid = weekly_availability(
        [AvailabilitySpan(a.engineer_id, a.capacity_factor, a.start_date, a.end_date)
         for a in m.availability],
        window_start,
        window_end,
    )
    weeks = [w.isoformat() for w in mondays(window_start, window_end)]
    projects_by_engineer: dict[int, set[str]] = {}
    for a in allocs:
        if a.project_id is not None and a.project_id in m.project_keys:
            projects_by_engineer.setdefault(a.engineer_id, set()).add(m.project_keys[a.project_id])
    rows = [
        CapacityRow(
            engineer_id=eng_id,
            engineer_name=m.engineer_names.get(eng_id, f"#{eng_id}"),
            cells={week.isoformat(): pct for week, pct in by_week.items()},
            projects=sorted(projects_by_engineer.get(eng_id, set())),
            availability={
                week.isoformat(): factor for week, factor in avail_grid.get(eng_id, {}).items()
            },
        )
        for eng_id, by_week in sorted(grid.items())
    ]
    return CapacityResponse(project_id=project_id, weeks=weeks, rows=rows)


def scenario_alerts(m: MaterializedScenario, project_id: int) -> AlertsResponse:
    tasks, results = _schedule_project(m, project_id)
    alert_tasks = [
        AlertTask(
            id=t.id,  # type: ignore[arg-type]
            name=t.name,
            is_summary=t.type == TaskType.summary,
            end=results[t.id].end if t.id in results else None,
            deadline=t.deadline,
        )
        for t in tasks
    ]
    alert_milestones = [
        AlertMilestone(m_.id, m_.name, m_.target_date, m_.status)
        for m_ in m.milestones
        if m_.project_id == project_id and m_.id is not None
    ]
    window_start, window_end = _capacity_window(m)
    over = [
        OverAllocation(
            m.engineer_names.get(o.engineer_id, f"#{o.engineer_id}"), o.week.isoformat(), o.percent
        )
        for o in over_allocated_weeks(
            [
                AllocationSpan(a.engineer_id, a.percent_allocation, a.start_date, a.end_date)
                for a in m.allocations
                if a.project_id == project_id
            ],
            [
                AvailabilitySpan(a.engineer_id, a.capacity_factor, a.start_date, a.end_date)
                for a in m.availability
            ],
            window_start,
            window_end,
        )
    ]
    alerts = compute_alerts(date.today(), alert_tasks, alert_milestones, over, blockers=[])
    return AlertsResponse(
        project_id=project_id,
        alerts=[
            AlertRead(
                kind=a.kind,
                severity=a.severity,
                message=a.message,
                entity_type=a.entity_type,
                entity_id=a.entity_id,
            )
            for a in alerts
        ],
    )


def _done_dates(m: MaterializedScenario, tasks: list[ScenarioTask]) -> list[date]:
    """One completion date per cloned task (last done transition) from its live history — a
    reopened-then-redone task counts once, not once per transition (added tasks have none)."""
    rows = [
        (t.live_task_id, h.to_status, h.changed_at.date())
        for t in tasks
        if t.live_task_id is not None
        for h in m.live_history.get(t.live_task_id, [])
    ]
    return done_dates_per_task(rows)


def scenario_burndown(m: MaterializedScenario, project_id: int) -> BurndownResponse:
    leaves = [
        t for t in m.tasks if t.project_id == project_id and t.type != TaskType.summary
    ]
    done_dates = _done_dates(m, leaves)
    knob = m.project_knobs.get(project_id)
    live = m.live_projects.get(project_id)
    _, results = _schedule_project(m, project_id)
    ends = [r.end for r in results.values() if r.end]
    window_start = (
        (knob.start_date if knob else None)
        or (live.start_date if live else None)
        or (done_dates[0] if done_dates else date.today())
    )
    window_end = (
        (knob.target_date if knob else None)
        or (live.target_date if live else None)
        or (max(ends) if ends else window_start)
    )
    if window_end < window_start:
        window_end = window_start
    points = [
        BurndownPoint(week=p.week, total=p.total, completed=p.completed, remaining=p.remaining)
        for p in compute_burndown(len(leaves), done_dates, mondays(window_start, window_end))
    ]
    return BurndownResponse(project_id=project_id, points=points)


def scenario_forecast(m: MaterializedScenario, project_id: int | None = None) -> ForecastResponse:
    leaves = [
        t
        for t in m.tasks
        if (project_id is None or t.project_id == project_id) and t.type != TaskType.summary
    ]
    remaining = sum(1 for t in leaves if t.percent_complete < 100)
    done_dates = _done_dates(m, leaves)
    today = date.today()
    result = monte_carlo_forecast(remaining, weekly_throughput(done_dates, today), today)
    return ForecastResponse(
        scope="initiative" if project_id is None else "project",
        id=project_id if project_id is not None else m.scenario.initiative_id,
        sufficient=result.sufficient,
        reason=result.reason,
        remaining_items=result.remaining_items,
        history_weeks=result.history_weeks,
        trials=result.trials,
        p50_weeks=result.p50_weeks,
        p85_weeks=result.p85_weeks,
        p50_date=result.p50_date,
        p85_date=result.p85_date,
    )


def scenario_board(m: MaterializedScenario, project_id: int) -> BoardResponse:
    leaves = [
        t
        for t in m.tasks
        if t.project_id == project_id and t.type != TaskType.summary and t.id is not None
    ]
    today = date.today()
    inputs: list[BoardTaskInput] = []
    for t in leaves:
        assert t.id is not None
        live = m.live_tasks.get(t.live_task_id) if t.live_task_id is not None else None
        status = live.status if live is not None else None
        rows = m.live_history.get(t.live_task_id, []) if t.live_task_id is not None else []
        created = live.created_at.date() if live is not None else today
        entered = max((h.changed_at.date() for h in rows if h.to_status == status), default=created)
        done_dates = [h.changed_at.date() for h in rows if is_done_status(h.to_status)]
        cycle_days = max(0, (max(done_dates) - created).days) if done_dates else None
        inputs.append(
            BoardTaskInput(
                id=t.id,
                name=t.name,
                status=status,
                assignee_engineer_id=t.assignee_engineer_id,
                is_done=is_done_status(status),
                age_days=max(0, (today - entered).days),
                cycle_days=cycle_days,
            )
        )
    board = build_board(inputs)
    return BoardResponse(
        project_id=project_id,
        cycle_time_p85_days=board.cycle_time_p85_days,
        aging_count=board.aging_count,
        lanes=[
            BoardLaneRead(
                status=lane.status,
                is_done=lane.is_done,
                wip=lane.wip,
                tasks=[
                    BoardTaskRead(
                        id=bt.id,
                        name=bt.name,
                        status=bt.status,
                        assignee_engineer_id=bt.assignee_engineer_id,
                        is_done=bt.is_done,
                        age_days=bt.age_days,
                        aging=bt.aging,
                    )
                    for bt in lane.tasks
                ],
            )
            for lane in board.lanes
        ],
    )
