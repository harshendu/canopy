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
    lines = [
        f"# Retrospective — {inputs.project_name}",
        f"_Generated {inputs.generated_on.isoformat()}._",
        "",
        "## Summary",
        f"{inputs.completed_tasks}/{inputs.total_tasks} tasks complete ({pct_done}%). "
        f"{inputs.open_drift_events} open drift event(s); ADR churn {churn}% "
        f"({inputs.adr_superseded}/{inputs.adr_total} superseded).",
        "",
        "## What shipped",
        milestones,
        "",
        "## Schedule variance",
        f"- {inputs.drifted_tasks} task(s) ended off their baseline.",
        "",
        "## Architecture health",
        f"- Open drift events: {inputs.open_drift_events}.",
        f"- Decisions: {inputs.adr_accepted} accepted, {inputs.adr_superseded} superseded "
        f"of {inputs.adr_total} total (churn {churn}%).",
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
