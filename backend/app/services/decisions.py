"""Decision-centric helpers (pure, unit-testable).

The architect's unit of work is the *decision*, so the rules around an ADR's lifecycle
live here, independent of the ORM and the request cycle:

  * ``valid_transition`` — the allowed ADR status lifecycle, so the API can reject
    nonsensical jumps (e.g. ``deprecated -> proposed``).
  * ``review_summary`` — fold each stakeholder's latest review action into an approval
    state under a project's decision rule (owner-decides / consensus / lazy-consensus).
  * ``build_decision_queue`` — turn a set of ADRs into the architect's morning queue:
    what needs triage, what's mid-discussion, what's stuck, and which deferred decisions
    are coming due.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from app.models.base import ADRCommentKind, ADRStatus, DecisionRule

# --- Lifecycle ---------------------------------------------------------------

_TRANSITIONS: dict[ADRStatus, set[ADRStatus]] = {
    ADRStatus.proposed: {
        ADRStatus.under_discussion,
        ADRStatus.deferred,
        ADRStatus.accepted,
        ADRStatus.rejected,
    },
    ADRStatus.under_discussion: {
        ADRStatus.accepted,
        ADRStatus.rejected,
        ADRStatus.deferred,
        ADRStatus.proposed,
    },
    ADRStatus.deferred: {
        ADRStatus.under_discussion,
        ADRStatus.proposed,
        ADRStatus.accepted,
        ADRStatus.rejected,
    },
    ADRStatus.accepted: {ADRStatus.superseded, ADRStatus.deprecated},
    ADRStatus.rejected: {ADRStatus.proposed, ADRStatus.under_discussion},
    ADRStatus.superseded: {ADRStatus.deprecated},
    ADRStatus.deprecated: set(),
}


def valid_transition(old: ADRStatus, new: ADRStatus) -> bool:
    """Whether an ADR may move from ``old`` to ``new``. A no-op (old == new) is allowed."""
    if old == new:
        return True
    return new in _TRANSITIONS.get(old, set())


# --- Reviews -----------------------------------------------------------------

_REVIEW_ACTIONS = {
    ADRCommentKind.approve,
    ADRCommentKind.request_changes,
    ADRCommentKind.reject,
}


@dataclass
class ReviewSummary:
    required: int
    approved: int
    changes_requested: int
    rejected: int
    pending: int
    can_accept: bool


def review_summary(
    stakeholder_ids: list[int],
    latest_by_engineer: dict[int, ADRCommentKind],
    rule: DecisionRule,
) -> ReviewSummary:
    """Summarise stakeholder reviews under a project's decision rule.

    ``latest_by_engineer`` is each engineer's most recent *review action* (plain
    comments don't count). Only stakeholders' actions affect the summary. ``can_accept``
    is advisory — it reports whether the rule is satisfied; the API surfaces it rather
    than hard-blocking an owner who chooses to decide anyway.
    """
    required = len(stakeholder_ids)
    approved = changes_requested = rejected = 0
    for sid in stakeholder_ids:
        action = latest_by_engineer.get(sid)
        if action == ADRCommentKind.approve:
            approved += 1
        elif action == ADRCommentKind.request_changes:
            changes_requested += 1
        elif action == ADRCommentKind.reject:
            rejected += 1
    pending = required - approved - changes_requested - rejected

    if rule == DecisionRule.consensus:
        can_accept = required > 0 and approved == required
    elif rule == DecisionRule.lazy_consensus:
        can_accept = changes_requested == 0 and rejected == 0
    else:  # owner_decides — the owner's call, reviews are advisory
        can_accept = True

    return ReviewSummary(
        required=required,
        approved=approved,
        changes_requested=changes_requested,
        rejected=rejected,
        pending=pending,
        can_accept=can_accept,
    )


# --- Decision queue ----------------------------------------------------------

# Mutually-exclusive buckets, in triage priority order.
BUCKET_PRIORITY = ["needs_triage", "stuck", "deferred_soon", "discussing"]


@dataclass
class DecisionQueueInput:
    id: int
    project_id: int
    number: int
    title: str
    status: ADRStatus
    created_at: datetime
    decide_by: date | None
    sla_hours: int


@dataclass
class QueueItem:
    id: int
    project_id: int
    number: int
    title: str
    status: ADRStatus
    bucket: str
    reason: str
    overdue: bool
    decide_by: date | None
    age_hours: float


def _to_naive_utc(value: datetime) -> datetime:
    """Drop tzinfo (converting to UTC first) so DB-loaded naive datetimes compare
    cleanly against an aware ``now``."""
    if value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


def build_decision_queue(
    items: list[DecisionQueueInput],
    now: datetime,
    *,
    stuck_after_days: int = 14,
    deferred_window_days: int = 14,
) -> list[QueueItem]:
    """The decision queue: ADRs needing attention, most urgent first.

    Buckets (mutually exclusive):
      * ``needs_triage``  — ``proposed`` ADRs awaiting the owner (overdue past the SLA).
      * ``stuck``         — ``under_discussion`` longer than ``stuck_after_days``.
      * ``discussing``    — ``under_discussion`` within the window.
      * ``deferred_soon`` — ``deferred`` ADRs whose ``decide_by`` is within the window
        (or already past). Deferred ADRs with a comfortably distant date are omitted.
    Decided/rejected/superseded/deprecated ADRs are not in the queue.
    """
    now_naive = _to_naive_utc(now)
    today = now_naive.date()
    out: list[QueueItem] = []

    for it in items:
        age_hours = (now_naive - _to_naive_utc(it.created_at)).total_seconds() / 3600.0
        bucket: str | None = None
        reason = ""
        overdue = False

        if it.status == ADRStatus.proposed:
            bucket = "needs_triage"
            overdue = age_hours > it.sla_hours
            reason = (
                f"Awaiting triage — {age_hours:.0f}h old, past the {it.sla_hours}h SLA"
                if overdue
                else f"Awaiting triage (owner SLA {it.sla_hours}h)"
            )
        elif it.status == ADRStatus.under_discussion:
            if age_hours > stuck_after_days * 24:
                bucket = "stuck"
                overdue = True
                reason = f"Under discussion for {age_hours / 24:.0f} days (> {stuck_after_days}d)"
            else:
                bucket = "discussing"
                reason = "Open for discussion"
        elif it.status == ADRStatus.deferred:
            if it.decide_by is None:
                bucket = "deferred_soon"
                overdue = True
                reason = "Deferred without a decide-by date"
            elif it.decide_by <= today + timedelta(days=deferred_window_days):
                bucket = "deferred_soon"
                overdue = it.decide_by < today
                reason = (
                    f"Decide-by {it.decide_by} has passed"
                    if overdue
                    else f"Decide-by {it.decide_by} is approaching"
                )

        if bucket is not None:
            out.append(
                QueueItem(
                    id=it.id,
                    project_id=it.project_id,
                    number=it.number,
                    title=it.title,
                    status=it.status,
                    bucket=bucket,
                    reason=reason,
                    overdue=overdue,
                    decide_by=it.decide_by,
                    age_hours=age_hours,
                )
            )

    out.sort(
        key=lambda q: (
            not q.overdue,
            BUCKET_PRIORITY.index(q.bucket),
            -q.age_hours,
        )
    )
    return out
