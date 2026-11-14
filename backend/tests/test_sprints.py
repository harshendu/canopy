"""Sprint metrics (pure): burndown, totals, velocity, forecast, capacity (USER_FLOWS §C11)."""

from datetime import date, timedelta

from app.services.alerts import AlertSprintTask, compute_alerts
from app.services.sprints import (
    AvailabilityWindow,
    CapacitySpan,
    SprintItem,
    VelocityPoint,
    capacity_person_days,
    effective_unit,
    estimate_of,
    sprint_burndown,
    sprint_forecast,
    sprint_totals,
    velocity,
)

START = date(2026, 6, 1)  # a Monday
END = START + timedelta(days=13)


def _items() -> list[SprintItem]:
    return [
        SprintItem(1, 5.0, done_on=START + timedelta(days=3)),
        SprintItem(2, 3.0),  # never finished -> carried over
        SprintItem(3, 2.0, added_on=START + timedelta(days=5)),  # scope added
        SprintItem(4, 8.0, removed_on=START + timedelta(days=4)),  # scope removed
        SprintItem(5, 1.0, done_on=START - timedelta(days=1)),  # done before it started
    ]


def test_totals_split_commitment_scope_and_carry_over():
    totals = sprint_totals(START, END, _items())
    assert totals.committed == 17.0  # 5 + 3 + 8 + 1 in the sprint at the start
    assert totals.completed == 6.0  # 5 + 1 done and still in at the end
    assert totals.scope_added == 2.0
    assert totals.scope_removed == 8.0
    assert totals.carried_over == 5.0  # 3 + 2 open at the end


def test_burndown_tracks_remaining_ideal_and_added_scope():
    days = sprint_burndown(START, END, _items(), today=END + timedelta(days=5))
    assert len(days) == 14
    first, last = days[0], days[-1]
    assert first.remaining == 16.0  # 5 + 3 + 8 open (task 5 already done)
    assert first.ideal == 17.0 and last.ideal == 0.0
    assert days[3].remaining == 11.0  # task 1 done on day 3
    assert days[4].remaining == 3.0  # task 4 removed on day 4
    assert days[5].scope_added == 2.0 and days[5].remaining == 5.0
    assert last.remaining == 5.0


def test_burndown_stops_today_for_a_running_sprint():
    days = sprint_burndown(START, END, _items(), today=START + timedelta(days=2))
    assert [d.day for d in days][-1] == START + timedelta(days=2)


def test_units_and_estimates():
    assert estimate_of("points", 5.0, 3) == 5.0
    assert estimate_of("points", None, 3) == 0.0
    assert estimate_of("days", None, 3) == 3.0
    assert estimate_of("count", 8.0, 3) == 1.0
    assert effective_unit("points", [None, None]) == "count"  # nobody estimated yet
    assert effective_unit("points", [None, 3.0]) == "points"
    assert effective_unit("days", [None]) == "days"


def test_velocity_needs_three_sprints_and_uses_the_last_six():
    pts = [
        VelocityPoint(i, f"S{i}", START + timedelta(days=14 * i), 20.0, float(10 + i))
        for i in range(8)
    ]
    v = velocity(pts)
    assert v.sufficient is True
    assert v.mean == round(sum(10 + i for i in range(2, 8)) / 6, 2)
    assert (v.low, v.high) == (12.0, 17.0)
    assert pts[0].reliability == 0.5
    thin = velocity(pts[:2])
    assert thin.sufficient is False and "3 completed sprints" in (thin.reason or "")
    assert VelocityPoint(1, "S", None, 0.0, 3.0).reliability is None


def test_sprint_forecast():
    anchor = date(2026, 7, 1)
    done = sprint_forecast(0, [5.0, 6.0, 7.0], 14, anchor)
    assert done.p50_sprints == 0 and done.p50_date == anchor
    thin = sprint_forecast(30, [5.0], 14, anchor)
    assert thin.sufficient is False
    f = sprint_forecast(30, [10.0, 10.0, 10.0], 14, anchor)
    assert f.sufficient and f.p50_sprints == 3 and f.p85_sprints == 3
    assert f.p50_date == anchor + timedelta(days=42)


def test_capacity_counts_weekdays_allocation_and_availability():
    per = capacity_person_days(
        START,
        END,
        [CapacitySpan(1, 100.0, None, None), CapacitySpan(2, 50.0, START, START + timedelta(4))],
        [AvailabilityWindow(1, 0.0, START + timedelta(days=7), START + timedelta(days=11))],
    )
    assert per[1] == 5.0  # 10 weekdays, out the whole second week
    assert per[2] == 2.5  # half-time for the first five weekdays


def test_sprint_overrun_alert():
    alerts = compute_alerts(
        END,
        [],
        [],
        [],
        sprint_tasks=[
            AlertSprintTask(1, "Late", END + timedelta(days=2), "Sprint 4", END),
            AlertSprintTask(2, "On time", END, "Sprint 4", END),
        ],
    )
    kinds = [(a.kind, a.entity_id) for a in alerts]
    assert ("sprint_overrun", 1) in kinds and ("sprint_overrun", 2) not in kinds
