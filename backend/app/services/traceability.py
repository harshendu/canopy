"""The decision-to-code traceability ledger — PROPOSED_FLOWS §T, AGENT_EXECUTION.md §21
Phase 4 (pure).

"For decision X, what implemented it, and is it still honored?" — joining a decision to the
tasks that implement it (`Task.implements_adr_id`) or touch what it governs (its components),
their pull requests and the reviews that checked them against it, its fitness functions and the
drift the scan found. The verdict is computed from those facts, never stored.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

RETIRED = frozenset({"superseded", "deprecated", "rejected"})


@dataclass
class TaskFact:
    task_id: int
    key: str | None
    name: str
    status: str | None
    done: bool
    implements: bool  # the task says it implements this decision
    governed: bool  # it touches a component the decision governs


@dataclass
class PrFact:
    task_id: int | None
    repo: str
    number: int
    url: str | None
    state: str
    merged: bool
    checks_state: str | None = None
    review_decision: str | None = None


@dataclass
class ReviewFact:
    task_id: int
    artifact_id: int
    verdict: str | None
    checked: bool  # the review says it checked the work against this decision


@dataclass
class FitnessFact:
    fitness_id: int
    kind: str  # forbid | require
    source: str
    target: str
    description: str | None
    violated: bool


@dataclass
class DriftFact:
    drift_id: int
    kind: str
    summary: str


@dataclass
class DecisionFacts:
    adr_id: int
    number: int
    title: str
    status: str
    reversibility: str | None
    components: Sequence[str] = ()
    tasks: Sequence[TaskFact] = ()
    prs: Sequence[PrFact] = ()
    reviews: Sequence[ReviewFact] = ()
    fitness: Sequence[FitnessFact] = ()
    drift: Sequence[DriftFact] = field(default_factory=list)  # open drift that concerns it


def verdict(f: DecisionFacts) -> tuple[str, str]:
    """(verdict, why): retired · pending · violated · unimplemented · at_risk · no_linked_work ·
    in_progress · honored — the first that holds, worst first."""
    if f.status in RETIRED:
        return "retired", f"The decision is {f.status}."
    if f.status != "accepted":
        return "pending", f"The decision is {f.status.replace('_', ' ')} — not binding yet."
    broken = [x for x in f.fitness if x.violated]
    if broken:
        rules = "; ".join(f"{x.source} must {'not ' if x.kind == 'forbid' else ''}depend on "
                          f"{x.target}" for x in broken)
        return "violated", f"A fitness rule is broken: {rules}."
    if any(d.kind == "unimplemented_adr" for d in f.drift):
        return "unimplemented", "The drift scan finds no code that implements it."
    others = [d for d in f.drift if d.kind != "unimplemented_adr"]
    if others:
        return "at_risk", f"{len(others)} open drift event(s) on what it governs."
    implementing = [t for t in f.tasks if t.implements]
    if not f.tasks:
        return "no_linked_work", "No task implements it or touches what it governs yet."
    if implementing and not all(t.done for t in implementing):
        left = sum(1 for t in implementing if not t.done)
        return "in_progress", f"{left} implementing task(s) still open."
    failed = [r for r in f.reviews if r.checked and r.verdict == "fail"]
    if failed and not any(r.checked and r.verdict in ("pass", "concerns") for r in f.reviews):
        return "at_risk", "Reviews that checked the work against it failed."
    if implementing:
        return "honored", "Its implementing work is done, its fitness rules hold and no drift " \
            "is open."
    return "honored", "The work that touches what it governs shows no broken rule, failed " \
        "review or open drift."


def summary(f: DecisionFacts) -> dict[str, object]:
    """One ledger row."""
    code, why = verdict(f)
    return {
        "adr_id": f.adr_id, "number": f.number, "title": f.title, "status": f.status,
        "verdict": code, "reason": why,
        "tasks": len(f.tasks), "implementing": sum(1 for t in f.tasks if t.implements),
        "done": sum(1 for t in f.tasks if t.done),
        "prs": len(f.prs), "merged": sum(1 for p in f.prs if p.merged),
        "fitness": len(f.fitness), "violated": sum(1 for x in f.fitness if x.violated),
        "reviews_checked": sum(1 for r in f.reviews if r.checked),
        "open_drift": len(f.drift),
    }
