from datetime import date

from app.services.scheduling import (
    SchedDep,
    SchedTask,
    assign_dates,
    compute_cpm,
    critical_path,
)

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
