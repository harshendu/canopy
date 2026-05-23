from datetime import date

from app.services.capacity import AllocationSpan, mondays, weekly_capacity


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


def test_weekly_capacity_ignores_undated_spans():
    spans = [AllocationSpan(engineer_id=1, percent=100.0, start=None, end=None)]
    assert weekly_capacity(spans, date(2026, 1, 5), date(2026, 1, 11)) == {}
