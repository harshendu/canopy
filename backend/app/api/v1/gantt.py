from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.api.deps import CurrentUser, FeatureGate, PlannerWriter, SessionDep
from app.core.events import publish
from app.models.base import RiskScope, RiskStatus, TaskType
from app.models.project import (
    Baseline,
    Blocker,
    Dependency,
    Milestone,
    Project,
    Task,
    TaskStatusHistory,
)
from app.models.risk_register import RiskItem
from app.models.team import Allocation, Engineer, EngineerAvailability
from app.schemas.entities import (
    AlertRead,
    AlertsResponse,
    BaselineRead,
    BaselineRequest,
    BoardLaneRead,
    BoardResponse,
    BoardTaskRead,
    BurndownPoint,
    BurndownResponse,
    ForecastResponse,
    GanttLink,
    GanttResponse,
    GanttTask,
    ReplanResult,
    WhatIfRequest,
)
from app.services.alerts import (
    AlertBlocker,
    AlertMilestone,
    AlertRiskItem,
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
)
from app.services.flow import BoardTaskInput, build_board
from app.services.forecast import monte_carlo_forecast, weekly_throughput
from app.services.metadata import risk_exposure
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
    engineer_names = {
        e.id: e.name
        for e in (await session.execute(select(Engineer))).scalars().all()
        if e.id is not None
    }
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
            assignee_engineer_id=t.assignee_engineer_id,
            assignee_name=(
                engineer_names.get(t.assignee_engineer_id)
                if t.assignee_engineer_id is not None
                else None
            ),
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


@router.post(
    "/projects/{project_id}/whatif",
    response_model=ReplanResult,
    dependencies=[FeatureGate("planning.whatif")],
)
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
    dependencies=[FeatureGate("planning.baselines")],
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


@router.get(
    "/projects/{project_id}/baselines",
    response_model=list[BaselineRead],
    dependencies=[FeatureGate("planning.baselines")],
)
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


