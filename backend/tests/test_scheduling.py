from datetime import date

from app.services.scheduling import (
    SchedDep,
    SchedTask,
    WorkingCalendar,
    add_working_days,
    assign_dates,
    compute_cpm,
    critical_path,
    working_days_between,
)


def test_add_working_days_skips_weekend():
    # 2026-01-02 is a Friday; +1 working day lands on Monday 2026-01-05.
    cal = WorkingCalendar(weekend=frozenset({5, 6}))
    assert add_working_days(date(2026, 1, 2), 1, cal) == date(2026, 1, 5)


def test_working_days_between_skips_weekend():
    cal = WorkingCalendar(weekend=frozenset({5, 6}))
    assert working_days_between(date(2026, 1, 2), date(2026, 1, 5), cal) == 1


def test_trivial_calendar_is_plain_calendar_days():
    cal = WorkingCalendar()
    assert add_working_days(date(2026, 1, 2), 3, cal) == date(2026, 1, 5)
    assert working_days_between(date(2026, 1, 1), date(2026, 1, 6), cal) == 5


def test_holidays_are_skipped():
    cal = WorkingCalendar(weekend=frozenset({5, 6}), holidays=frozenset({date(2026, 1, 6)}))
    # Mon 01-05 + 1 working day skips the Tue 01-06 holiday -> Wed 01-07.
    assert add_working_days(date(2026, 1, 5), 1, cal) == date(2026, 1, 7)

# Diamond DAG:  A(2) -> B(3) -> D(2)  and  A(2) -> C(4) -> D(2)  (all FS).
# Hand-computed critical path is A -> C -> D (length 8); B has 1 day of float.
TASKS = [
    SchedTask(id=1, duration=2),  # A
    SchedTask(id=2, duration=3),  # B
    SchedTask(id=3, duration=4),  # C
    SchedTask(id=4, duration=2),  # D
]
DEPS = [
    SchedDep(1, 2),
    SchedDep(1, 3),
    SchedDep(2, 4),
    SchedDep(3, 4),
]


def test_cpm_critical_path():
    results = compute_cpm(TASKS, DEPS)
    assert results[1].is_critical
    assert results[3].is_critical
    assert results[4].is_critical
    assert not results[2].is_critical
    assert results[2].total_float == 1
    assert sorted(critical_path(results)) == [1, 3, 4]


def test_cpm_early_finish():
    results = compute_cpm(TASKS, DEPS)
    assert results[1].ef == 2
    assert results[3].ef == 6
    assert results[4].ef == 8  # project finish


def test_assign_dates():
    results = compute_cpm(TASKS, DEPS)
    assign_dates(TASKS, results, date(2026, 1, 1))
    assert results[1].start == date(2026, 1, 1)
    assert results[1].end == date(2026, 1, 3)
    assert results[4].start == date(2026, 1, 7)
    assert results[4].end == date(2026, 1, 9)


def test_lag_pushes_successor():
    results = compute_cpm(
        [SchedTask(id=1, duration=2), SchedTask(id=2, duration=2)],
        [SchedDep(1, 2, type="FS", lag=3)],
    )
    assert results[2].es == 5  # finish of 1 (2) + lag (3)
