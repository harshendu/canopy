"""Burndown computation from task completion events.

Pure logic (no DB) so it is unit-testable: given the total task count and the dates
tasks transitioned to a done status, compute remaining/completed per ISO week.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

DONE_STATUSES = frozenset({"done", "closed", "resolved", "complete"})


@dataclass
class BurndownPoint:
    week: date
    total: int
    completed: int
    remaining: int


def is_done_status(status: str | None) -> bool:
    return status is not None and status.strip().lower() in DONE_STATUSES


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
