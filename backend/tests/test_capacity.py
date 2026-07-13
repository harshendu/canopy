from datetime import date

from app.services.capacity import (
    AllocationSpan,
    AvailabilitySpan,
    mondays,
    over_allocated_weeks,
    weekly_availability,
    weekly_capacity,
)


def test_mondays_span():
    weeks = mondays(date(2026, 1, 7), date(2026, 1, 20))  # Wed -> next-next Tue
    assert weeks == [date(2026, 1, 5), date(2026, 1, 12), date(2026, 1, 19)]


def test_weekly_capacity_sums_overlaps():
    spans = [
        AllocationSpan(1, 50.0, date(2026, 1, 5), date(2026, 1, 18)),
        AllocationSpan(1, 30.0, date(2026, 1, 5), date(2026, 1, 11)),
        AllocationSpan(2, 100.0, date(2026, 1, 12), date(2026, 1, 18)),
    ]
    grid = weekly_capacity(spans, date(2026, 1, 5), date(2026, 1, 18))
    assert grid[1][date(2026, 1, 5)] == 80.0  # 50 + 30 overlap in week 1
    assert grid[1][date(2026, 1, 12)] == 50.0  # only the 50% span reaches week 2
    assert grid[2][date(2026, 1, 12)] == 100.0
    assert date(2026, 1, 5) not in grid.get(2, {})


def test_weekly_capacity_counts_open_ended_spans_across_the_window():
    # BUG-25: an open-ended allocation (no start/end) still consumes capacity every window week —
    # dropping it made a 100%-with-no-end-date allocation invisible to the over-allocation check.
    spans = [AllocationSpan(engineer_id=1, percent=100.0, start=None, end=None)]
    grid = weekly_capacity(spans, date(2026, 1, 5), date(2026, 1, 18))
    assert grid == {1: {date(2026, 1, 5): 100.0, date(2026, 1, 12): 100.0}}

    # A span with only an end date is bounded on the right, open on the left.
    half_open = [AllocationSpan(engineer_id=2, percent=50.0, start=None, end=date(2026, 1, 11))]
    grid2 = weekly_capacity(half_open, date(2026, 1, 5), date(2026, 1, 18))
    assert grid2 == {2: {date(2026, 1, 5): 50.0}}


def test_weekly_availability_takes_worst_factor_per_week():
    spans = [
        AvailabilitySpan(1, 0.5, date(2026, 1, 5), date(2026, 1, 18)),  # weeks 1-2 half
        AvailabilitySpan(1, 0.0, date(2026, 1, 5), date(2026, 1, 11)),  # week 1 fully out
    ]
    grid = weekly_availability(spans, date(2026, 1, 5), date(2026, 1, 18))
    assert grid[1][date(2026, 1, 5)] == 0.0  # min(0.5, 0.0) -> the worst wins
    assert grid[1][date(2026, 1, 12)] == 0.5
    assert date(2026, 1, 5) not in grid.get(2, {})


def test_over_allocated_weeks_without_availability_uses_100_threshold():
    allocs = [
        AllocationSpan(1, 120.0, date(2026, 1, 5), date(2026, 1, 11)),
        AllocationSpan(2, 100.0, date(2026, 1, 5), date(2026, 1, 11)),  # exactly 100 = ok
    ]
    over = over_allocated_weeks(allocs, [], date(2026, 1, 5), date(2026, 1, 11))
    assert [(o.engineer_id, o.percent, o.ceiling) for o in over] == [(1, 120.0, 100.0)]


def test_over_allocated_weeks_scales_ceiling_by_availability():
    allocs = [AllocationSpan(1, 60.0, date(2026, 1, 5), date(2026, 1, 11))]
    avail = [AvailabilitySpan(1, 0.5, date(2026, 1, 5), date(2026, 1, 11))]  # ceiling 50%
    over = over_allocated_weeks(allocs, avail, date(2026, 1, 5), date(2026, 1, 11))
    # 60% demand against a 50% availability-scaled ceiling is an over-allocation.
    assert len(over) == 1
    assert over[0].engineer_id == 1
    assert over[0].percent == 60.0
    assert over[0].ceiling == 50.0
