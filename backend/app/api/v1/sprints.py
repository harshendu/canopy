"""Delivery methods, the team board and sprints (USER_FLOWS §C11).

- `delivery_router` (core): a team's delivery settings (`kanban` | `sprint` | `both`, sprint
  length, estimate unit) and the team board — one board over every project the team runs.
- `router` (feature `tracking.sprints`): sprints — create/plan/start/complete/reopen, the sprint
  report (burndown, scope change, carry-over) and team velocity with a per-sprint forecast.

Reads are open. Delivery settings: the team's directors/managers (or an admin). Sprints: those
plus the planners of the team's projects. A sprint mirrored from a tracker is read-only (409
`sprint_externally_owned`); a mirrored task whose tracker syncs sprints can't be re-planned here
(409 `membership_externally_owned`). Nothing about sprints is written to a tracker.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    ContributorWriter,
    CurrentUser,
    FeatureGate,
    PlannerWriter,
    SessionDep,
    current_engineer,
    is_planner,
)
from app.api.v1.tasks import actor_name
from app.core.events import publish
from app.models.base import (
    CANOPY_OWNER,
    DeliveryMethod,
    EstimateUnit,
    SprintState,
    StatusSource,
)
from app.models.org import Team
from app.models.project import Task
from app.models.sprint import Sprint
from app.models.team import Engineer
from app.models.user import User
from app.schemas.entities import (
    BoardResponse,
    BoardViewer,
    BurndownDayRead,
    EngineerCapacityRead,
    SprintCapacityRead,
    SprintCompleteRequest,
    SprintCreate,
    SprintDetail,
    SprintForecastRead,
    SprintRead,
    SprintReportRead,
    SprintTasksRequest,
    SprintUpdate,
    TaskRead,
    TeamDeliveryRead,
    TeamDeliveryUpdate,
    VelocityPointRead,
    VelocityRead,
)
from app.services import sprint_service as svc
from app.services import sprints as metrics
from app.services.access import (
    ensure_sprint_manageable,
    ensure_team_manageable,
    sprint_can_manage,
    team_can_manage,
)
from app.services.board import team_board
from app.services.features import feature_enabled
from app.services.workflow import TrackingError

delivery_router = APIRouter()
router = APIRouter()


def _http(exc: TrackingError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail())


async def _team(session: AsyncSession, team_id: int) -> Team:
    team = await session.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    return team


async def _sprint(session: AsyncSession, sprint_id: int) -> tuple[Sprint, Team]:
    sprint = await session.get(Sprint, sprint_id)
    if sprint is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sprint not found")
    return sprint, await _team(session, sprint.team_id)


async def sprint_read(session: AsyncSession, sprint: Sprint, team: Team) -> SprintRead:
    assert sprint.id is not None
    members = await svc.sprint_tasks(session, sprint.id)
    unit = sprint.estimate_unit or svc.unit_for(team, members)
    read = SprintRead.model_validate(sprint)
    read.task_count = len(members)
    read.done_count = sum(1 for t in members if svc.is_done(t))
    read.scope = round(sum(svc.estimate(t, unit) for t in members), 2)
    read.done = round(sum(svc.estimate(t, unit) for t in members if svc.is_done(t)), 2)
    read.unit = unit
    return read


async def _publish(team_id: int, sprint_id: int | None = None) -> None:
    await publish({"type": "sprint", "team_id": team_id, "sprint_id": sprint_id})


# --------------------------------------------------------------------------- #
# Delivery settings + the team board (core)
# --------------------------------------------------------------------------- #


async def _delivery_read(session: AsyncSession, team: Team, user: User) -> TeamDeliveryRead:
    assert team.id is not None
    view = await svc.team_delivery(session, team)
    active = await svc.active_sprints(session, team.id)
    return TeamDeliveryRead(
        team_id=team.id,
        delivery_method=DeliveryMethod(view.method),
        effective_method=DeliveryMethod(view.effective_method),
        sprint_length_days=view.sprint_length_days,
        estimate_unit=EstimateUnit(view.estimate_unit),
        sprints_enabled=view.sprints_enabled,
        can_manage=await team_can_manage(session, user, team.id),
        active_sprint_id=active[0].id if active else None,
    )


@delivery_router.get("/teams/{team_id}/delivery", response_model=TeamDeliveryRead)
async def get_team_delivery(
    session: SessionDep, user: CurrentUser, team_id: int
) -> TeamDeliveryRead:
    """How the team runs its work across all its projects (`effective_method` is kanban when
    the `tracking.sprints` feature is off)."""
    return await _delivery_read(session, await _team(session, team_id), user)


@delivery_router.put("/teams/{team_id}/delivery", response_model=TeamDeliveryRead)
async def put_team_delivery(
    session: SessionDep, user: ContributorWriter, team_id: int, payload: TeamDeliveryUpdate
) -> TeamDeliveryRead:
    """Choose kanban | sprint | both for every project of the team (directors/managers or an
    admin). Switching to kanban needs the active sprint completed; nothing is deleted."""
    team = await _team(session, team_id)
    await ensure_team_manageable(session, user, team_id)
    try:
        await svc.set_team_delivery(
            session,
            team,
            method=payload.delivery_method.value if payload.delivery_method else None,
            sprint_length_days=payload.sprint_length_days,
            estimate_unit=payload.estimate_unit.value if payload.estimate_unit else None,
        )
    except TrackingError as exc:
        raise _http(exc) from exc
    await session.commit()
    await session.refresh(team)
    await _publish(team_id)
    return await _delivery_read(session, team, user)


@delivery_router.get(
    "/teams/{team_id}/board",
    response_model=BoardResponse,
    dependencies=[FeatureGate("tracking.board")],
)
async def get_team_board(
    session: SessionDep,
    user: CurrentUser,
    team_id: int,
    pod_id: int | None = None,
    project_id: int | None = None,
    sprint: str | None = None,
) -> BoardResponse:
    """One board over every project the team runs, on the team's columns (a card whose status
    they don't name sits in the first column of its category). `sprint` = active | backlog |
    all | a sprint id; `pod_id` / `project_id` narrow it."""
    await _team(session, team_id)
    engineer = await current_engineer(session, user)
    viewer = BoardViewer(
        can_plan=is_planner(user) and await sprint_can_manage(session, user, team_id),
        engineer_id=engineer.id if engineer is not None else None,
        native_enabled=await feature_enabled(session, "tracking.native"),
    )
    return await team_board(
        session, team_id, viewer, pod_id=pod_id, project_id=project_id, sprint=sprint
    )


# --------------------------------------------------------------------------- #
# Sprints (feature `tracking.sprints`)
# --------------------------------------------------------------------------- #


@router.get("/teams/{team_id}/sprints", response_model=list[SprintRead])
async def list_sprints(
    session: SessionDep, _: CurrentUser, team_id: int, state: SprintState | None = None
) -> list[SprintRead]:
    """The team's sprints: active first, then planned, then completed (newest first)."""
    team = await _team(session, team_id)
    rows = await svc.team_sprints(session, team_id, state.value if state else None)
    return [await sprint_read(session, s, team) for s in rows]


