"""Project alerts / digest (pure, unit-testable).

Turns the current project state into a list of actionable alerts: deadline misses,
overdue milestones, over-allocations, and unscheduled work. The endpoint adapts ORM
rows into these lightweight dataclasses; delivery (Slack/email) is a future hook.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass
class AlertTask:
    id: int
    name: str
    is_summary: bool
    end: date | None
    deadline: date | None


@dataclass
class AlertMilestone:
    id: int
    name: str
    target_date: date | None
    status: str


@dataclass
class OverAllocation:
    engineer_name: str
    week: str
    percent: float


@dataclass
class AlertBlocker:
    task_id: int
    task_name: str
    reason: str


@dataclass
class Alert:
    kind: str
    severity: str  # info | warning | error
    message: str
    entity_type: str | None = None
    entity_id: int | None = None


def compute_alerts(
    today: date,
    tasks: list[AlertTask],
    milestones: list[AlertMilestone],
    over_allocations: list[OverAllocation],
    blockers: list[AlertBlocker] | None = None,
) -> list[Alert]:
    alerts: list[Alert] = []

    for blocker in blockers or []:
        alerts.append(
            Alert(
                kind="blocked",
                severity="warning",
                message=f"'{blocker.task_name}' is blocked: {blocker.reason}",
                entity_type="task",
                entity_id=blocker.task_id,
            )
        )

    for task in tasks:
        if task.deadline and task.end and task.end > task.deadline:
            alerts.append(
                Alert(
                    kind="deadline_miss",
                    severity="error",
                    message=f"'{task.name}' ends {task.end} — past its deadline {task.deadline}",
                    entity_type="task",
                    entity_id=task.id,
                )
            )
        elif not task.is_summary and task.end is None:
            alerts.append(
                Alert(
                    kind="unscheduled",
                    severity="info",
                    message=f"'{task.name}' is unscheduled",
                    entity_type="task",
                    entity_id=task.id,
                )
            )

    for milestone in milestones:
        if (
            milestone.target_date
            and milestone.target_date < today
            and milestone.status.lower() not in {"hit", "done"}
        ):
            alerts.append(
                Alert(
                    kind="milestone_overdue",
                    severity="warning",
                    message=f"Milestone '{milestone.name}' was due {milestone.target_date}",
                    entity_type="milestone",
                    entity_id=milestone.id,
                )
            )

    for over in over_allocations:
        alerts.append(
            Alert(
                kind="over_allocation",
                severity="warning",
                message=(
                    f"{over.engineer_name} is allocated {over.percent:.0f}% "
                    f"in week of {over.week}"
                ),
            )
        )

    return alerts
