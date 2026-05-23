from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.api.deps import CurrentUser, PlannerWriter, SessionDep
from app.core.events import publish
from app.models.base import TaskType
from app.models.project import (
    Baseline,
    Dependency,
    Milestone,
    Project,
    Task,
    TaskStatusHistory,
)
from app.models.team import Allocation, Engineer
from app.schemas.entities import (
    AlertRead,
    AlertsResponse,
    BaselineRead,
    BaselineRequest,
    BurndownPoint,
    BurndownResponse,
    GanttLink,
    GanttResponse,
    GanttTask,
    ReplanResult,
    WhatIfRequest,
)
from app.services.alerts import (
    AlertMilestone,
    AlertTask,
    OverAllocation,
    compute_alerts,
)
from app.services.burndown import compute_burndown, is_done_status
from app.services.capacity import AllocationSpan, mondays, weekly_capacity
from app.services.planner import PlanOutcome, reschedule_project
from app.services.scheduling import CycleError

router = APIRouter()


async def _load_project_graph(
    session: AsyncSession, project_id: int
) -> tuple[list[Task], list[Dependency]]:
    tasks = list(
        (await session.execute(select(Task).where(Task.project_id == project_id)))
        .scalars()
        .all()
    )
    task_ids = {t.id for t in tasks}
    all_deps = (await session.execute(select(Dependency))).scalars().all()
    deps = [d for d in all_deps if d.predecessor_id in task_ids and d.successor_id in task_ids]
    return tasks, deps


def _to_result(project_id: int, outcome: PlanOutcome) -> ReplanResult:
    return ReplanResult(
        project_id=project_id,
        scheduled_tasks=outcome.scheduled_tasks,
        critical_path=outcome.critical_path,
        project_end=outcome.project_end,
        deadline_violations=outcome.deadline_violations,
    )


@router.get("/projects/{project_id}/gantt", response_model=GanttResponse)
async def get_gantt(session: SessionDep, _: CurrentUser, project_id: int) -> GanttResponse:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    tasks, deps = await _load_project_graph(session, project_id)
    gantt_tasks = [
        GanttTask(
            id=t.id,
            text=t.name,
            start_date=t.start,
            end_date=t.end,
            baseline_start=t.baseline_start,
            baseline_end=t.baseline_end,
            deadline=t.deadline,
            duration=t.duration,
            progress=round(t.percent_complete / 100.0, 4),
            parent=t.parent_id or 0,
            type=t.type,
            is_critical=t.is_critical,
            total_float=t.total_float,
        )
        for t in tasks
    ]
    links = [
        GanttLink(id=d.id, source=d.predecessor_id, target=d.successor_id, type=d.type, lag=d.lag)
        for d in deps
    ]
    return GanttResponse(project_id=project_id, tasks=gantt_tasks, links=links)


@router.post("/projects/{project_id}/replan", response_model=ReplanResult)
async def replan(session: SessionDep, _: PlannerWriter, project_id: int) -> ReplanResult:
    try:
        outcome = await reschedule_project(session, project_id, persist=True)
    except CycleError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if outcome is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    await publish({"type": "replan", "project_id": project_id})
    return _to_result(project_id, outcome)


@router.post("/projects/{project_id}/whatif", response_model=ReplanResult)
async def whatif(
    session: SessionDep, _: CurrentUser, project_id: int, payload: WhatIfRequest
) -> ReplanResult:
    """Project a schedule with hypothetical duration changes — computed, never persisted."""
    try:
        outcome = await reschedule_project(
            session, project_id, persist=False, duration_overrides=payload.duration_overrides
        )
    except CycleError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if outcome is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return _to_result(project_id, outcome)


@router.post(
    "/projects/{project_id}/baseline",
    response_model=BaselineRead,
    status_code=status.HTTP_201_CREATED,
)
async def set_baseline(
    session: SessionDep,
    _: PlannerWriter,
    project_id: int,
    payload: BaselineRequest | None = None,
) -> Baseline:
    """Snapshot current start/end into baseline_* for every task as the new plan-of-record.

    Re-baselining is a deliberate, reasoned act — pass a `note` explaining why the plan was
    reset. The event is logged (see `GET .../baselines`) so the schedule-variance reference
    carries its own history. ("Drift" is reserved for architecture drift, §N.)
    """
    tasks = list(
        (
            await session.execute(select(Task).where(Task.project_id == project_id))
        ).scalars().all()
    )
    ends = [t.end for t in tasks if t.end]
    count = 0
    for task in tasks:
        task.baseline_start = task.start
        task.baseline_end = task.end
        count += 1
    baseline = Baseline(
        project_id=project_id,
        note=payload.note if payload else None,
        task_count=count,
        project_end=max(ends) if ends else None,
    )
    session.add(baseline)
    await session.commit()
    await session.refresh(baseline)
    await publish({"type": "baseline", "project_id": project_id})
    return baseline


