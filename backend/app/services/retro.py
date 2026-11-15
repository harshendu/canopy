"""Retrospective generation (pure, unit-testable).

Seeds a project retrospective's body from already-aggregated project state — completed
milestones, schedule variance, open drift, and ADR churn — as markdown. The endpoint
gathers the numbers from the DB; this module just renders them, so it stays pure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class RetroInputs:
    project_name: str
    generated_on: date
    completed_milestones: list[str] = field(default_factory=list)  # "Name (date)"
    total_tasks: int = 0
    completed_tasks: int = 0
    drifted_tasks: int = 0  # tasks whose end moved off baseline (schedule variance)
    open_drift_events: int = 0
    adr_total: int = 0
    adr_accepted: int = 0
    adr_superseded: int = 0
    outcomes: list[str] = field(default_factory=list)  # "statement — current/target unit (status)"
    # Agent work in the retro's window (Phase 4: gate latency, rework, parking — see
    # `agent_work_lines`); empty when no agent worked on the project.
    agent_work: list[str] = field(default_factory=list)
    # design docs that moved on after they were approved: "Title (approved r12, now r14)" (§V9)
    docs_changed_after_approval: list[str] = field(default_factory=list)


_GATE_WORDS = {
    "plan_approval": "plan approvals", "handoff_approval": "hand-off approvals",
    "signoff": "sign-offs", "question": "questions", "escalation": "escalations",
}


def _pct(value: object) -> str:
    return f"{round(float(value) * 100)}%" if isinstance(value, int | float) else "—"


def _hours(value: object) -> str:
    if not isinstance(value, int | float):
        return "—"
    return f"{round(value / 24)} d" if value >= 48 else f"{round(float(value), 1)} h"


def agent_work_lines(flow: dict[str, object], uncleared_moves: int = 0) -> list[str]:
    """The retro's agent-work section from the project's agent-flow numbers (pure): how long
    people took to decide, what came back, what parked, and which gates look like they aren't
    protecting anything. Empty when no session worked on the project."""
    claims = flow.get("claims") if isinstance(flow.get("claims"), dict) else {}
    wait = flow.get("human_wait") if isinstance(flow.get("human_wait"), dict) else {}
    assert isinstance(claims, dict) and isinstance(wait, dict)
    finished = int(claims.get("finished") or 0)
    by_kind = wait.get("by_kind") if isinstance(wait.get("by_kind"), dict) else {}
    assert isinstance(by_kind, dict)
    if not finished and not by_kind:
        return []
    lines = [f"{finished} agent session(s) finished; {flow.get('agent_tasks_done', 0)} "
             f"agent-worked task(s) reached done ({_pct(flow.get('unassisted_share'))} needed "
             "no person but the sign-off)."]
    if by_kind:
        waits = ", ".join(
            f"{_GATE_WORDS.get(str(k), str(k))} {_hours(v.get('median_hours'))}"
            for k, v in sorted(by_kind.items()) if isinstance(v, dict))
        lines.append(f"Median time for a person to decide: {waits}.")
    first = flow.get("first_pass") if isinstance(flow.get("first_pass"), dict) else {}
    assert isinstance(first, dict)
    lines.append(f"First-pass acceptance: reviews {_pct(first.get('reviews'))}, plans and "
                 f"sign-offs {_pct(first.get('approvals'))}.")
    rework = flow.get("rework") if isinstance(flow.get("rework"), dict) else {}
    assert isinstance(rework, dict)
    lines.append(f"Rework: {_pct(rework.get('tasks_returned_share'))} of worked tasks went back "
                 "at least once.")
    queue = flow.get("queue") if isinstance(flow.get("queue"), dict) else {}
    assert isinstance(queue, dict)
    if queue.get("parked"):
        lines.append(f"Parked: {queue.get('parked')} task(s) used up their attempts.")
    if uncleared_moves:
        lines.append(f"Moved in the tracker without canopy's clearance: {uncleared_moves}.")
    if isinstance(flow.get("cost_per_task_usd"), int | float):
        lines.append(f"Cost per completed task: ${flow.get('cost_per_task_usd')}.")
    for exp in flow.get("gates_as_experiments") or []:  # type: ignore[attr-defined]
        if not isinstance(exp, dict):
            continue
        rate, decided = exp.get("approval_rate"), int(exp.get("decided") or 0)
        if isinstance(rate, int | float) and rate >= 0.9 and decided >= 5:
            lines.append(
                f"{_GATE_WORDS.get(str(exp.get('kind')), str(exp.get('kind'))).capitalize()} "
                f"were approved {_pct(rate)} of the time in a median "
                f"{_hours(exp.get('median_hours'))} — a candidate to relax (Agents view → "
                "Graduated autonomy).")
    if not flow.get("sufficient") and flow.get("reason"):
        lines.append(f"_Thin data: {flow.get('reason')}._")
    return lines


def _churn_pct(superseded: int, total: int) -> int:
    return round(100 * superseded / total) if total else 0


def generate_project_retro(inputs: RetroInputs) -> str:
    pct_done = round(100 * inputs.completed_tasks / inputs.total_tasks) if inputs.total_tasks else 0
    milestones = (
        "\n".join(f"- {m}" for m in inputs.completed_milestones)
        if inputs.completed_milestones
        else "- _No milestones marked complete._"
    )
    churn = _churn_pct(inputs.adr_superseded, inputs.adr_total)
    outcomes = (
        "\n".join(f"- {o}" for o in inputs.outcomes)
        if inputs.outcomes
        else "- _No outcomes defined — what bet was this project? (outcomes over output)_"
    )
    lines = [
        f"# Retrospective — {inputs.project_name}",
        f"_Generated {inputs.generated_on.isoformat()}._",
        "",
        "## Outcomes — did the bet pay off?",
        outcomes,
        "",
        "## Summary",
        f"{inputs.completed_tasks}/{inputs.total_tasks} tasks complete ({pct_done}%). "
        f"{inputs.open_drift_events} open drift event(s); ADR churn {churn}% "
        f"({inputs.adr_superseded}/{inputs.adr_total} superseded).",
        "",
        "## What shipped",
        milestones,
        "",
        *(
            ["## Agent work", *(f"- {line}" for line in inputs.agent_work),
             "- _Which gate or rule should change? Decide it here, change it in canopy._", ""]
            if inputs.agent_work else []
        ),
        "## Schedule variance",
        f"- {inputs.drifted_tasks} task(s) ended off their baseline.",
        "",
        "## Architecture health",
        f"- Open drift events: {inputs.open_drift_events}.",
        f"- Decisions: {inputs.adr_accepted} accepted, {inputs.adr_superseded} superseded "
        f"of {inputs.adr_total} total (churn {churn}%).",
        "",
        "## Design docs that changed after approval",
        *(
            [f"- {d}" for d in inputs.docs_changed_after_approval]
            if inputs.docs_changed_after_approval
            else ["- _None — every approved design doc still matches what was signed off._"]
        ),
        "",
        "## What went well",
        "- _Add notes…_",
        "",
        "## What to improve",
        "- _Add notes…_",
        "",
        "## Action items",
        "- _Use the follow-up actions to mint tasks or propose ADRs._",
    ]
    return "\n".join(lines)
