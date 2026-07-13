from datetime import date

from app.services.burndown import compute_burndown, done_dates_per_task, is_done_status


def test_is_done_status():
    assert is_done_status("Done")
    assert is_done_status("resolved")
    assert is_done_status("CLOSED")
    assert not is_done_status("In Progress")
    assert not is_done_status(None)


def test_is_done_status_recognizes_common_custom_done_columns():
    # BUG-14: a team whose board ends in Shipped/Deployed/Released must register as done.
    for name in ("Shipped", "deployed", "Released", "live", "MERGED", "accepted", "completed"):
        assert is_done_status(name), name
    # ...but a still-open / non-completion state is not done.
    for name in ("In Review", "Cancelled", "Won't Do", "Blocked"):
        assert not is_done_status(name), name


def test_done_dates_per_task_dedups_reopened_tasks():
    # BUG-15: task 1 went Done→Reopened→Done; it must contribute ONE date (the last), not two.
    rows = [
        (1, "Done", date(2026, 1, 5)),
        (1, "In Progress", date(2026, 1, 6)),
        (1, "Done", date(2026, 1, 12)),  # re-done — the one that should count
        (2, "Done", date(2026, 1, 8)),
        (3, "In Progress", date(2026, 1, 9)),  # never done — excluded
    ]
    assert done_dates_per_task(rows) == [date(2026, 1, 8), date(2026, 1, 12)]


def test_done_dates_per_task_empty():
    assert done_dates_per_task([]) == []


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
