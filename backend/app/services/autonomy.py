"""Graduated autonomy — docs/AGENT_EXECUTION.md §21 Phase 4 (pure).

A team relaxes its checkpoints for change classes that have earned it: people keep a list of
**pre-approved** classes (`tag:<tag>`) on a column's plan / hand-off checkpoint, and canopy
suggests additions and removals from the evidence — how often plans of that class were approved
as written, how fast, whether their reviews passed first time, and whether any of their work
came back or parked. The data suggests; a person decides (the apply endpoint is human-only), and
the safety floor (one-way doors, high-criticality components, unsettled decisions, low
confidence) is never pre-approved.

Everything here is pure: the service loads facts, this module counts and recommends.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from statistics import median

APPROVED_AS_WRITTEN = "approve"
APPROVED_WITH_CHANGES = frozenset({"approve_with_conditions", "edit_and_approve"})
SENT_BACK = frozenset({"request_changes", "reject"})
PASSING = frozenset({"pass", "concerns"})

MIN_GATES = 8  # decided checkpoint gates of the class before suggesting a pre-approval
MIN_REVIEWS = 5  # first reviews of the class
APPROVE_RATE = 0.95
FIRST_PASS_RATE = 0.85
REVOKE_FIRST_PASS = 0.7


@dataclass
class TaskRow:
    task_id: int
    tags: Sequence[str]
    rework_rounds: int = 0  # times it went back for rework
    parked: bool = False


@dataclass
class GateRow:
    task_id: int
    kind: str  # plan_approval | handoff_approval
    decision: str | None
    created_at: datetime
    decided_at: datetime | None = None


@dataclass
class ReviewRow:
    task_id: int
    verdict: str | None
    created_at: datetime


@dataclass
class AutonomyFacts:
    tasks: Sequence[TaskRow] = ()
    gates: Sequence[GateRow] = ()
    reviews: Sequence[ReviewRow] = ()
    pre_approved: dict[str, Sequence[str]] = field(default_factory=dict)  # checkpoint → classes
    checkpoints: Sequence[str] = ("plan",)  # checkpoints the stage has
    keep_for_people: frozenset[str] = frozenset()  # tags never suggested (security, …)


@dataclass
class ClassStats:
    change_class: str
    tasks: int = 0
    gates: dict[str, int] = field(default_factory=dict)  # kind → decided
    approved_as_written: dict[str, int] = field(default_factory=dict)
    sent_back: dict[str, int] = field(default_factory=dict)
    decision_hours: dict[str, list[float]] = field(default_factory=dict)
    reviews: int = 0
    first_pass: int = 0
    rework_tasks: int = 0
    parked: int = 0

    def approval_rate(self, kind: str) -> float | None:
        decided = self.gates.get(kind, 0)
        return self.approved_as_written.get(kind, 0) / decided if decided else None

    def median_hours(self, kind: str) -> float | None:
        values = self.decision_hours.get(kind) or []
        return round(median(values), 1) if values else None

    @property
    def first_pass_rate(self) -> float | None:
        return self.first_pass / self.reviews if self.reviews else None


@dataclass
class Suggestion:
    action: str  # pre_approve | revoke
    checkpoint: str  # plan | handoff
    change_class: str
    reason: str
    stats: ClassStats


KIND_OF = {"plan": "plan_approval", "handoff": "handoff_approval"}


def _classes(tags: Iterable[str]) -> list[str]:
    return sorted({f"tag:{t.strip().lower()}" for t in tags if t and t.strip()})


def class_stats(facts: AutonomyFacts) -> dict[str, ClassStats]:
    """Per change class: checkpoint decisions, first reviews, rework and parking of its tasks."""
    stats: dict[str, ClassStats] = {}
    by_task: dict[int, list[str]] = {}
    for task in facts.tasks:
        classes = _classes(task.tags)
        by_task[task.task_id] = classes
        for cls in classes:
            row = stats.setdefault(cls, ClassStats(cls))
            row.tasks += 1
            row.rework_tasks += 1 if task.rework_rounds else 0
            row.parked += 1 if task.parked else 0
    for gate in facts.gates:
        if gate.decision is None:
            continue
        for cls in by_task.get(gate.task_id, []):
            row = stats[cls]
            row.gates[gate.kind] = row.gates.get(gate.kind, 0) + 1
            if gate.decision == APPROVED_AS_WRITTEN:
                row.approved_as_written[gate.kind] = row.approved_as_written.get(gate.kind, 0) + 1
            if gate.decision in SENT_BACK:
                row.sent_back[gate.kind] = row.sent_back.get(gate.kind, 0) + 1
            if gate.decided_at is not None:
                hours = max(0.0, (gate.decided_at - gate.created_at).total_seconds() / 3600)
                row.decision_hours.setdefault(gate.kind, []).append(hours)
    first_reviews: dict[int, ReviewRow] = {}
    for review in sorted(facts.reviews, key=lambda r: r.created_at):
        first_reviews.setdefault(review.task_id, review)
    for task_id, review in first_reviews.items():
        for cls in by_task.get(task_id, []):
            row = stats[cls]
            row.reviews += 1
            row.first_pass += 1 if (review.verdict or "") in PASSING else 0
    return stats


def suggestions(facts: AutonomyFacts) -> list[Suggestion]:
    """What the evidence says people could pre-approve — or should stop pre-approving."""
    out: list[Suggestion] = []
    stats = class_stats(facts)
    for cls, row in sorted(stats.items()):
        tag = cls.partition(":")[2]
        for checkpoint in facts.checkpoints:
            kind = KIND_OF.get(checkpoint)
            if kind is None:
                continue
            already = cls in (facts.pre_approved.get(checkpoint) or ())
            if already:
                fp = row.first_pass_rate
                if row.parked or row.rework_tasks >= 2 or (
                    row.reviews >= 3 and fp is not None and fp < REVOKE_FIRST_PASS
                ):
                    problems = []
                    if row.parked:
                        problems.append(f"{row.parked} parked")
                    if row.rework_tasks:
                        problems.append(f"{row.rework_tasks} sent back for rework")
                    if fp is not None:
                        problems.append(f"first reviews passed {round(fp * 100)}%")
                    out.append(Suggestion(
                        "revoke", checkpoint, cls,
                        f"Pre-approved {cls} work is coming back: " + ", ".join(problems)
                        + f" — ask a person again at the {checkpoint} checkpoint.", row))
                continue
            if tag in facts.keep_for_people:
                continue
            decided = row.gates.get(kind, 0)
            rate = row.approval_rate(kind)
            fp = row.first_pass_rate
            if (decided >= MIN_GATES and rate is not None and rate >= APPROVE_RATE
                    and not row.sent_back.get(kind) and row.reviews >= MIN_REVIEWS
                    and fp is not None and fp >= FIRST_PASS_RATE and not row.parked):
                hours = row.median_hours(kind)
                out.append(Suggestion(
                    "pre_approve", checkpoint, cls,
                    f"{decided} {checkpoint} approvals of {cls} work: "
                    f"{round(rate * 100)}% approved as written"
                    + (f" in a median {hours} h" if hours is not None else "")
                    + f", first reviews passed {round(fp * 100)}%. A person reviewing these "
                    "isn't changing the outcome — the safety floor still applies.", row))
    return out