@router.post(
    "/teams/{team_id}/sprints", response_model=SprintRead, status_code=status.HTTP_201_CREATED
)
async def create_sprint(
    session: SessionDep, user: PlannerWriter, team_id: int, payload: SprintCreate
) -> SprintRead:
    """Create a planned sprint. Dates default to the day after the team's last sprint, for
    the team's sprint length; the name defaults to "Sprint <n>". The team must run sprints."""
    team = await _team(session, team_id)
    await ensure_sprint_manageable(session, user, team_id)
    view = await svc.team_delivery(session, team)
    if not view.uses_sprints:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "team_is_kanban",
                "message": "This team works as Kanban — switch its delivery method to sprint "
                "or both first",
            },
        )
    default_start, default_end = await svc.default_dates(session, team, date.today())
    start = payload.start_date or default_start
    end = payload.end_date or start + (default_end - default_start)
    if end < start:
        raise HTTPException(status_code=422, detail="end_date is before start_date")
    count = len(await svc.team_sprints(session, team_id))
    sprint = Sprint(
        team_id=team_id,
        pod_id=payload.pod_id,
        name=(payload.name or "").strip() or f"Sprint {count + 1}",
        goal=payload.goal,
        start_date=start,
        end_date=end,
        state=SprintState.planned.value,
        owner=CANOPY_OWNER,
    )
    session.add(sprint)
    await session.commit()
    await session.refresh(sprint)
    await _publish(team_id, sprint.id)
    return await sprint_read(session, sprint, team)


