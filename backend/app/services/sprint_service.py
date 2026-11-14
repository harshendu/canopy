"""Delivery methods and sprints — the DB side (USER_FLOWS §C11).

A team runs its work as `kanban`, `sprint` or `both`, across all its projects (the setting is
on `Team`). Sprints belong to a team (optionally one pod). Membership is one sprint per task,
written ONLY through `record_membership`, which keeps `Task.sprint_id` (and the legacy
`Task.sprint` name) in step and appends `TaskSprintHistory` — commitment, scope change and
carry-over are computed from that history (pure maths in `app/services/sprints.py`).

Ownership mirrors status ownership: a canopy-owned sprint is planned and run here; a sprint
mirrored from a tracker is read-only. A mirrored task's membership belongs to its tracker when
that tracker syncs sprints; every other task's membership is canopy's. Nothing about sprints is
ever written back to a tracker.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.core.config import settings
from app.models.base import (
    CANOPY_OWNER,
    DeliveryMethod,
    Provider,
    SprintState,
    StatusCategory,
    StatusSource,
    TaskType,
    utcnow,
)
from app.models.integration import Connection
from app.models.org import Team
from app.models.project import Project, Task, TaskStatusHistory
from app.models.sprint import Sprint, TaskSprintHistory
from app.models.team import Allocation, EngineerAvailability
from app.services import sprints as metrics
from app.services.features import feature_enabled
from app.services.org import project_team_id, team_project_ids
from app.services.workflow import TrackingError, category_of_history, category_of_task

SPRINT_METHODS = frozenset({DeliveryMethod.sprint.value, DeliveryMethod.both.value})


# --------------------------------------------------------------------------- #
# Delivery method
# --------------------------------------------------------------------------- #


@dataclass
class DeliveryView:
    team_id: int | None
    method: str  # what the team chose
    effective_method: str  # what applies now (kanban when sprints are off or there is no team)
    sprint_length_days: int
    estimate_unit: str
    sprints_enabled: bool  # feature `tracking.sprints`

    @property
    def uses_sprints(self) -> bool:
        return self.effective_method in SPRINT_METHODS


async def team_delivery(session: AsyncSession, team: Team) -> DeliveryView:
    enabled = await feature_enabled(session, "tracking.sprints")
    method = team.delivery_method
    return DeliveryView(
        team_id=team.id,
        method=method,
        effective_method=method if enabled else DeliveryMethod.kanban.value,
        sprint_length_days=team.sprint_length_days,
        estimate_unit=team.estimate_unit,
        sprints_enabled=enabled,
    )


async def project_delivery(session: AsyncSession, project: Project) -> DeliveryView:
    """A project runs its team's method; a project in no team is Kanban-only (there is no
    team to hold a sprint)."""
    team_id = await project_team_id(session, project)
    team = await session.get(Team, team_id) if team_id is not None else None
    if team is not None:
        return await team_delivery(session, team)
    return DeliveryView(
        team_id=None,
        method=DeliveryMethod.kanban.value,
        effective_method=DeliveryMethod.kanban.value,
        sprint_length_days=14,
        estimate_unit="count",
        sprints_enabled=await feature_enabled(session, "tracking.sprints"),
    )


def default_method() -> str:
    try:
        return DeliveryMethod(settings.DELIVERY_DEFAULT_METHOD).value
    except ValueError:
        return DeliveryMethod.kanban.value


async def set_team_delivery(
    session: AsyncSession,
    team: Team,
    *,
    method: str | None,
    sprint_length_days: int | None,
    estimate_unit: str | None,
) -> None:
    """Change a team's delivery settings. Leaving sprints (→ kanban) needs the active sprint
    completed first; nothing else is converted — past sprints stay as history."""
    if method is not None and method != team.delivery_method:
        if method == DeliveryMethod.kanban.value and await active_sprints(session, team.id):
            raise TrackingError(
                "active_sprint",
                "Complete the active sprint before switching the team to Kanban",
                409,
            )
        team.delivery_method = method
    if sprint_length_days is not None:
        if not 1 <= sprint_length_days <= 90:
            raise TrackingError("bad_sprint_length", "Sprint length must be 1-90 days", 422)
        team.sprint_length_days = sprint_length_days
    if estimate_unit is not None:
        team.estimate_unit = estimate_unit
    team.updated_at = utcnow()


# --------------------------------------------------------------------------- #
# Lookups
# --------------------------------------------------------------------------- #


async def active_sprints(
    session: AsyncSession, team_id: int | None, pod_id: int | None = None
) -> list[Sprint]:
    if team_id is None:
        return []
    stmt = select(Sprint).where(
        Sprint.team_id == team_id, Sprint.state == SprintState.active.value
    )
    rows = list((await session.execute(stmt)).scalars().all())
    if pod_id is not None:
        rows = [s for s in rows if s.pod_id in (None, pod_id)]
    return rows


async def team_sprints(
    session: AsyncSession, team_id: int, state: str | None = None
) -> list[Sprint]:
    stmt = select(Sprint).where(Sprint.team_id == team_id)
    if state is not None:
        stmt = stmt.where(Sprint.state == state)
    rows = (await session.execute(stmt)).scalars().all()
    order = {SprintState.active.value: 0, SprintState.planned.value: 1}
    return sorted(
        rows,
        key=lambda s: (
            order.get(s.state, 2),
            -(s.start_date.toordinal() if s.start_date else 0),
            -(s.id or 0),
        ),
    )


async def sprint_tasks(session: AsyncSession, sprint_id: int) -> list[Task]:
    return list(
        (await session.execute(select(Task).where(Task.sprint_id == sprint_id))).scalars().all()
    )


async def tracker_syncing_sprints(session: AsyncSession, project_id: int) -> str | None:
    """The provider whose sprints this project mirrors, if any (a Jira connection bound to the
    project with a `board_id`). Phase 3 replaces this with the binding's `sync_iterations`."""
    rows = (
        await session.execute(
            select(Connection).where(
                Connection.provider == Provider.jira, col(Connection.active).is_(True)
            )
        )
    ).scalars().all()
    for connection in rows:
        config = connection.config or {}
        try:
            bound = int(config.get("project_id", 0)) == project_id
        except (TypeError, ValueError):
            bound = False
        if bound and config.get("board_id"):
            return connection.provider.value
    return None


