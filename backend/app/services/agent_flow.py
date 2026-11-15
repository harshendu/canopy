"""Agent-flow metrics (pure) — docs/AGENT_EXECUTION.md §19.

How the agent work queue is flowing, for a project, an initiative or a team: what waits on
agents and what waits on people, how long people take to decide, how often plans and hand-offs
pass first time, how much rework there is, how sessions end, how much of the elapsed time a task
was actually being worked, the review load each kind of gate creates, how much work reached done
with no person stepping in, and — where runners report it — the cost per finished task.

**Team-level by design**: by role, stage, gate kind and project — never by engineer, never by the
person whose token an agent used, never by token (P10). Thin data reports `sufficient: false`
with a reason rather than a number that means nothing.

The database side (`load_facts` in `agent_flow_service.py`) adapts rows into the dataclasses
below; everything here is arithmetic over them.
"""

from __future__ import annotations

import statistics
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

APPROVAL_KINDS = frozenset({"plan_approval", "handoff_approval", "signoff"})
ASSISTED_KINDS = frozenset({"plan_approval", "handoff_approval", "question", "escalation"})
MIN_FINISHED_CLAIMS = 5  # below this, outcome shares and efficiency mean little


@dataclass
class ClaimRow:
    task_id: int
    role: str
    outcome: str | None
    claimed_at: datetime
    finished_at: datetime | None
    cost_usd: float | None = None


@dataclass
class GateRow:
    task_id: int
    kind: str
    origin: str
    status: str
    decision: str | None
    created_at: datetime
    decided_at: datetime | None
    reasons: Sequence[str] = ()
    remind_at: datetime | None = None
    escalate_at: datetime | None = None
    escalation_level: int = 0


@dataclass
class VerdictRow:
    task_id: int
    kind: str  # review | qa_report
    verdict: str | None
    created_at: datetime


@dataclass
class TaskRow:
    task_id: int
    done_at: datetime | None  # reached done within the window (None = not done there)
    returned: int = 0  # times sent back for rework (all time)


@dataclass
class ReadyRow:
    task_id: int
    role: str
    ready_hours: float


@dataclass
class AgentFlowFacts:
    claims: Sequence[ClaimRow] = ()
    gates: Sequence[GateRow] = ()
    verdicts: Sequence[VerdictRow] = ()
    tasks: Sequence[TaskRow] = ()
    ready: Sequence[ReadyRow] = ()
    held: dict[str, int] = field(default_factory=dict)  # open gates by kind ("parked" apart)
    parked: int = 0


def _hours(delta: timedelta) -> float:
    return max(0.0, delta.total_seconds() / 3600)


