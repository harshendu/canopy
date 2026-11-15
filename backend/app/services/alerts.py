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
    severity: str | None = None  # low | medium | high | critical
    needed_by: date | None = None


@dataclass
class AlertRiskItem:
    """An open register risk (RAID), for the overdue-resolution alert. Kept out of the
    computed risk score — this only surfaces in the actionable digest."""

    id: int
    title: str
    exposure: int  # 1..9
    target_resolution_date: date | None


@dataclass
class AlertSprintTask:
    """An open task in an active sprint, with the sprint's end — for the overrun alert."""

    task_id: int
    name: str
    end: date | None  # the task's computed (CPM) end
    sprint_name: str
    sprint_end: date | None


@dataclass
class AlertGate:
    """An open gate — agent work waiting on a person (docs/AGENT_EXECUTION.md §9.4, §19)."""

    id: int
    task_id: int
    task_name: str
    kind: str
    title: str
    age_hours: float
    parked: bool = False  # canopy stopped offering the task (attempts used up, rework loop)
    remind_after_hours: float | None = None
    escalate_after_hours: float | None = None


@dataclass
class AlertClaim:
    """An active work claim — a session working a task (docs/AGENT_EXECUTION.md §6.3, §19)."""

    id: int
    task_id: int
    task_name: str
    role: str
    lease_minutes: int
    heartbeat_age_minutes: float
    active_hours: float


@dataclass
class Alert:
    kind: str
    severity: str  # info | warning | error
    message: str
    entity_type: str | None = None
    entity_id: int | None = None


# Blocker severities that escalate the alert from a warning to an error.
_ERROR_BLOCKER_SEVERITIES = {"high", "critical"}


def compute_alerts(
    today: date,
    tasks: list[AlertTask],
    milestones: list[AlertMilestone],
    over_allocations: list[OverAllocation],
    blockers: list[AlertBlocker] | None = None,
    register_risks: list[AlertRiskItem] | None = None,
    sprint_tasks: list[AlertSprintTask] | None = None,
    gates: list[AlertGate] | None = None,
    claims: list[AlertClaim] | None = None,
    claim_overrun_hours: float = 8,
) -> list[Alert]:
    alerts: list[Alert] = []
    alerts.extend(agent_work_alerts(gates or [], claims or [], claim_overrun_hours))

    # Sprints never pin the schedule (CPM dates stay computed): surface the conflict instead.
    for st in sprint_tasks or []:
        if st.end is not None and st.sprint_end is not None and st.end > st.sprint_end:
            alerts.append(
                Alert(
                    kind="sprint_overrun",
                    severity="warning",
                    message=(
                        f"'{st.name}' is scheduled to finish {st.end}, after "
                        f"{st.sprint_name} ends ({st.sprint_end})"
                    ),
                    entity_type="task",
                    entity_id=st.task_id,
                )
            )

    for blocker in blockers or []:
        severity = "error" if blocker.severity in _ERROR_BLOCKER_SEVERITIES else "warning"
        message = f"'{blocker.task_name}' is blocked: {blocker.reason}"
        if blocker.needed_by is not None:
            message += f" (needed by {blocker.needed_by})"
        alerts.append(
            Alert(
                kind="blocked",
                severity=severity,
                message=message,
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

    for risk in register_risks or []:
        if risk.target_resolution_date is not None and risk.target_resolution_date < today:
            alerts.append(
                Alert(
                    kind="risk_overdue",
                    # high-exposure (>=6 of 9) overdue risks are errors, the rest warnings
                    severity="error" if risk.exposure >= 6 else "warning",
                    message=(
                        f"Risk '{risk.title}' was due to be resolved by "
                        f"{risk.target_resolution_date}"
                    ),
                    entity_type="risk",
                    entity_id=risk.id,
                )
            )

    return alerts


def agent_work_alerts(
    gates: list[AlertGate], claims: list[AlertClaim], claim_overrun_hours: float = 8
) -> list[Alert]:
    """Agent work that needs a person (§19): a parked task, a gate waiting past its reminder
    (warning) or escalation threshold (error), a session that stopped checking in, a claim
    that has run for too long."""
    alerts: list[Alert] = []
    for gate in gates:
        if gate.parked:
            alerts.append(
                Alert(
                    kind="task_parked",
                    severity="error",
                    message=(
                        f"'{gate.task_name}' is parked — {gate.title}. Retry it with guidance, "
                        "take it over, or cancel it."
                    ),
                    entity_type="task",
                    entity_id=gate.task_id,
                )
            )
            continue
        past_escalation = (
            gate.escalate_after_hours is not None and gate.age_hours >= gate.escalate_after_hours
        )
        past_reminder = (
            gate.remind_after_hours is not None and gate.age_hours >= gate.remind_after_hours
        )
        if past_escalation or past_reminder:
            alerts.append(
                Alert(
                    kind="gate_waiting",
                    severity="error" if past_escalation else "warning",
                    message=(
                        f"'{gate.task_name}' has waited {gate.age_hours:.0f} h for a person "
                        f"({gate.kind.replace('_', ' ')}): {gate.title}"
                    ),
                    entity_type="gate",
                    entity_id=gate.id,
                )
            )
    for claim in claims:
        if claim.heartbeat_age_minutes > claim.lease_minutes / 2:
            alerts.append(
                Alert(
                    kind="claim_stale",
                    severity="warning",
                    message=(
                        f"The {claim.role} session on '{claim.task_name}' last checked in "
                        f"{claim.heartbeat_age_minutes:.0f} min ago (lease {claim.lease_minutes} "
                        "min) — it may have stopped"
                    ),
                    entity_type="task",
                    entity_id=claim.task_id,
                )
            )
        if claim.active_hours > claim_overrun_hours:
            alerts.append(
                Alert(
                    kind="claim_overrun",
                    severity="warning",
                    message=(
                        f"The {claim.role} session on '{claim.task_name}' has held it for "
                        f"{claim.active_hours:.0f} h — check it is still making progress"
                    ),
                    entity_type="task",
                    entity_id=claim.task_id,
                )
            )
    return alerts