async def membership_owner(session: AsyncSession, task: Task) -> str:
    """Who decides this task's sprint: its tracker for a mirrored task whose tracker syncs
    sprints, else canopy."""
    if task.status_owner == CANOPY_OWNER:
        return CANOPY_OWNER
    provider = await tracker_syncing_sprints(session, task.project_id)
    return provider if provider is not None else CANOPY_OWNER


# --------------------------------------------------------------------------- #
# Membership (the one writer of Task.sprint_id)
# --------------------------------------------------------------------------- #


def record_membership(
    session: AsyncSession,
    task: Task,
    sprint: Sprint | None,
    *,
    source: StatusSource,
    author: str | None = None,
    at: datetime | None = None,
) -> TaskSprintHistory | None:
    """Put a task into `sprint` (None = back to the backlog), recording the move. Returns the
    history row (None when nothing changed). The task must have an id."""
    target = sprint.id if sprint is not None else None
    if task.sprint_id == target:
        return None
    assert task.id is not None
    row = TaskSprintHistory(
        task_id=task.id,
        from_sprint_id=task.sprint_id,
        to_sprint_id=target,
        changed_at=at or utcnow(),
        author=author,
        source=source.value,
    )
    task.sprint_id = target
    task.sprint = sprint.name if sprint is not None else None
    session.add(row)
    return row


async def delete_sprint_rows(session: AsyncSession, sprint: Sprint) -> None:
    """Remove a (planned, never started) sprint and the membership moves that touched it."""
    for row in (
        await session.execute(
            select(TaskSprintHistory).where(
                (col(TaskSprintHistory.to_sprint_id) == sprint.id)
                | (col(TaskSprintHistory.from_sprint_id) == sprint.id)
            )
        )
    ).scalars().all():
        await session.delete(row)
    await session.flush()
    await session.delete(sprint)


