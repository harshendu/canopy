"""Delivery metrics — DORA + flow, at project and initiative scope.

Reuses the existing flow building blocks (the board's aging, `weekly_throughput`, the status
categories stamped on history) and the §J8 activity substrate. **Team-level by design** — there
is no per-engineer breakdown (a Goodhart trap). Computation is pure in
`app/services/flow_metrics.py`; this module gathers the rows and assembles the response.
See `docs/AI_NATIVE_EXECUTION.md` §4.
"""

from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, HTTPException, status
from sqlmodel import col, select

from app.api.deps import CurrentUser, SessionDep
from app.models.activity import ActivityEvent
from app.models.base import StatusCategory
from app.models.project import Initiative, Project, Task
from app.schemas.entities import (
    DeliveryMetricsRead,
    DoraMetricsRead,
    FlowMetricsRead,
)
from app.services import flow_metrics
from app.services.board import board_inputs, history_points, leaves_of, task_flow_facts
from app.services.flow import build_board
from app.services.forecast import weekly_throughput
from app.services.workflow import category_of_task

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

    # Flow — leaf tasks + their status history, read by category (not status name).
    leaves: list[Task] = []
    if project_ids:
        tasks = (
            await session.execute(
                select(Task).where(col(Task.project_id).in_(project_ids))
            )
        ).scalars()
        leaves = leaves_of(list(tasks))
    history = await history_points(session, [t.id for t in leaves if t.id is not None])

    cycle_samples: list[int] = []
    lead_samples: list[int] = []
    done_dates_window: list[date] = []
    for t in leaves:
        facts = task_flow_facts(t, history, today)
        if facts.done_on is not None and facts.done_on >= window_start:  # done in the window
            done_dates_window.append(facts.done_on)
            if facts.cycle_days is not None:
                cycle_samples.append(facts.cycle_days)
            if facts.lead_days is not None:
                lead_samples.append(facts.lead_days)

    board = build_board(board_inputs(leaves, history, today))
    # Team WIP = work that has started and not finished (the backlog is not WIP).
    wip = sum(1 for t in leaves if category_of_task(t) == StatusCategory.in_progress)
    throughput = weekly_throughput(sorted(done_dates_window), today)
    flow = flow_metrics.compute_flow(
        throughput, cycle_samples, wip, board.aging_count, lead_samples
    )

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
