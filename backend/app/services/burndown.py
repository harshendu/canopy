"""Burndown computation from task completion events.

Pure logic (no DB) so it is unit-testable: given the total task count and the dates
tasks transitioned to a done status, compute remaining/completed per ISO week.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta

# Common "work is finished" column names across real Jira workflows — not just the four defaults.
# A team whose board ends in "Shipped"/"Deployed"/"Released" would otherwise never register as
# done anywhere (board ages forever, burndown never burns, forecast stays "insufficient"). Only
# unambiguous *completion* states are included (not "cancelled"/"won't do", which leave WIP but
# aren't completed work). Per-connection configurable done-mapping is the remaining follow-up.
DONE_STATUSES = frozenset(
    {
        "done",
        "closed",
        "resolved",
        "complete",
        "completed",
        "shipped",
        "deployed",
        "released",
        "live",
        "merged",
        "accepted",
    }
)


@dataclass
class BurndownPoint:
    week: date
    total: int
    completed: int
    remaining: int


def is_done_status(status: str | None) -> bool:
    return status is not None and status.strip().lower() in DONE_STATUSES


def done_dates_per_task(rows: Iterable[tuple[int, str | None, date]]) -> list[date]:
    """One completion date per task — the LAST transition into a done status — from `(task_id,
    to_status, changed_date)` rows. A task that bounced Done→Reopened→Done is counted once, not
    once per transition (which would inflate weekly throughput and could drive burndown
    `remaining` negative). Sorted ascending. Pure/testable — callers pass ORM fields as tuples."""
    latest: dict[int, date] = {}
    for task_id, to_status, changed in rows:
        if is_done_status(to_status) and (task_id not in latest or changed > latest[task_id]):
            latest[task_id] = changed
    return sorted(latest.values())


def compute_burndown(total: int, done_dates: list[date], weeks: list[date]) -> list[BurndownPoint]:
    """For each week start, count tasks completed by week-end; remaining = total - completed."""
    points: list[BurndownPoint] = []
    for week in weeks:
        week_end = week + timedelta(days=6)
        completed = sum(1 for d in done_dates if d <= week_end)
        points.append(
            BurndownPoint(week=week, total=total, completed=completed, remaining=total - completed)
        )
    return points