def _require_canopy_sprint(sprint: Sprint) -> None:
    if sprint.owner != CANOPY_OWNER:
        raise TrackingError(
            "sprint_externally_owned",
            f"This sprint is mirrored from {sprint.owner}; change it there",
            409,
            provider=sprint.owner,
        )


async def add_tasks(
    session: AsyncSession, sprint: Sprint, task_ids: list[int], *, author: str | None
) -> list[Task]:
    """Plan tasks into a sprint. Each must be a leaf task of one of the team's projects whose
    membership canopy owns; the sprint must not be completed. A task leaves its previous
    sprint (recorded)."""
    if sprint.state == SprintState.completed.value:
        raise TrackingError("sprint_completed", "A completed sprint can't take new work", 409)
    team_projects = set(await team_project_ids(session, sprint.team_id))
    added: list[Task] = []
    for task_id in task_ids:
        task = await session.get(Task, task_id)
        if task is None:
            raise TrackingError("not_found", f"Task {task_id} not found", 404)
        if task.project_id not in team_projects:
            raise TrackingError(
                "outside_team", f"Task {task_id} is not in one of this team's projects", 422
            )
        if task.type == TaskType.summary:
            raise TrackingError("not_a_card", "Summary tasks (phases) can't join a sprint", 422)
        owner = await membership_owner(session, task)
        if owner != CANOPY_OWNER:
            raise TrackingError(
                "membership_externally_owned",
                f"Task {task.key or task_id}'s sprint is set in {owner}",
                409,
                provider=owner,
            )
        record_membership(session, task, sprint, source=StatusSource.canopy, author=author)
        added.append(task)
    return added


async def remove_task(
    session: AsyncSession, sprint: Sprint, task: Task, *, author: str | None
) -> None:
    if task.sprint_id != sprint.id:
        raise TrackingError("not_in_sprint", "The task is not in this sprint", 404)
    owner = await membership_owner(session, task)
    if owner != CANOPY_OWNER:
        raise TrackingError(
            "membership_externally_owned", f"This task's sprint is set in {owner}", 409,
            provider=owner,
        )
    record_membership(session, task, None, source=StatusSource.canopy, author=author)


# --------------------------------------------------------------------------- #
# Estimates + lifecycle
# --------------------------------------------------------------------------- #


def unit_for(team: Team, tasks: list[Task]) -> str:
    return metrics.effective_unit(team.estimate_unit, [t.story_points for t in tasks])


def estimate(task: Task, unit: str) -> float:
    return metrics.estimate_of(unit, task.story_points, task.duration)


def is_done(task: Task) -> bool:
    return category_of_task(task) == StatusCategory.done


def is_closed(task: Task) -> bool:
    return category_of_task(task) in (StatusCategory.done, StatusCategory.cancelled)


async def default_dates(
    session: AsyncSession, team: Team, today: date
) -> tuple[date, date]:
    """The day after the team's latest sprint ends (else today), for the team's length."""
    assert team.id is not None
    ends = [s.end_date for s in await team_sprints(session, team.id) if s.end_date is not None]
    start = max(ends) + timedelta(days=1) if ends else today
    return start, start + timedelta(days=max(team.sprint_length_days, 1) - 1)


async def start_sprint(
    session: AsyncSession, sprint: Sprint, team: Team, *, author: str | None
) -> None:
    _require_canopy_sprint(sprint)
    if sprint.state != SprintState.planned.value:
        raise TrackingError("not_planned", "Only a planned sprint can start", 409)
    # One active sprint per team — or per pod when sprints are pod-scoped.
    others = [
        s
        for s in await active_sprints(session, sprint.team_id)
        if s.id != sprint.id
        and (s.pod_id is None or sprint.pod_id is None or s.pod_id == sprint.pod_id)
    ]
    if others:
        raise TrackingError(
            "active_sprint",
            f"{others[0].name!r} is still active — complete it first",
            409,
            sprint_id=others[0].id,
        )
    if sprint.start_date is None or sprint.end_date is None:
        raise TrackingError("missing_dates", "Give the sprint a start and end date first", 422)
    members = await sprint_tasks(session, sprint.id or 0)
    unit = unit_for(team, members)
    sprint.state = SprintState.active.value
    sprint.started_at = utcnow()
    sprint.estimate_unit = unit
    sprint.committed = round(sum(estimate(t, unit) for t in members if not is_closed(t)), 2)
    sprint.completed = None
    sprint.updated_at = utcnow()


