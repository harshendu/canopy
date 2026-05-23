"""Weekly capacity aggregation for the resource heatmap.

Pure logic (no DB) so it is unit-testable: given allocation spans and a window,
sum each engineer's allocation percentage per ISO week (Monday-aligned).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass
class AllocationSpan:
    engineer_id: int
    percent: float
    start: date | None
    end: date | None


def mondays(window_start: date, window_end: date) -> list[date]:
    """Monday-aligned week starts covering [window_start, window_end] inclusive."""
    first = window_start - timedelta(days=window_start.weekday())
    last = window_end - timedelta(days=window_end.weekday())
    weeks: list[date] = []
    cursor = first
    while cursor <= last:
        weeks.append(cursor)
        cursor += timedelta(days=7)
    return weeks


def weekly_capacity(
    allocations: list[AllocationSpan], window_start: date, window_end: date
) -> dict[int, dict[date, float]]:
    """Return {engineer_id: {week_start: summed_percent}} across the window's weeks."""
    weeks = mondays(window_start, window_end)
    result: dict[int, dict[date, float]] = {}
    for span in allocations:
        if span.start is None or span.end is None:
            continue
        for week in weeks:
            week_end = week + timedelta(days=6)
            if span.start <= week_end and span.end >= week:  # span overlaps this week
                per_engineer = result.setdefault(span.engineer_id, {})
                per_engineer[week] = per_engineer.get(week, 0.0) + span.percent
    return result
