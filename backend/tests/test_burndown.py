from datetime import date

from app.services.burndown import compute_burndown, is_done_status


def test_is_done_status():
    assert is_done_status("Done")
    assert is_done_status("resolved")
    assert is_done_status("CLOSED")
    assert not is_done_status("In Progress")
    assert not is_done_status(None)


def test_compute_burndown_decreases_remaining():
    weeks = [date(2026, 1, 5), date(2026, 1, 12), date(2026, 1, 19)]
    done = [date(2026, 1, 8), date(2026, 1, 15)]  # one in week 1, one in week 2
    points = compute_burndown(total=3, done_dates=done, weeks=weeks)
    assert [(p.completed, p.remaining) for p in points] == [(1, 2), (2, 1), (2, 1)]
    assert all(p.total == 3 for p in points)


def test_compute_burndown_no_completions():
    weeks = [date(2026, 1, 5)]
    points = compute_burndown(total=4, done_dates=[], weeks=weeks)
    assert points[0].remaining == 4
    assert points[0].completed == 0