def p85(values: Sequence[float]) -> float | None:
    """Nearest-rank 85th percentile."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, -(-85 * len(ordered) // 100))  # ceil(0.85 n)
    return round(ordered[rank - 1], 1)


def _median(values: Sequence[float]) -> float | None:
    return round(statistics.median(values), 1) if values else None


def _share(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 2) if denominator else None


def _first_pass(rows: Iterable[tuple[int, str, bool]]) -> float | None:
    """Share of (task, kind) pairs whose first outcome was a pass."""
    first: dict[tuple[int, str], bool] = {}
    for task_id, kind, passed in rows:
        first.setdefault((task_id, kind), passed)
    return _share(sum(first.values()), len(first))


def compute(facts: AgentFlowFacts, *, now: datetime, since: datetime) -> dict[str, Any]:
    """The §19 measures over the window [since, now]."""
    finished = [c for c in facts.claims if c.finished_at is not None and c.finished_at >= since]
    done_tasks = [t for t in facts.tasks if t.done_at is not None and since <= t.done_at <= now]
    weeks = max(1.0, (now - since).days / 7)

    # Human wait: opened → decided, by kind; and what's still waiting past its thresholds.
    decided = [g for g in facts.gates if g.decided_at is not None and g.decided_at >= since]
    by_kind: dict[str, list[float]] = {}
    for g in decided:
        assert g.decided_at is not None
        by_kind.setdefault(g.kind, []).append(_hours(g.decided_at - g.created_at))
    open_gates = [g for g in facts.gates if g.status == "open"]
    past_reminder = sum(1 for g in open_gates if g.remind_at is not None and g.remind_at <= now)
    past_escalation = sum(
        1 for g in open_gates
        if g.escalation_level > 0 or (g.escalate_at is not None and g.escalate_at <= now)
    )

    # First pass: approvals (in time order) and review / QA verdicts.
    approvals = sorted(
        (g for g in decided if g.kind in APPROVAL_KINDS and g.decision not in (None, "cancelled",
                                                                               "take_over")),
        key=lambda g: g.created_at,
    )
    first_pass_approvals = _first_pass(
        (g.task_id, g.kind, g.status == "approved") for g in approvals
    )
    verdicts = sorted((v for v in facts.verdicts if v.created_at >= since),
                      key=lambda v: v.created_at)
    first_pass_reviews = _first_pass(
        (v.task_id, v.kind, v.verdict in ("pass", "concerns")) for v in verdicts
    )

    # Rework, claim outcomes, attempts.
    worked = {c.task_id for c in facts.claims if c.claimed_at >= since}
    reworked_tasks = [t for t in facts.tasks if t.task_id in worked]
    returned = [t for t in reworked_tasks if t.returned > 0]
    outcomes = Counter(c.outcome or "unknown" for c in finished)
    attempts = Counter(c.task_id for c in facts.claims if c.claimed_at >= since)

    # Flow efficiency: time under a claim ÷ first claim → done, over tasks done in the window.
    active: list[float] = []
    elapsed: list[float] = []
    for t in done_tasks:
        assert t.done_at is not None
        mine = [c for c in facts.claims if c.task_id == t.task_id]
        if not mine:
            continue
        start = min(c.claimed_at for c in mine)
        elapsed.append(_hours(t.done_at - start))
        active.append(sum(_hours((c.finished_at or t.done_at) - c.claimed_at) for c in mine))
    efficiency = round(min(1.0, sum(active) / sum(elapsed)), 2) if sum(elapsed) > 0 else None

    # Gate load, and each gate kind as an experiment.
    opened = [g for g in facts.gates if g.created_at >= since]
    reasons = Counter(r for g in opened for r in g.reasons)
    experiments = []
    for kind in sorted({g.kind for g in decided}):
        rows = [g for g in decided if g.kind == kind]
        experiments.append({
            "kind": kind,
            "decided": len(rows),
            "approval_rate": _share(sum(1 for g in rows if g.status in ("approved", "answered")),
                                    len(rows)),
            "median_hours": _median(by_kind.get(kind, [])),
        })

    # Unassisted: agent-worked tasks done with no gate but sign-off.
    assisted = {g.task_id for g in facts.gates if g.kind in ASSISTED_KINDS}
    agent_done = [t for t in done_tasks if any(c.task_id == t.task_id for c in facts.claims)]
    unassisted = _share(sum(1 for t in agent_done if t.task_id not in assisted), len(agent_done))

    # Cost per finished task, where runners report it.
    costs = [c.cost_usd for c in facts.claims
             if c.cost_usd is not None and any(t.task_id == c.task_id for t in agent_done)]
    cost_per_task = round(sum(costs) / len(agent_done), 2) if costs and agent_done else None

    ready_by_role: dict[str, int] = dict(Counter(r.role for r in facts.ready))
    oldest = max((r.ready_hours for r in facts.ready), default=None)

    sufficient = len(finished) >= MIN_FINISHED_CLAIMS
    return {
        "sufficient": sufficient,
        "reason": None if sufficient else (
            f"Only {len(finished)} agent session(s) finished in the window — rates need at "
            f"least {MIN_FINISHED_CLAIMS}"),
        "queue": {
            "ready_by_role": ready_by_role,
            "oldest_ready_hours": round(oldest, 1) if oldest is not None else None,
            "held_by_kind": dict(facts.held),
            "parked": facts.parked,
        },
        "human_wait": {
            "by_kind": {k: {"decided": len(v), "median_hours": _median(v), "p85_hours": p85(v)}
                        for k, v in sorted(by_kind.items())},
            "open": len(open_gates),
            "open_past_reminder": past_reminder,
            "open_past_escalation": past_escalation,
        },
        "first_pass": {"approvals": first_pass_approvals, "reviews": first_pass_reviews},
        "rework": {
            "tasks_returned_share": _share(len(returned), len(reworked_tasks)),
            "rounds_per_returned_task": round(sum(t.returned for t in returned) / len(returned), 1)
            if returned else None,
        },
        "claims": {
            "finished": len(finished),
            "by_outcome": dict(sorted(outcomes.items())),
            "attempts_per_task": round(sum(attempts.values()) / len(attempts), 1)
            if attempts else None,
        },
        "flow_efficiency": efficiency,
        "gate_load": {
            "opened": len(opened),
            "per_week": round(len(opened) / weeks, 1),
            "by_kind": dict(sorted(Counter(g.kind for g in opened).items())),
            "top_reasons": [{"reason": r, "count": n} for r, n in reasons.most_common(5)],
        },
        "gates_as_experiments": experiments,
        "unassisted_share": unassisted,
        "agent_tasks_done": len(agent_done),
        "cost_per_task_usd": cost_per_task,
    }
