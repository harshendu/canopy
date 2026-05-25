"""Initiative digest — a manage-by-exception weekly health roll-up (pure, unit-testable).

Synthesizes the already-aggregated initiative state into a short briefing that **leads with
what needs attention** (37signals / Cagan: green is silent; surface exceptions). The
endpoint gathers the numbers (reusing the rollup, forecast, blockers, outcomes); this module
decides what's an exception and renders the markdown. Delivery (Slack/email) is a hook over this
output — not built here (same posture as the alerts digest §I). See AI_NATIVE_EXECUTION.md §5.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

_ELEVATED = {"high", "critical"}


@dataclass
class DigestInputs:
    name: str
    generated_on: date
    on_track: bool | None
    target_date: date | None
    project_end: date | None
    p85_date: date | None
    forecast_sufficient: bool
    risk_level: str
    drift_level: str
    avg_percent_complete: float
    completed_tasks: int
    total_tasks: int
    open_decisions: int
    open_blockers: int
    at_risk_projects: list[str] = field(default_factory=list)
    outcomes: list[str] = field(default_factory=list)  # "statement (status)"


def attention_items(inp: DigestInputs) -> list[str]:
    """The exception list — what an architect/EM should look at first."""
    items: list[str] = []
    if inp.on_track is False and inp.project_end and inp.target_date:
        items.append(
            f"Behind target — projected end {inp.project_end} vs target {inp.target_date}."
        )
    if inp.p85_date and inp.target_date and inp.p85_date > inp.target_date:
        items.append(f"P85 forecast {inp.p85_date} is past the target {inp.target_date}.")
    if inp.risk_level in _ELEVATED:
        items.append(f"Risk is {inp.risk_level}.")
    if inp.drift_level in _ELEVATED:
        items.append(f"Architecture drift is {inp.drift_level}.")
    if inp.open_blockers:
        items.append(f"{inp.open_blockers} open blocker(s).")
    if inp.open_decisions:
        items.append(f"{inp.open_decisions} decision(s) awaiting resolution.")
    for project in inp.at_risk_projects:
        items.append(f"Project needs attention: {project}.")
    return items


def headline(attention: list[str]) -> str:
    if not attention:
        return "On track — no exceptions to flag."
    return f"{len(attention)} item(s) need attention."


def render_markdown(inp: DigestInputs, attention: list[str]) -> str:
    pct = round(100 * inp.completed_tasks / inp.total_tasks) if inp.total_tasks else 0
    forecast = (
        f"P85 {inp.p85_date}" if (inp.forecast_sufficient and inp.p85_date) else "not enough data"
    )
    target = inp.target_date.isoformat() if inp.target_date else "—"
    attention_block = (
        "\n".join(f"- {a}" for a in attention)
        if attention
        else "- _Nothing flagged — on track._"
    )
    outcomes_block = (
        "\n".join(f"- {o}" for o in inp.outcomes)
        if inp.outcomes
        else "- _No outcomes defined._"
    )
    return "\n".join(
        [
            f"# {inp.name} — weekly digest ({inp.generated_on.isoformat()})",
            "",
            f"**{headline(attention)}**",
            "",
            "## Needs attention",
            attention_block,
            "",
            "## Status",
            f"- Progress: {inp.completed_tasks}/{inp.total_tasks} tasks ({pct}%).",
            f"- Forecast: {forecast} · target {target}.",
            f"- Risk: {inp.risk_level} · drift: {inp.drift_level}.",
            f"- Open blockers: {inp.open_blockers} · decisions awaiting: {inp.open_decisions}.",
            "",
            "## Outcomes",
            outcomes_block,
        ]
    )