@router.get("/projects/{project_id}/baselines", response_model=list[BaselineRead])
async def list_baselines(
    session: SessionDep, _: CurrentUser, project_id: int
) -> list[Baseline]:
    """The log of re-baseline events (newest first) — when the plan was reset and why."""
    rows = await session.execute(
        select(Baseline)
        .where(Baseline.project_id == project_id)
        .order_by(col(Baseline.id).desc())
    )
    return list(rows.scalars().all())


@router.get("/projects/{project_id}/burndown", response_model=BurndownResponse)
async def burndown(session: SessionDep, _: CurrentUser, project_id: int) -> BurndownResponse:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    tasks = list(
        (
            await session.execute(select(Task).where(Task.project_id == project_id))
        ).scalars().all()
    )
    leaves = [t for t in tasks if t.type != TaskType.summary]
    total = len(leaves)
    task_ids = {t.id for t in tasks}

    history = (
        await session.execute(
            select(TaskStatusHistory).where(col(TaskStatusHistory.task_id).in_(task_ids))
        )
    ).scalars().all()
    done_dates = sorted(
        h.changed_at.date() for h in history if is_done_status(h.to_status)
    )

    ends = [t.end for t in tasks if t.end]
    window_start = project.start_date or (done_dates[0] if done_dates else date.today())
    window_end = project.target_date or (max(ends) if ends else window_start)
    if window_end < window_start:
        window_end = window_start
    weeks = mondays(window_start, window_end)
    points = [
        BurndownPoint(week=p.week, total=p.total, completed=p.completed, remaining=p.remaining)
        for p in compute_burndown(total, done_dates, weeks)
    ]
    return BurndownResponse(project_id=project_id, points=points)


@router.get("/projects/{project_id}/alerts", response_model=AlertsResponse)
async def alerts(session: SessionDep, _: CurrentUser, project_id: int) -> AlertsResponse:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    tasks = list(
        (await session.execute(select(Task).where(Task.project_id == project_id))).scalars().all()
    )
    milestones = list(
        (
            await session.execute(select(Milestone).where(Milestone.project_id == project_id))
        ).scalars().all()
    )

    # Over-allocations: weeks where an engineer exceeds 100%.
    allocations = list(
        (
            await session.execute(select(Allocation).where(Allocation.project_id == project_id))
        ).scalars().all()
    )
    engineers = {
        e.id: e.name
        for e in (await session.execute(select(Engineer))).scalars().all()
        if e.id is not None
    }
    over: list[OverAllocation] = []
    if allocations:
        starts = [a.start_date for a in allocations if a.start_date]
        ends = [a.end_date for a in allocations if a.end_date]
        win_start = project.start_date or (min(starts) if starts else date.today())
        win_end = project.target_date or (max(ends) if ends else win_start + timedelta(weeks=8))
        grid = weekly_capacity(
            [AllocationSpan(a.engineer_id, a.percent_allocation, a.start_date, a.end_date)
             for a in allocations],
            win_start,
            win_end,
        )
        for eng_id, by_week in grid.items():
            for week, pct in by_week.items():
                if pct > 100:
                    over.append(
                        OverAllocation(engineers.get(eng_id, f"#{eng_id}"), week.isoformat(), pct)
                    )

    alert_tasks = [
        AlertTask(t.id, t.name, t.type == TaskType.summary, t.end, t.deadline)
        for t in tasks
        if t.id is not None
    ]
    alert_milestones = [
        AlertMilestone(m.id, m.name, m.target_date, m.status)
        for m in milestones
        if m.id is not None
    ]
    computed = compute_alerts(date.today(), alert_tasks, alert_milestones, over)
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
            for a in computed
        ],
    )