@router.get("/sprints/{sprint_id}", response_model=SprintDetail)
async def get_sprint(session: SessionDep, _: CurrentUser, sprint_id: int) -> SprintDetail:
    """A sprint with its tasks and the planning view: committed estimate vs the team's capacity
    over the sprint dates (person-days from allocations/availability) and mean velocity."""
    sprint, team = await _sprint(session, sprint_id)
    base = await sprint_read(session, sprint, team)
    members = await svc.sprint_tasks(session, sprint_id)
    capacity: SprintCapacityRead | None = None
    if sprint.start_date is not None and sprint.end_date is not None:
        per = await svc.team_capacity(session, sprint.team_id, sprint.start_date, sprint.end_date)
        names = {
            e.id: e.name
            for eid in per
            if (e := await session.get(Engineer, eid)) is not None and e.id is not None
        }
        velocity = metrics.velocity(await svc.velocity_points(session, sprint.team_id))
        open_scope = round(
            sum(svc.estimate(t, base.unit) for t in members if not svc.is_closed(t)), 2
        )
        total_days = round(sum(per.values()), 1)
        over: bool | None = None
        if base.unit == "days":
            over = open_scope > total_days if total_days > 0 else None
        elif velocity.mean is not None and velocity.sufficient:
            over = open_scope > velocity.mean
        capacity = SprintCapacityRead(
            person_days=total_days,
            engineers=[
                EngineerCapacityRead(engineer_id=eid, name=names.get(eid, f"#{eid}"),
                                     person_days=days)
                for eid, days in sorted(per.items(), key=lambda kv: -kv[1])
            ],
            velocity_mean=velocity.mean,
            committed=open_scope,
            unit=base.unit,
            over_capacity=over,
        )
    return SprintDetail(
        **base.model_dump(),
        tasks=[TaskRead.model_validate(t) for t in members],
        capacity=capacity,
    )


@router.patch("/sprints/{sprint_id}", response_model=SprintRead)
async def update_sprint(
    session: SessionDep, user: PlannerWriter, sprint_id: int, payload: SprintUpdate
) -> SprintRead:
    sprint, team = await _sprint(session, sprint_id)
    await ensure_sprint_manageable(session, user, sprint.team_id)
    if sprint.owner != CANOPY_OWNER:
        raise _http(TrackingError(
            "sprint_externally_owned", f"This sprint is mirrored from {sprint.owner}", 409,
            provider=sprint.owner,
        ))
    if sprint.state == SprintState.completed.value:
        raise _http(TrackingError("sprint_completed", "A completed sprint can't be edited", 409))
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(sprint, field, value)
    if sprint.start_date and sprint.end_date and sprint.end_date < sprint.start_date:
        raise HTTPException(status_code=422, detail="end_date is before start_date")
    await session.commit()
    await session.refresh(sprint)
    await _publish(sprint.team_id, sprint_id)
    return await sprint_read(session, sprint, team)


