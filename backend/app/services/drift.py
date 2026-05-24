"""Architecture drift detection (pure, unit-testable).

Compares the *declared* architecture (component links + accepted ADRs) against what the
code actually does (observed edges, component activity, and flagged implicit decisions),
producing drift findings with a stable `rule_key` for dedupe + suppression, plus a
0-100 drift score. All the I/O — reading code, walking commits — happens in the caller
(the Drift Sentinel subagent or the scan endpoint); this module is pure.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# kind -> how much one open finding of that kind contributes to the 0-100 score.
KIND_WEIGHTS = {
    "unexpected_dependency": 12,
    "dead_dependency": 8,
    "unimplemented_adr": 15,
    "implicit_decision": 20,  # an architectural change with no ADR is the loudest signal
    "fitness_violation": 25,  # an accepted decision's machine-checkable rule is broken — loudest
}


@dataclass
class ImplicitSignal:
    kind: str  # new_package | new_dependency | new_service | new_datastore
    summary: str
    suspected_cause: str | None = None
    component_id: int | None = None


@dataclass
class FitnessRule:
    """An ADR's machine-checkable dependency assertion, evaluated against the actual edges.
    `forbid`: source must NOT depend on target; `require`: it MUST."""

    id: int
    adr_number: int
    kind: str  # forbid | require
    source_component_id: int
    target_component_id: int
    description: str | None = None


@dataclass
class DriftInputs:
    component_names: dict[int, str]
    declared_edges: set[tuple[int, int]] = field(default_factory=set)
    actual_edges: set[tuple[int, int]] = field(default_factory=set)
    # Accepted ADRs as (number, title, affected_component_ids).
    accepted_adrs: list[tuple[int, str, list[int]]] = field(default_factory=list)
    # Components with no recent commit activity (for unimplemented-ADR detection).
    inactive_component_ids: set[int] = field(default_factory=set)
    implicit_signals: list[ImplicitSignal] = field(default_factory=list)
    # Machine-checkable dependency rules from accepted ADRs (evaluated vs actual_edges).
    fitness_rules: list[FitnessRule] = field(default_factory=list)


@dataclass
class Finding:
    kind: str
    rule_key: str
    summary: str
    detail: str | None
    suspected_cause: str | None
    affected_component_ids: list[int]


@dataclass
class DriftReport:
    score: int
    level: str
    findings: list[Finding]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


def _name(names: dict[int, str], cid: int) -> str:
    return names.get(cid, f"#{cid}")


def detect(inputs: DriftInputs) -> list[Finding]:
    names = inputs.component_names
    findings: list[Finding] = []

    # 1. Dependency drift: edges in code but not declared, and declared but not in code.
    for src, tgt in sorted(inputs.actual_edges - inputs.declared_edges):
        edge = f"{_name(names, src)} → {_name(names, tgt)}"
        findings.append(
            Finding(
                kind="unexpected_dependency",
                rule_key=f"dep_unexpected:{src}->{tgt}",
                summary=f"{edge} exists in code but isn't declared",
                detail="Code imports across this edge, but the system map has no such link.",
                suspected_cause=None,
                affected_component_ids=[src, tgt],
            )
        )
    for src, tgt in sorted(inputs.declared_edges - inputs.actual_edges):
        edge = f"{_name(names, src)} → {_name(names, tgt)}"
        findings.append(
            Finding(
                kind="dead_dependency",
                rule_key=f"dep_missing:{src}->{tgt}",
                summary=f"{edge} is declared but not found in code",
                detail="The system map declares this link, but no code backs it (dead arch).",
                suspected_cause=None,
                affected_component_ids=[src, tgt],
            )
        )

    # 2. Accepted ADRs whose affected components show no activity (unimplemented decisions).
    for number, title, component_ids in inputs.accepted_adrs:
        if component_ids and all(cid in inputs.inactive_component_ids for cid in component_ids):
            findings.append(
                Finding(
                    kind="unimplemented_adr",
                    rule_key=f"adr_unimplemented:{number}",
                    summary=f"ADR-{number:04d} '{title}' is accepted but its components are idle",
                    detail="Accepted decision with no commit activity on its affected components.",
                    suspected_cause=None,
                    affected_component_ids=list(component_ids),
                )
            )

    # 3. Fitness functions: accepted ADRs' machine-checkable dependency rules, evaluated
    #    against the actual edges. A violated rule is the loudest signal — the decision is
    #    not being honored.
    for rule in inputs.fitness_rules:
        pair = (rule.source_component_id, rule.target_component_id)
        present = pair in inputs.actual_edges
        violated = present if rule.kind == "forbid" else (not present)
        if violated:
            arrow = f"{_name(names, rule.source_component_id)} → " + _name(
                names, rule.target_component_id
            )
            verb = "must not depend on" if rule.kind == "forbid" else "must depend on"
            findings.append(
                Finding(
                    kind="fitness_violation",
                    rule_key=f"fitness:{rule.id}",
                    summary=f"ADR-{rule.adr_number:04d} fitness violated: {arrow}",
                    detail=rule.description
                    or (
                        f"{_name(names, rule.source_component_id)} {verb} "
                        f"{_name(names, rule.target_component_id)} (ADR-{rule.adr_number:04d})."
                    ),
                    suspected_cause=f"ADR-{rule.adr_number:04d}",
                    affected_component_ids=[rule.source_component_id, rule.target_component_id],
                )
            )

    # 4. Implicit decisions: architectural changes in code with no ADR.
    for signal in inputs.implicit_signals:
        findings.append(
            Finding(
                kind="implicit_decision",
                rule_key=f"implicit:{signal.kind}:{_slug(signal.summary)}",
                summary=signal.summary,
                detail=f"Architectural change of kind '{signal.kind}' with no corresponding ADR.",
                suspected_cause=signal.suspected_cause,
                affected_component_ids=[signal.component_id] if signal.component_id else [],
            )
        )

    return findings


def apply_suppressions(findings: list[Finding], suppressed: set[str]) -> list[Finding]:
    return [f for f in findings if f.rule_key not in suppressed]


def score_kinds(kinds: list[str]) -> int:
    total = sum(KIND_WEIGHTS.get(k, 5) for k in kinds)
    return max(0, min(100, total))


def level(score: int) -> str:
    if score < 20:
        return "low"
    if score < 45:
        return "moderate"
    if score < 70:
        return "high"
    return "critical"


def run_detection(inputs: DriftInputs, suppressed: set[str]) -> DriftReport:
    findings = apply_suppressions(detect(inputs), suppressed)
    score = score_kinds([f.kind for f in findings])
    return DriftReport(score=score, level=level(score), findings=findings)