@router.get(
    "/projects/{project_id}/burndown",
    response_model=BurndownResponse,
    dependencies=[FeatureGate("tracking.burndown")],
)
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
    # One completion date per task (last done transition) — a reopened-then-redone task must not
    # count twice, which would inflate throughput / push burndown remaining negative.
    done_dates = done_dates_per_task(
        (h.task_id, h.to_status, h.changed_at.date()) for h in history
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


@router.get(
    "/projects/{project_id}/forecast",
    response_model=ForecastResponse,
    dependencies=[FeatureGate("tracking.forecast")],
)
async def project_forecast(
    session: SessionDep, _: CurrentUser, project_id: int
) -> ForecastResponse:
    """Probabilistic (Monte-Carlo) completion forecast from historical weekly throughput."""
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    tasks = list(
        (
            await session.execute(select(Task).where(Task.project_id == project_id))
        ).scalars().all()
    )
    leaves = [t for t in tasks if t.type != TaskType.summary]
    remaining = sum(1 for t in leaves if t.percent_complete < 100)
    task_ids = {t.id for t in tasks}
    history = (
        await session.execute(
            select(TaskStatusHistory).where(col(TaskStatusHistory.task_id).in_(task_ids))
        )
    ).scalars().all()
    done_dates = sorted(h.changed_at.date() for h in history if is_done_status(h.to_status))
    today = date.today()
    result = monte_carlo_forecast(remaining, weekly_throughput(done_dates, today), today)
    return ForecastResponse(
        scope="project",
        id=project_id,
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


@router.get(
    "/projects/{project_id}/board",
    response_model=BoardResponse,
    dependencies=[FeatureGate("tracking.board")],
)
async def board(session: SessionDep, _: CurrentUser, project_id: int) -> BoardResponse:
    """Flow board: leaf tasks in status lanes, with WIP per lane and aging vs cycle-time P85."""
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    tasks = list(
        (
            await session.execute(select(Task).where(Task.project_id == project_id))
        ).scalars().all()
    )
    leaves = [t for t in tasks if t.type != TaskType.summary and t.id is not None]
    history = (
        await session.execute(
            select(TaskStatusHistory).where(
                col(TaskStatusHistory.task_id).in_({t.id for t in leaves})
            )
        )
    ).scalars().all()
    by_task: dict[int, list[TaskStatusHistory]] = {}
    for h in history:
        by_task.setdefault(h.task_id, []).append(h)

    today = date.today()
    inputs: list[BoardTaskInput] = []
    for t in leaves:
        assert t.id is not None
        rows = by_task.get(t.id, [])
        # When did it enter its current status? (latest matching transition; else the task's last
        # update, not created_at — a months-old task freshly moved in Jira but synced without its
        # changelog would otherwise read as aging-for-months, a false "stuck" signal.)
        entered = max(
            (h.changed_at.date() for h in rows if h.to_status == t.status),
            default=t.updated_at.date(),
        )
        age_days = max(0, (today - entered).days)
        done_dates = [h.changed_at.date() for h in rows if is_done_status(h.to_status)]
        cycle_days = (
            max(0, (max(done_dates) - t.created_at.date()).days) if done_dates else None
        )
        inputs.append(
            BoardTaskInput(
                id=t.id,
                name=t.name,
                status=t.status,
                assignee_engineer_id=t.assignee_engineer_id,
                is_done=is_done_status(t.status),
                age_days=age_days,
                cycle_days=cycle_days,
            )
        )

    result = build_board(inputs)
    return BoardResponse(
        project_id=project_id,
        cycle_time_p85_days=result.cycle_time_p85_days,
        aging_count=result.aging_count,
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
            for lane in result.lanes
        ],
    )


@router.get(
    "/projects/{project_id}/alerts",
    response_model=AlertsResponse,
    dependencies=[FeatureGate("tracking.alerts")],
)
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
        availability = [
            AvailabilitySpan(a.engineer_id, a.capacity_factor, a.start_date, a.end_date)
            for a in (await session.execute(select(EngineerAvailability))).scalars().all()
        ]
        over = [
            OverAllocation(
                engineers.get(o.engineer_id, f"#{o.engineer_id}"), o.week.isoformat(), o.percent
            )
            for o in over_allocated_weeks(
                [
                    AllocationSpan(a.engineer_id, a.percent_allocation, a.start_date, a.end_date)
                    for a in allocations
                ],
                availability,
                win_start,
                win_end,
            )
        ]

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
    task_names = {t.id: t.name for t in tasks if t.id is not None}
    open_blockers = (
        await session.execute(
            select(Blocker).where(
                col(Blocker.task_id).in_(set(task_names)),
                col(Blocker.resolved_at).is_(None),
            )
        )
    ).scalars().all()
    alert_blockers = [
        AlertBlocker(
            b.task_id,
            task_names.get(b.task_id, f"#{b.task_id}"),
            b.reason,
            severity=b.severity.value if b.severity is not None else None,
            needed_by=b.needed_by,
        )
        for b in open_blockers
    ]
    # Open register risks scoped to this project or one of its tasks (RAID digest only —
    # these do not feed the computed risk score).
    open_risks = (
        await session.execute(
            select(RiskItem).where(
                col(RiskItem.status).in_({RiskStatus.open, RiskStatus.mitigating}),
            )
        )
    ).scalars().all()
    task_id_set = set(task_names)
    alert_risks = [
        AlertRiskItem(
            id=r.id,
            title=r.title,
            exposure=risk_exposure(r.probability, r.impact),
            target_resolution_date=r.target_resolution_date,
        )
        for r in open_risks
        if r.id is not None
        and (
            (r.scope_level == RiskScope.project and r.scope_id == project_id)
            or (r.scope_level == RiskScope.task and r.scope_id in task_id_set)
        )
    ]
    computed = compute_alerts(
        date.today(), alert_tasks, alert_milestones, over, alert_blockers, alert_risks
    )
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