@router.delete("/sprints/{sprint_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sprint(session: SessionDep, user: PlannerWriter, sprint_id: int) -> None:
    """Delete a planned (never started) sprint; its tasks return to the backlog."""
    sprint, _ = await _sprint(session, sprint_id)
    await ensure_sprint_manageable(session, user, sprint.team_id)
    if sprint.owner != CANOPY_OWNER or sprint.state != SprintState.planned.value:
        raise _http(TrackingError(
            "not_deletable", "Only a planned canopy sprint can be deleted", 409
        ))
    for task in await svc.sprint_tasks(session, sprint_id):
        svc.record_membership(
            session, task, None, source=StatusSource.canopy, author=actor_name(user)
        )
    await svc.delete_sprint_rows(session, sprint)
    await session.commit()
    await _publish(sprint.team_id, sprint_id)


@router.post("/sprints/{sprint_id}/tasks", response_model=SprintRead)
async def add_sprint_tasks(
    session: SessionDep, user: PlannerWriter, sprint_id: int, payload: SprintTasksRequest
) -> SprintRead:
    """Plan tasks into the sprint (each leaves any previous sprint; recorded)."""
    sprint, team = await _sprint(session, sprint_id)
    await ensure_sprint_manageable(session, user, sprint.team_id)
    try:
        await svc.add_tasks(session, sprint, payload.task_ids, author=actor_name(user))
    except TrackingError as exc:
        await session.rollback()
        raise _http(exc) from exc
    await session.commit()
    await session.refresh(sprint)
    await _publish(sprint.team_id, sprint_id)
    return await sprint_read(session, sprint, team)


@router.delete("/sprints/{sprint_id}/tasks/{task_id}", response_model=SprintRead)
async def remove_sprint_task(
    session: SessionDep, user: PlannerWriter, sprint_id: int, task_id: int
) -> SprintRead:
    """Take a task out of the sprint, back to the backlog (recorded as scope removed)."""
    sprint, team = await _sprint(session, sprint_id)
    await ensure_sprint_manageable(session, user, sprint.team_id)
    task = await session.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    try:
        await svc.remove_task(session, sprint, task, author=actor_name(user))
    except TrackingError as exc:
        raise _http(exc) from exc
    await session.commit()
    await session.refresh(sprint)
    await _publish(sprint.team_id, sprint_id)
    return await sprint_read(session, sprint, team)


@router.post("/sprints/{sprint_id}/start", response_model=SprintRead)
async def start_sprint(session: SessionDep, user: PlannerWriter, sprint_id: int) -> SprintRead:
    """Start a planned sprint: it becomes active and its commitment is captured. One active
    sprint per team (or per pod for pod-scoped sprints)."""
    sprint, team = await _sprint(session, sprint_id)
    await ensure_sprint_manageable(session, user, sprint.team_id)
    try:
        await svc.start_sprint(session, sprint, team, author=actor_name(user))
    except TrackingError as exc:
        raise _http(exc) from exc
    await session.commit()
    await session.refresh(sprint)
    await _publish(sprint.team_id, sprint_id)
    return await sprint_read(session, sprint, team)


@router.post("/sprints/{sprint_id}/complete", response_model=SprintRead)
async def complete_sprint(
    session: SessionDep, user: PlannerWriter, sprint_id: int, payload: SprintCompleteRequest
) -> SprintRead:
    """Complete the active sprint: capture what was done, then move each unfinished task to
    `next_sprint_id` (carry_over=next) or back to the backlog (recorded as carry-over)."""
    sprint, team = await _sprint(session, sprint_id)
    await ensure_sprint_manageable(session, user, sprint.team_id)
    next_sprint = (
        await session.get(Sprint, payload.next_sprint_id)
        if payload.next_sprint_id is not None
        else None
    )
    try:
        await svc.complete_sprint(
            session,
            sprint,
            team,
            carry_over=payload.carry_over,
            next_sprint=next_sprint,
            author=actor_name(user),
        )
    except TrackingError as exc:
        await session.rollback()
        raise _http(exc) from exc
    await session.commit()
    await session.refresh(sprint)
    await _publish(sprint.team_id, sprint_id)
    return await sprint_read(session, sprint, team)


@router.post("/sprints/{sprint_id}/reopen", response_model=SprintRead)
async def reopen_sprint(session: SessionDep, user: PlannerWriter, sprint_id: int) -> SprintRead:
    sprint, team = await _sprint(session, sprint_id)
    await ensure_sprint_manageable(session, user, sprint.team_id)
    try:
        await svc.reopen_sprint(session, sprint)
    except TrackingError as exc:
        raise _http(exc) from exc
    await session.commit()
    await session.refresh(sprint)
    await _publish(sprint.team_id, sprint_id)
    return await sprint_read(session, sprint, team)


@router.get("/sprints/{sprint_id}/report", response_model=SprintReportRead)
async def sprint_report(session: SessionDep, _: CurrentUser, sprint_id: int) -> SprintReportRead:
    """Sprint burndown (remaining vs ideal, scope added shown separately), commitment vs
    completed, scope change and carry-over."""
    sprint, team = await _sprint(session, sprint_id)
    base = await sprint_read(session, sprint, team)
    unit = sprint.estimate_unit or base.unit
    items, _tasks = await svc.sprint_items(session, sprint, unit)
    if sprint.start_date is None or sprint.end_date is None:
        return SprintReportRead(
            sprint=base, unit=unit, burndown=[], committed=0, completed=0, scope_added=0,
            scope_removed=0, carried_over=0,
        )
    totals = metrics.sprint_totals(sprint.start_date, sprint.end_date, items)
    committed = sprint.committed if sprint.committed is not None else totals.committed
    completed = sprint.completed if sprint.completed is not None else totals.completed
    return SprintReportRead(
        sprint=base,
        unit=unit,
        burndown=[
            BurndownDayRead(day=d.day, remaining=d.remaining, ideal=d.ideal,
                            scope_added=d.scope_added)
            for d in metrics.sprint_burndown(
                sprint.start_date, sprint.end_date, items, date.today(), sprint.committed
            )
        ],
        committed=committed,
        completed=completed,
        scope_added=totals.scope_added,
        scope_removed=totals.scope_removed,
        carried_over=totals.carried_over,
        reliability=round(completed / committed, 2) if committed else None,
    )


@router.get("/teams/{team_id}/velocity", response_model=VelocityRead)
async def team_velocity(session: SessionDep, _: CurrentUser, team_id: int) -> VelocityRead:
    """Completed estimate per completed sprint (mean and range over the last six), commitment
    reliability, and the P50/P85 number of sprints to finish the team's open work. Team-level
    only — never per engineer."""
    team = await _team(session, team_id)
    points = await svc.velocity_points(session, team_id)
    v = metrics.velocity(points)
    active = await svc.active_sprints(session, team_id)
    # Everything still to finish: the backlog plus work already planned into sprints.
    work = await svc.team_open_work(session, team_id)
    unit = svc.unit_for(team, work)
    remaining = sum(svc.estimate(t, unit) for t in work)
    anchor = max((s.end_date for s in active if s.end_date is not None), default=date.today())
    forecast = metrics.sprint_forecast(
        remaining, [p.completed for p in v.points], team.sprint_length_days, anchor
    )
    return VelocityRead(
        team_id=team_id,
        unit=unit,
        points=[
            VelocityPointRead(
                sprint_id=p.sprint_id, name=p.name, end_date=p.end_date, committed=p.committed,
                completed=p.completed, reliability=p.reliability,
            )
            for p in v.points
        ],
        mean=v.mean,
        low=v.low,
        high=v.high,
        mean_reliability=v.mean_reliability,
        sufficient=v.sufficient,
        reason=v.reason,
        forecast=SprintForecastRead(
            sufficient=forecast.sufficient,
            remaining=forecast.remaining,
            history_sprints=forecast.history_sprints,
            p50_sprints=forecast.p50_sprints,
            p85_sprints=forecast.p85_sprints,
            p50_date=forecast.p50_date,
            p85_date=forecast.p85_date,
            reason=forecast.reason,
        ),
    )
