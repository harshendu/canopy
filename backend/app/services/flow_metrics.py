"""Delivery metrics — DORA + flow, computed purely from canopy's own signal.

DORA (deploy frequency, change-fail rate, failed-deployment recovery time) comes from the
§J8 activity substrate; flow (throughput, cycle time, WIP, aging) comes from `TaskStatusHistory`
+ the board. Everything here is **team-level by design** — per-individual delivery metrics are a
Goodhart trap (see `docs/AI_NATIVE_EXECUTION.md` §4), so this module never takes an engineer key.

Honesty over false precision (the forecast's instinct): when the inputs are too thin to mean
anything, report `sufficient=False` with a reason rather than a confident-looking zero. Metrics
canopy can't compute from its data (PR review latency, decision latency) are deliberately absent.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from app.models.base import ActivityKind

MIN_HISTORY_WEEKS = 3  # same bar as the probabilistic forecast


@dataclass
class ActivityPoint:
    kind: str
    at: datetime


@dataclass
class DoraMetrics:
    window_weeks: float
    deploys: int
    deploy_frequency_per_week: float
    failures: int  # incidents opened in the window
    change_fail_rate: float | None  # failures / deploys (None when there were no deploys)
    recovered_incidents: int
    mean_recovery_hours: float | None
    median_recovery_hours: float | None


@dataclass
class FlowMetrics:
    completed_items: int  # items finished in the window
    throughput_per_week: float | None
    cycle_time_median_days: float | None
    cycle_time_p85_days: int | None
    wip: int  # current not-done leaf tasks (a now-snapshot, not windowed)
    aging_wip: int  # WIP older than the team's cycle-time P85
    sufficient: bool
    reason: str | None = None


def _percentile(values: list[int], pct: float) -> int:
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return ordered[rank - 1]


def _median(values: list[int]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2


def _recovery_hours(events: list[ActivityPoint]) -> list[float]:
    """Hours from incident_open to incident_close, paired in time order (FIFO).

    The activity substrate has no incident id linking open→close, so each close resolves the
    oldest still-open incident — a reasonable MTTR approximation."""
    open_times: list[datetime] = []
    durations: list[float] = []
    for event in sorted(events, key=lambda e: e.at):
        if event.kind == ActivityKind.incident_open:
            open_times.append(event.at)
        elif event.kind == ActivityKind.incident_close and open_times:
            opened = open_times.pop(0)
            durations.append((event.at - opened).total_seconds() / 3600)
    return durations


def compute_dora(events: list[ActivityPoint], window_weeks: float) -> DoraMetrics:
    deploys = sum(1 for e in events if e.kind == ActivityKind.deploy)
    failures = sum(1 for e in events if e.kind == ActivityKind.incident_open)
    recoveries = _recovery_hours(events)
    return DoraMetrics(
        window_weeks=round(window_weeks, 1),
        deploys=deploys,
        deploy_frequency_per_week=round(deploys / window_weeks, 2) if window_weeks else 0.0,
        failures=failures,
        change_fail_rate=round(failures / deploys, 3) if deploys else None,
        recovered_incidents=len(recoveries),
        mean_recovery_hours=round(sum(recoveries) / len(recoveries), 2) if recoveries else None,
        median_recovery_hours=(
            round(m, 2) if (m := _median([round(r) for r in recoveries])) is not None else None
        ),
    )


def compute_flow(
    throughput: list[int], cycle_samples: list[int], wip: int, aging_wip: int
) -> FlowMetrics:
    """`throughput` = items completed per ISO week over the window (incl. zero weeks);
    `cycle_samples` = per-item created→done days for items finished in the window."""
    sufficient = len(throughput) >= MIN_HISTORY_WEEKS and sum(throughput) > 0
    median = _median(cycle_samples)
    return FlowMetrics(
        completed_items=len(cycle_samples),
        throughput_per_week=(
            round(sum(throughput) / len(throughput), 2) if throughput else None
        ),
        cycle_time_median_days=round(median, 1) if median is not None else None,
        cycle_time_p85_days=_percentile(cycle_samples, 85) if cycle_samples else None,
        wip=wip,
        aging_wip=aging_wip,
        sufficient=sufficient,
        reason=(
            None
            if sufficient
            else (
                "Not enough completed-work history for stable flow metrics — needs at least "
                f"{MIN_HISTORY_WEEKS} weeks with some throughput "
                "(sync Jira status / mark tasks done)."
            )
        ),
    )
