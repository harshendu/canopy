from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.api.deps import (
    CurrentUser,
    FeatureGate,
    PlannerWriter,
    SessionDep,
    current_engineer,
    is_contributor,
    is_planner,
)
from app.core.events import publish
from app.models.base import RiskScope, RiskStatus, SprintState, StatusCategory, TaskType
from app.models.project import (
    Baseline,
    Blocker,
    Dependency,
    Milestone,
    Project,
    Task,
)
from app.models.risk_register import RiskItem
from app.models.sprint import Sprint
from app.models.team import Allocation, Engineer, EngineerAvailability
from app.models.user import User
from app.schemas.entities import (
    AlertRead,
    AlertsResponse,
    BaselineRead,
    BaselineRequest,
    BoardResponse,
    BoardViewer,
    BurndownPoint,
    BurndownResponse,
    ForecastResponse,
    GanttLink,
    GanttResponse,
    GanttTask,
    ReplanResult,
    WhatIfRequest,
)
from app.services import design_docs
from app.services.access import ensure_project_editable, project_can_edit
from app.services.alerts import (
    AlertBlocker,
    AlertDocFlag,
    AlertMilestone,
    AlertRiskItem,
    AlertSprintTask,
    AlertTask,
    OverAllocation,
    compute_alerts,
)
from app.services.board import completion_dates, history_points, project_board
from app.services.burndown import compute_burndown
from app.services.capacity import (
    AllocationSpan,
    AvailabilitySpan,
    mondays,
    over_allocated_weeks,
)
from app.services.doc_health import ATTENTION_FLAGS
from app.services.features import feature_enabled
from app.services.forecast import monte_carlo_forecast, weekly_throughput
from app.services.metadata import risk_exposure
from app.services.planner import PlanOutcome, reschedule_project
from app.services.scheduling import CycleError
from app.services.workflow import category_of_task

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
async def replan(session: SessionDep, user: PlannerWriter, project_id: int) -> ReplanResult:
    await ensure_project_editable(session, user, project_id)
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
    # One completion date per task (its last transition into a done category) — a reopened-
    # then-redone task must not count twice, which would inflate throughput / push burndown
    # remaining negative.
    done_dates = completion_dates(
        await history_points(session, [t.id for t in leaves if t.id is not None])
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
    remaining = sum(1 for t in leaves if _is_open(t))
    done_dates = completion_dates(
        await history_points(session, [t.id for t in leaves if t.id is not None])
    )
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
async def board(
    session: SessionDep, user: CurrentUser, project_id: int, sprint: str | None = None
) -> BoardResponse:
    """Kanban board: the project's workflow columns in order (empty ones included), cards
    ranked within each, WIP per column against its limit, aging vs cycle-time P85, and what
    the caller may move. Canopy-owned cards move via `POST /tasks/{id}/move`. `sprint` narrows
    it to `active` | `backlog` | `all` | a sprint id (teams that run sprints, §C11)."""
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    viewer = await board_viewer(session, user, project)
    return await project_board(session, project, viewer, sprint)


async def board_viewer(session: AsyncSession, user: User, project: Project) -> BoardViewer:
    """What the caller may do on this project's board (shared with the team board) — the same
    rules `POST /tasks/{id}/move` enforces: a planner who may edit the project moves any
    canopy-owned card; anyone else who contributes (a planner outside this project included)
    moves their own cards or pulls an unassigned one; a viewer moves nothing."""
    engineer = await current_engineer(session, user) if is_contributor(user) else None
    return BoardViewer(
        can_plan=is_planner(user) and await project_can_edit(session, user, project),
        engineer_id=engineer.id if engineer is not None else None,
        native_enabled=await feature_enabled(session, "tracking.native"),
    )


def _is_open(task: Task) -> bool:
    """Still to finish: not in a done or cancelled category (and not marked 100% by hand)."""
    return (
        category_of_task(task) not in (StatusCategory.done, StatusCategory.cancelled)
        and task.percent_complete < 100
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
    sprint_rows = {
        sp.id: sp
        for sp in (
            await session.execute(
                select(Sprint).where(
                    col(Sprint.id).in_({t.sprint_id for t in tasks if t.sprint_id is not None}),
                    Sprint.state == SprintState.active.value,
                )
            )
        ).scalars().all()
    }
    alert_sprint_tasks = [
        AlertSprintTask(
            task_id=t.id,
            name=t.name,
            end=t.end,
            sprint_name=sprint_rows[t.sprint_id].name,
            sprint_end=sprint_rows[t.sprint_id].end_date,
        )
        for t in tasks
        if t.id is not None
        and t.sprint_id in sprint_rows
        and t.type != TaskType.summary
        and category_of_task(t) not in (StatusCategory.done, StatusCategory.cancelled)
    ]
    # Design docs bearing on the project: changed after approval, behind a pin, a gate close
    # to its date, made private, unreachable (USER_FLOWS §V8).
    project_docs = await design_docs.docs_in_project(session, project_id)
    doc_flags = [
        AlertDocFlag(doc_id, flag.flag, flag.severity, flag.message)
        for doc_id, flags in (await design_docs.health_for(session, project_docs)).items()
        for flag in flags
        if flag.flag in ATTENTION_FLAGS
    ]
    computed = compute_alerts(
        date.today(),
        alert_tasks,
        alert_milestones,
        over,
        alert_blockers,
        alert_risks,
        alert_sprint_tasks,
        doc_flags,
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
