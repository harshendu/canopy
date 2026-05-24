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


@dataclass
class AvailabilitySpan:
    """A window where an engineer's capacity is scaled by `capacity_factor` (0..1)."""

    engineer_id: int
    capacity_factor: float
    start: date | None
    end: date | None


@dataclass
class OverAllocatedWeek:
    engineer_id: int
    week: date
    percent: float  # summed allocation demand for the week
    ceiling: float  # availability-scaled limit (100 * factor)


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


def weekly_availability(
    spans: list[AvailabilitySpan], window_start: date, window_end: date
) -> dict[int, dict[date, float]]:
    """Return {engineer_id: {week_start: factor}} — the *worst* (lowest) availability factor
    that touches each week. Weeks not covered by any span are absent (callers default to 1.0)."""
    weeks = mondays(window_start, window_end)
    result: dict[int, dict[date, float]] = {}
    for span in spans:
        if span.start is None or span.end is None:
            continue
        for week in weeks:
            week_end = week + timedelta(days=6)
            if span.start <= week_end and span.end >= week:  # span overlaps this week
                per_engineer = result.setdefault(span.engineer_id, {})
                prev = per_engineer.get(week)
                per_engineer[week] = (
                    span.capacity_factor if prev is None else min(prev, span.capacity_factor)
                )
    return result


def availability_factor(
    availability: dict[int, dict[date, float]], engineer_id: int, week: date
) -> float:
    """The availability factor for one engineer-week (1.0 when unconstrained)."""
    return availability.get(engineer_id, {}).get(week, 1.0)


def over_allocated_weeks(
    allocations: list[AllocationSpan],
    availability: list[AvailabilitySpan],
    window_start: date,
    window_end: date,
) -> list[OverAllocatedWeek]:
    """Weeks where allocation demand exceeds the availability-scaled ceiling (100 * factor).
    With no availability rows the factor is 1.0, preserving the plain >100% behaviour."""
    demand = weekly_capacity(allocations, window_start, window_end)
    avail = weekly_availability(availability, window_start, window_end)
    out: list[OverAllocatedWeek] = []
    for eng_id, by_week in demand.items():
        for week, pct in by_week.items():
            ceiling = 100.0 * availability_factor(avail, eng_id, week)
            if pct > ceiling:
                out.append(OverAllocatedWeek(eng_id, week, pct, ceiling))
    return out
