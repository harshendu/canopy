"""Team and project rules — working agreements and the Definition of Done
(docs/AGENT_EXECUTION.md §10).

A rule is guidance delivered in a session's brief, or an **attestation**: a Definition-of-Done
item a hand-off must attest with evidence (the `attestations_complete` check reads them). A
project's effective rules are the workspace's, then its team's, then its own; a rule with the
same `key` lower down replaces the one above — nearest wins — unless the higher one is `locked`,
and for attestations the stricter enforcement always wins. A lower scope can switch an inherited
rule off (`disabled`) unless it is locked. A rule whose source decision was superseded or
deprecated is **stale**: still applied, flagged in the list, raised as an alert.

`merge` and `applies` are pure; the rest loads facts.
"""

from __future__ import annotations

import fnmatch
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.models.architecture import ArchitectureDecision
from app.models.base import ArtifactKind, RuleKind, RuleScope
from app.models.policy import DeliveryRule
from app.models.project import Project, Task
from app.services.stage_policy import StageDef

STRICTNESS = {"off": 0, "warn": 1, "block": 2}
STALE_STATUSES = frozenset({"superseded", "deprecated"})


@dataclass
class EffectiveRule:
    rule: DeliveryRule
    origin: str  # RuleScope the rule came from
    enforcement: str  # after the stricter-wins merge (attestations)
    overrides: list[str] = field(default_factory=list)  # origins it replaced, nearest last
    stale: bool = False
    stale_reason: str | None = None

    @property
    def key(self) -> str:
        return self.rule.key


def _stricter(a: str, b: str) -> str:
    return a if STRICTNESS.get(a, 1) >= STRICTNESS.get(b, 1) else b


def merge(layers: Iterable[tuple[str, Sequence[DeliveryRule]]]) -> list[EffectiveRule]:
    """Resolve scopes, broadest first (workspace, team, project), into the effective set."""
    by_key: dict[str, EffectiveRule] = {}
    order: list[str] = []
    for origin, rules in layers:
        for rule in sorted(rules, key=lambda r: (r.key, r.id or 0)):
            current = by_key.get(rule.key)
            if current is not None and current.rule.locked:
                # A locked rule stands; a stricter attestation lower down still tightens it.
                if (not rule.disabled and current.rule.kind == RuleKind.attestation.value
                        and rule.kind == RuleKind.attestation.value):
                    current.enforcement = _stricter(current.enforcement, rule.enforcement)
                continue
            if rule.disabled:
                if current is not None:
                    by_key.pop(rule.key)
                    order.remove(rule.key)
                continue
            enforcement = rule.enforcement
            if (current is not None and current.rule.kind == RuleKind.attestation.value
                    and rule.kind == RuleKind.attestation.value):
                enforcement = _stricter(current.enforcement, rule.enforcement)
            by_key[rule.key] = EffectiveRule(
                rule=rule, origin=origin, enforcement=enforcement,
                overrides=[*current.overrides, current.origin] if current is not None else [],
            )
            if rule.key not in order:
                order.append(rule.key)
    return [by_key[k] for k in order]


def applies(
    rule: DeliveryRule,
    *,
    role: str | None,
    tags: Iterable[str],
    component_ids: Iterable[int],
    paths: Sequence[str] | None,
) -> bool:
    """Does `rule` apply to this work? Roles narrow by the stage's role; the selector by task
    tags, components and (once a plan names them) paths — before a plan exists, a path-selected
    rule is included, since it may apply."""
    if rule.roles and (role is None or role not in rule.roles):
        return False
    selector = rule.selector or {}
    wanted_tags = {str(t).strip().lower() for t in selector.get("tags") or []}
    if wanted_tags and not wanted_tags & {t.strip().lower() for t in tags}:
        return False
    wanted_components = {int(c) for c in selector.get("components") or []}
    if wanted_components and not wanted_components & set(component_ids):
        return False
    globs = [str(g) for g in selector.get("paths") or []]
    if globs and paths is not None:
        clean = [p.strip().lstrip("./") for p in paths]
        if not any(fnmatch.fnmatch(p, g) or p.startswith(g.split("*", 1)[0] or "\0")
                   for p in clean for g in globs):
            return False
    return True


# --------------------------------------------------------------------------- #
# Database side
# --------------------------------------------------------------------------- #


