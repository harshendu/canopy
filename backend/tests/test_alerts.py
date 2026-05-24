from datetime import date

from app.services.alerts import (
    AlertBlocker,
    AlertMilestone,
    AlertRiskItem,
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


def test_blocker_severity_escalates_to_error_and_notes_needed_by():
    blockers = [
        AlertBlocker(
            1, "Build", "waiting on infra", severity="critical", needed_by=date(2026, 6, 1)
        ),
        AlertBlocker(2, "Docs", "needs review", severity="low"),
    ]
    alerts = compute_alerts(TODAY, [], [], [], blockers)
    by_task = {a.entity_id: a for a in alerts}
    assert by_task[1].severity == "error"
    assert "needed by 2026-06-01" in by_task[1].message
    assert by_task[2].severity == "warning"


def test_blocker_without_severity_defaults_to_warning():
    alerts = compute_alerts(TODAY, [], [], [], [AlertBlocker(1, "Build", "stuck")])
    assert alerts[0].kind == "blocked"
    assert alerts[0].severity == "warning"


def test_overdue_register_risk_alert_only_when_past_target():
    risks = [
        AlertRiskItem(id=1, title="Vendor", exposure=9, target_resolution_date=date(2026, 4, 1)),
        AlertRiskItem(id=2, title="Minor", exposure=2, target_resolution_date=date(2026, 4, 1)),
        AlertRiskItem(id=3, title="Future", exposure=9, target_resolution_date=date(2026, 6, 1)),
        AlertRiskItem(id=4, title="Undated", exposure=9, target_resolution_date=None),
    ]
    alerts = compute_alerts(TODAY, [], [], [], None, risks)
    overdue = {a.entity_id: a for a in alerts if a.kind == "risk_overdue"}
    assert set(overdue) == {1, 2}  # only past-target risks; future / undated excluded
    assert overdue[1].severity == "error"  # high exposure
    assert overdue[2].severity == "warning"  # low exposure