async def complete_sprint(
    session: AsyncSession,
    sprint: Sprint,
    team: Team,
    *,
    carry_over: str,
    next_sprint: Sprint | None,
    author: str | None,
) -> list[Task]:
    """Close the sprint: capture what was completed, then send each unfinished task to the next
    sprint or back to the backlog (recorded). Returns the carried tasks."""
    _require_canopy_sprint(sprint)
    if sprint.state != SprintState.active.value:
        raise TrackingError("not_active", "Only an active sprint can be completed", 409)
    if carry_over == "next":
        if next_sprint is None:
            raise TrackingError("no_next_sprint", "Name the sprint unfinished work moves to", 422)
        if next_sprint.team_id != sprint.team_id or next_sprint.id == sprint.id:
            raise TrackingError("bad_next_sprint", "Pick another sprint of this team", 422)
        if next_sprint.state == SprintState.completed.value:
            raise TrackingError("bad_next_sprint", "The next sprint is already completed", 422)
        _require_canopy_sprint(next_sprint)
    members = await sprint_tasks(session, sprint.id or 0)
    unit = sprint.estimate_unit or unit_for(team, members)
    sprint.estimate_unit = unit
    sprint.completed = round(sum(estimate(t, unit) for t in members if is_done(t)), 2)
    sprint.state = SprintState.completed.value
    sprint.completed_at = utcnow()
    sprint.updated_at = utcnow()
    carried = [t for t in members if not is_closed(t)]
    target = next_sprint if carry_over == "next" else None
    for task in carried:
        record_membership(session, task, target, source=StatusSource.canopy, author=author)
    return carried


async def reopen_sprint(session: AsyncSession, sprint: Sprint) -> None:
    _require_canopy_sprint(sprint)
    if sprint.state != SprintState.completed.value:
        raise TrackingError("not_completed", "Only a completed sprint can be reopened", 409)
    if [s for s in await active_sprints(session, sprint.team_id) if s.pod_id == sprint.pod_id]:
        raise TrackingError("active_sprint", "Another sprint is active — complete it first", 409)
    sprint.state = SprintState.active.value
    sprint.completed = None
    sprint.completed_at = None
    sprint.updated_at = utcnow()


# --------------------------------------------------------------------------- #
# Reports
# --------------------------------------------------------------------------- #