async def scope_rules(session: AsyncSession, level: str, scope_id: int) -> list[DeliveryRule]:
    return list(
        (
            await session.execute(
                select(DeliveryRule)
                .where(DeliveryRule.scope_level == level, DeliveryRule.scope_id == scope_id)
                .order_by(col(DeliveryRule.key))
            )
        ).scalars().all()
    )


async def mark_stale(session: AsyncSession, rules: Sequence[EffectiveRule]) -> None:
    ids = {e.rule.source_adr_id for e in rules if e.rule.source_adr_id is not None}
    if not ids:
        return
    statuses: dict[int, tuple[str, str]] = {}
    for adr in (
        await session.execute(
            select(ArchitectureDecision).where(col(ArchitectureDecision.id).in_(list(ids)))
        )
    ).scalars().all():
        if adr.id is not None:
            status = str(adr.status.value if hasattr(adr.status, "value") else adr.status)
            statuses[adr.id] = (status, f"ADR-{adr.number:04d} {adr.title}")
    for effective in rules:
        found = statuses.get(effective.rule.source_adr_id or -1)
        if found is not None and found[0] in STALE_STATUSES:
            effective.stale = True
            effective.stale_reason = f"{found[1]} is {found[0]}"


async def effective_rules(session: AsyncSession, project: Project) -> list[EffectiveRule]:
    """The project's resolved rules, each with where it came from and whether it is stale."""
    from app.services.org import project_team_id

    assert project.id is not None
    team_id = await project_team_id(session, project)
    layers: list[tuple[str, Sequence[DeliveryRule]]] = [
        (RuleScope.workspace.value, await scope_rules(session, RuleScope.workspace.value, 0)),
        (RuleScope.team.value,
         await scope_rules(session, RuleScope.team.value, team_id) if team_id else []),
        (RuleScope.project.value, await scope_rules(session, RuleScope.project.value, project.id)),
    ]
    merged = merge(layers)
    await mark_stale(session, merged)
    return merged


async def _work_context(session: AsyncSession, task: Task) -> tuple[list[int], list[str] | None]:
    """The components a task touches (declared, or resolved from its plan) and its plan's
    paths (None before any plan)."""
    from app.services import work_service

    assert task.id is not None
    component_ids = set(await work_service.task_component_ids(session, task.id))
    plan = await work_service.latest_artifact(session, task.id, ArtifactKind.plan)
    paths: list[str] | None = None
    if plan is not None:
        data = plan.data or {}
        component_ids |= {int(c) for c in data.get("resolved_component_ids") or []}
        paths = [str(p) for p in data.get("affected_paths") or []]
    return sorted(component_ids), paths


async def applicable(
    session: AsyncSession, task: Task, role: str | None, kind: RuleKind | None = None
) -> list[EffectiveRule]:
    project = await session.get(Project, task.project_id)
    if project is None:
        return []
    component_ids, paths = await _work_context(session, task)
    return [
        e for e in await effective_rules(session, project)
        if (kind is None or e.rule.kind == kind.value)
        and applies(e.rule, role=role, tags=task.tags or [], component_ids=component_ids,
                    paths=paths)
    ]


async def required_attestations(session: AsyncSession, task: Task, stage: StageDef) -> list[str]:
    """The Definition-of-Done rule keys a hand-off from `stage` must attest."""
    return [e.key for e in await attestation_rules(session, task, stage)]


async def attestation_rules(
    session: AsyncSession, task: Task, stage: StageDef
) -> list[EffectiveRule]:
    return [
        e for e in await applicable(session, task, stage.worked_by, RuleKind.attestation)
        if e.enforcement != "off"
    ]


async def rules_for_brief(
    session: AsyncSession, task: Task, stage: StageDef | None, role: str | None
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """(guidance, attestations) for a brief — the rules that apply to this role and task."""
    guidance: list[dict[str, object]] = []
    attestations: list[dict[str, object]] = []
    for e in await applicable(session, task, role or (stage.worked_by if stage else None)):
        item: dict[str, object] = {
            "key": e.key, "title": e.rule.title, "body": e.rule.body, "origin": e.origin,
        }
        if e.stale:
            item["stale"] = e.stale_reason
        if e.rule.kind == RuleKind.attestation.value:
            if e.enforcement == "off":
                continue
            attestations.append({**item, "enforcement": e.enforcement,
                                 "how": "Attest it in submit_work(attestations=[{rule_key, "
                                        "status: done | n/a | not_done, evidence}])"})
        else:
            guidance.append(item)
    return guidance, attestations
