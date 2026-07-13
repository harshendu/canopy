"""Delivery metrics — DORA + flow, at project and initiative scope.

Reuses the existing flow building blocks (the board's WIP/aging, `weekly_throughput`,
`is_done_status`) and the §J8 activity substrate. **Team-level by design** — there is no
per-engineer breakdown (a Goodhart trap). Computation is pure in `app/services/flow_metrics.py`;
this module gathers the rows and assembles the response. See `docs/AI_NATIVE_EXECUTION.md` §4.
"""

from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, HTTPException, status
from sqlmodel import col, select

from app.api.deps import CurrentUser, SessionDep
from app.models.activity import ActivityEvent
from app.models.base import TaskType
from app.models.project import Initiative, Project, Task, TaskStatusHistory
from app.schemas.entities import (
    DeliveryMetricsRead,
    DoraMetricsRead,
    FlowMetricsRead,
)
from app.services import flow_metrics
from app.services.burndown import is_done_status
from app.services.flow import BoardTaskInput, build_board
from app.services.forecast import weekly_throughput

router = APIRouter()

_MAX_WEEKS = 52


def _clamp_weeks(weeks: int) -> int:
    return max(1, min(weeks, _MAX_WEEKS))


async def _delivery(
    session: SessionDep, project_ids: list[int], weeks: int, scope_level: str, scope_id: int
) -> DeliveryMetricsRead:
    today = date.today()
    window_start = today - timedelta(weeks=weeks)
    window_start_dt = datetime.combine(window_start, time.min)

    # DORA — from activity events in the window.
    points: list[flow_metrics.ActivityPoint] = []
    if project_ids:
        events = (
            await session.execute(
                select(ActivityEvent).where(
                    col(ActivityEvent.project_id).in_(project_ids),
                    col(ActivityEvent.created_at) >= window_start_dt,
                )
            )
        ).scalars()
        points = [flow_metrics.ActivityPoint(kind=e.kind, at=e.created_at) for e in events]
    dora = flow_metrics.compute_dora(points, float(weeks))

    # Flow — leaf tasks + their status history.
    leaves: list[Task] = []
    if project_ids:
        tasks = (
            await session.execute(
                select(Task).where(col(Task.project_id).in_(project_ids))
            )
        ).scalars()
        leaves = [t for t in tasks if t.type != TaskType.summary and t.id is not None]

    by_task: dict[int, list[TaskStatusHistory]] = {}
    if leaves:
        history = (
            await session.execute(
                select(TaskStatusHistory).where(
                    col(TaskStatusHistory.task_id).in_([t.id for t in leaves if t.id is not None])
                )
            )
        ).scalars()
        for h in history:
            by_task.setdefault(h.task_id, []).append(h)

    inputs: list[BoardTaskInput] = []
    cycle_samples: list[int] = []
    done_dates_window: list[date] = []
    for t in leaves:
        assert t.id is not None
        rows = by_task.get(t.id, [])
        # Last update, not created_at, when there's no matching status-history row (see gantt.py).
        entered = max(
            (h.changed_at.date() for h in rows if h.to_status == t.status),
            default=t.updated_at.date(),
        )
        done_dates = [h.changed_at.date() for h in rows if is_done_status(h.to_status)]
        cycle_days = max(0, (max(done_dates) - t.created_at.date()).days) if done_dates else None
        inputs.append(
            BoardTaskInput(
                id=t.id,
                name=t.name,
                status=t.status,
                assignee_engineer_id=t.assignee_engineer_id,
                is_done=is_done_status(t.status),
                age_days=max(0, (today - entered).days),
                cycle_days=cycle_days,
            )
        )
        if done_dates:
            last_done = max(done_dates)
            if last_done >= window_start:  # completed within the window
                done_dates_window.append(last_done)
                cycle_samples.append(max(0, (last_done - t.created_at.date()).days))

    board = build_board(inputs)
    wip = sum(lane.wip for lane in board.lanes)
    throughput = weekly_throughput(sorted(done_dates_window), today)
    flow = flow_metrics.compute_flow(throughput, cycle_samples, wip, board.aging_count)

    notes = [
        "Team-level only — deliberately never broken down per engineer (Goodhart's law).",
        "Change-fail rate ≈ incidents opened ÷ deploys; recovery time pairs "
        "incident_open→close in time order (no per-deploy failure link).",
        "PR review latency and decision latency are not computed yet "
        "(need GitHub PR metrics / ADR status history).",
    ]
    if not points:
        notes.append(
            f"No deploy/incident activity in the last {weeks} weeks — instrument the activity "
            "webhook (§J8) to populate DORA."
        )
    if not flow.sufficient and flow.reason:
        notes.append(flow.reason)

    return DeliveryMetricsRead(
        scope_level=scope_level,
        scope_id=scope_id,
        window_weeks=weeks,
        dora=DoraMetricsRead.model_validate(dora),
        flow=FlowMetricsRead.model_validate(flow),
        notes=notes,
    )


@router.get("/projects/{project_id}/delivery", response_model=DeliveryMetricsRead)
async def project_delivery(
    session: SessionDep, _: CurrentUser, project_id: int, weeks: int = 12
) -> DeliveryMetricsRead:
    """DORA + flow metrics for one project over the last `weeks` (default 12, max 52)."""
    if await session.get(Project, project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return await _delivery(session, [project_id], _clamp_weeks(weeks), "project", project_id)


@router.get("/initiatives/{initiative_id}/delivery", response_model=DeliveryMetricsRead)
async def initiative_delivery(
    session: SessionDep, _: CurrentUser, initiative_id: int, weeks: int = 12
) -> DeliveryMetricsRead:
    """DORA + flow metrics aggregated across an initiative's sub-projects."""
    if await session.get(Initiative, initiative_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Initiative not found")
    project_ids = [
        pid
        for pid in (
            await session.execute(
                select(col(Project.id)).where(Project.initiative_id == initiative_id)
            )
        ).scalars()
        if pid is not None
    ]
    return await _delivery(
        session, project_ids, _clamp_weeks(weeks), "initiative", initiative_id
    )
