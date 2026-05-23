from datetime import date

from app.services.alerts import (
    AlertMilestone,
    AlertTask,
    OverAllocation,
    compute_alerts,
)

TODAY = date(2026, 5, 1)


def test_deadline_miss_alert():
    tasks = [AlertTask(1, "Build", False, end=date(2026, 6, 1), deadline=date(2026, 5, 15))]
    alerts = compute_alerts(TODAY, tasks, [], [])
    assert len(alerts) == 1
    assert alerts[0].kind == "deadline_miss"
    assert alerts[0].severity == "error"
    assert alerts[0].entity_id == 1


def test_unscheduled_leaf_alert_but_not_summary():
    tasks = [
        AlertTask(1, "Leaf", False, end=None, deadline=None),
        AlertTask(2, "Phase", True, end=None, deadline=None),
    ]
    alerts = compute_alerts(TODAY, tasks, [], [])
    assert [a.kind for a in alerts] == ["unscheduled"]
    assert alerts[0].entity_id == 1


def test_overdue_milestone_and_hit_excluded():
    milestones = [
        AlertMilestone(1, "Beta", target_date=date(2026, 4, 1), status="planned"),
        AlertMilestone(2, "Alpha", target_date=date(2026, 4, 1), status="hit"),
    ]
    alerts = compute_alerts(TODAY, [], milestones, [])
    assert [a.entity_id for a in alerts] == [1]
    assert alerts[0].kind == "milestone_overdue"


def test_over_allocation_alert():
    alerts = compute_alerts(TODAY, [], [], [OverAllocation("Ada", "2026-05-04", 150.0)])
    assert alerts[0].kind == "over_allocation"
    assert "150%" in alerts[0].message