async def sprint_items(
    session: AsyncSession, sprint: Sprint, unit: str
) -> tuple[list[metrics.SprintItem], list[Task]]:
    """Every task that was in the sprint at some point, with when it joined/left (relative to
    the start) and when it was done — the input of the burndown and the totals."""
    assert sprint.id is not None
    history = (
        await session.execute(
            select(TaskSprintHistory).where(
                (col(TaskSprintHistory.to_sprint_id) == sprint.id)
                | (col(TaskSprintHistory.from_sprint_id) == sprint.id)
            )
        )
    ).scalars().all()
    ids = {h.task_id for h in history} | {
        t.id for t in await sprint_tasks(session, sprint.id) if t.id is not None
    }
    tasks = (
        list((await session.execute(select(Task).where(col(Task.id).in_(ids)))).scalars().all())
        if ids
        else []
    )
    status_rows = (
        (
            await session.execute(
                select(TaskStatusHistory).where(col(TaskStatusHistory.task_id).in_(ids))
            )
        ).scalars().all()
        if ids
        else []
    )
    done_on: dict[int, date] = {}
    for row in status_rows:
        if category_of_history(row) == StatusCategory.done:
            day = row.changed_at.date()
            if row.task_id not in done_on or day > done_on[row.task_id]:
                done_on[row.task_id] = day
    start = sprint.start_date
    items: list[metrics.SprintItem] = []
    for task in tasks:
        assert task.id is not None
        moves = sorted(
            (h for h in history if h.task_id == task.id), key=lambda h: (h.changed_at, h.id or 0)
        )
        joins = [h.changed_at.date() for h in moves if h.to_sprint_id == sprint.id]
        leaves = [h.changed_at.date() for h in moves if h.from_sprint_id == sprint.id]
        last_join = joins[-1] if joins else None
        joined_late = last_join is not None and start is not None and last_join > start
        added_on = last_join if joined_late else None
        removed_on = None
        if task.sprint_id != sprint.id:
            after_join = [d for d in leaves if last_join is None or d >= last_join]
            removed_on = after_join[-1] if after_join else (leaves[-1] if leaves else None)
            # Leaving at (or after) the end is carry-over, not scope removed: it stays in the
            # burndown as unfinished work to the last day.
            closed_on = sprint.completed_at.date() if sprint.completed_at is not None else None
            if removed_on is not None and (
                (sprint.end_date is not None and removed_on >= sprint.end_date)
                or (closed_on is not None and removed_on >= closed_on)
            ):
                removed_on = None
        finished = done_on.get(task.id) if is_done(task) else None
        items.append(
            metrics.SprintItem(
                task_id=task.id,
                estimate=estimate(task, unit),
                done_on=finished,
                added_on=added_on,
                removed_on=removed_on,
            )
        )
    return items, tasks


async def team_capacity(
    session: AsyncSession, team_id: int, start: date, end: date
) -> dict[int, float]:
    """Person-days per engineer allocated to the team's projects over the sprint dates."""
    project_ids = await team_project_ids(session, team_id)
    if not project_ids:
        return {}
    allocations = (
        await session.execute(
            select(Allocation).where(col(Allocation.project_id).in_(project_ids))
        )
    ).scalars().all()
    engineers = {a.engineer_id for a in allocations}
    windows = (
        (
            await session.execute(
                select(EngineerAvailability).where(
                    col(EngineerAvailability.engineer_id).in_(engineers)
                )
            )
        ).scalars().all()
        if engineers
        else []
    )
    return metrics.capacity_person_days(
        start,
        end,
        [
            metrics.CapacitySpan(a.engineer_id, a.percent_allocation, a.start_date, a.end_date)
            for a in allocations
        ],
        [
            metrics.AvailabilityWindow(w.engineer_id, w.capacity_factor, w.start_date, w.end_date)
            for w in windows
        ],
    )


async def team_backlog(session: AsyncSession, team_id: int) -> list[Task]:
    """Open leaf tasks of the team's projects that sit in no live sprint."""
    project_ids = await team_project_ids(session, team_id)
    if not project_ids:
        return []
    live = {
        s.id
        for s in await team_sprints(session, team_id)
        if s.state != SprintState.completed.value
    }
    tasks = (
        await session.execute(
            select(Task).where(
                col(Task.project_id).in_(project_ids), Task.type != TaskType.summary
            )
        )
    ).scalars().all()
    return [
        t for t in tasks if not is_closed(t) and (t.sprint_id is None or t.sprint_id not in live)
    ]


async def team_open_work(session: AsyncSession, team_id: int) -> list[Task]:
    """Every open leaf task of the team's projects, wherever it is planned."""
    project_ids = await team_project_ids(session, team_id)
    if not project_ids:
        return []
    tasks = (
        await session.execute(
            select(Task).where(
                col(Task.project_id).in_(project_ids), Task.type != TaskType.summary
            )
        )
    ).scalars().all()
    return [t for t in tasks if not is_closed(t)]


async def velocity_points(session: AsyncSession, team_id: int) -> list[metrics.VelocityPoint]:
    completed = await team_sprints(session, team_id, SprintState.completed.value)
    return [
        metrics.VelocityPoint(
            sprint_id=s.id or 0,
            name=s.name,
            end_date=s.end_date,
            committed=float(s.committed or 0.0),
            completed=float(s.completed or 0.0),
        )
        for s in completed
    ]
