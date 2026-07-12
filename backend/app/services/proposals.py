"""Change proposals: validation, before-snapshots, and the apply engine.

A proposal is a batch of staged mutations (`ProposalItem`s) an agent assembled — usually
from external signal (Slack/email/meetings/Jira/GitHub/Drive) — that a human reviews and
**applies** from the UI. This module is the whole write path:

- **Whitelisted payloads.** Every (entity, action) pair has an explicit field whitelist
  and a Pydantic validator (reusing the API's own request schemas where they exist), so a
  staged payload can never mass-assign arbitrary columns. Jira-owned `Task.status` is not
  writable here at all (the source-of-truth rule holds).
- **Scope containment.** A proposal is scoped to one project or initiative; every item
  must target that scope (a proposal reviewed under project A cannot mutate project B).
- **Refs.** A create item may declare a `ref` handle; later items may point at it with
  `*_ref` payload keys (`parent_ref`, `predecessor_ref`, `task_ref`, …) so a proposal can
  stage "create phase → create task under it → link them" before any ids exist.
- **Before snapshots** are captured at stage time for update/resolve items; the same
  snapshot recomputed at read time shows the reviewer live drift since staging.
- **Apply** is all-or-nothing: validate every included item, then execute in order in one
  transaction, replan the schedule-affected projects, and publish live-refresh events.

Called from `app/api/v1/proposals.py`; the review/commit endpoints there are human-only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.core.events import publish
from app.models.architecture import ArchitectureDecision
from app.models.base import (
    ADRStatus,
    DocScope,
    OutcomeScope,
    ProposalAction,
    ProposalEntity,
    ProposalScope,
    ProposalStatus,
    Reversibility,
    RiskScope,
    RiskStatus,
    utcnow,
)
from app.models.doc import DocReference
from app.models.outcome import Outcome
from app.models.project import Blocker, Dependency, Initiative, Milestone, Project, Task
from app.models.proposal import Proposal, ProposalItem
from app.models.risk_register import RiskItem
from app.schemas.entities import (
    BlockerCreate,
    DependencyCreate,
    DocReferenceCreate,
    MilestoneCreate,
    OutcomeCreate,
    OutcomeUpdate,
    RiskItemCreate,
    RiskItemUpdate,
    TaskCreate,
    TaskUpdate,
)
from app.services.metadata import normalize_tags
from app.services.planner import reschedule_project


class ProposalValidationError(Exception):
    """One or more items are invalid; `issues` maps each to a human-readable error."""

    def __init__(self, issues: list[ItemIssue]) -> None:
        super().__init__("; ".join(f"item {i.index}: {i.error}" for i in issues))
        self.issues = issues


@dataclass
class ItemIssue:
    index: int  # position within the proposal (stage time) — stable for the client
    error: str
    item_id: int | None = None  # set when validating persisted items


@dataclass
class ApplyOutcome:
    applied: int
    skipped: int  # reviewer-excluded items
    replanned_projects: list[int] = field(default_factory=list)


# --- payload validators (partial-update shapes the REST API doesn't need) ---


class _MilestonePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    description: str | None = None
    target_date: date | None = None
    status: str | None = None  # planned | at_risk | hit | missed


class _DecisionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: int
    title: str
    context: str | None = None
    decision: str | None = None
    consequences: str | None = None
    alternatives: list[str] = []
    reversibility: Reversibility | None = None
    decide_by: date | None = None
    rfc_url: str | None = None
    decision_owner_id: int | None = None
    proposed_by_id: int | None = None


# Payload field whitelists per (entity, action). `*_ref` keys are the intra-proposal
# reference alternative for the matching `*_id` key and are validated separately.
_ALLOWED_FIELDS: dict[tuple[ProposalEntity, ProposalAction], frozenset[str]] = {
    (ProposalEntity.task, ProposalAction.create): frozenset(
        {
            "project_id", "parent_id", "name", "description", "type", "start", "duration",
            "deadline", "assignee_engineer_id", "spec_id", "tags",
            "estimate_optimistic", "estimate_likely", "estimate_pessimistic",
        }
    ),
    (ProposalEntity.task, ProposalAction.update): frozenset(
        {
            "name", "description", "parent_id", "start", "duration", "deadline",
            "percent_complete", "assignee_engineer_id", "spec_id", "tags",
            "estimate_optimistic", "estimate_likely", "estimate_pessimistic",
        }
    ),
    (ProposalEntity.dependency, ProposalAction.create): frozenset(
        {"predecessor_id", "successor_id", "type", "lag"}
    ),
    (ProposalEntity.milestone, ProposalAction.create): frozenset(
        {"project_id", "name", "description", "target_date", "status"}
    ),
    (ProposalEntity.milestone, ProposalAction.update): frozenset(
        {"name", "description", "target_date", "status"}
    ),
    (ProposalEntity.blocker, ProposalAction.create): frozenset(
        {
            "task_id", "reason", "category", "severity", "owner_engineer_id",
            "needed_by", "blocking_task_id", "raised_by_engineer_id",
        }
    ),
    (ProposalEntity.blocker, ProposalAction.resolve): frozenset(),
    (ProposalEntity.risk, ProposalAction.create): frozenset(
        {
            "scope_level", "scope_id", "title", "description", "category", "probability",
            "impact", "status", "owner_engineer_id", "mitigation", "contingency",
            "target_resolution_date",
        }
    ),
    (ProposalEntity.risk, ProposalAction.update): frozenset(
        {
            "title", "description", "category", "probability", "impact", "status",
            "owner_engineer_id", "mitigation", "contingency", "target_resolution_date",
        }
    ),
    (ProposalEntity.outcome, ProposalAction.create): frozenset(
        {
            "scope_level", "scope_id", "statement", "metric", "unit", "baseline_value",
            "target_value", "current_value", "status", "target_date", "owner_engineer_id",
        }
    ),
    (ProposalEntity.outcome, ProposalAction.update): frozenset(
        {
            "statement", "metric", "unit", "baseline_value", "target_value",
            "current_value", "status", "target_date", "owner_engineer_id",
        }
    ),
    (ProposalEntity.decision, ProposalAction.create): frozenset(
        {
            "project_id", "title", "context", "decision", "consequences", "alternatives",
            "reversibility", "decide_by", "rfc_url", "decision_owner_id", "proposed_by_id",
        }
    ),
    (ProposalEntity.doc_reference, ProposalAction.create): frozenset(
        {"scope_level", "scope_id", "url", "kind", "title", "owner_engineer_id"}
    ),
}

# `<ref key> -> <id key>` per (entity, action): where a staged item may point at an
# entity created earlier in the same proposal instead of a live id.
_REF_KEYS: dict[tuple[ProposalEntity, ProposalAction], dict[str, str]] = {
    (ProposalEntity.task, ProposalAction.create): {"parent_ref": "parent_id"},
    (ProposalEntity.dependency, ProposalAction.create): {
        "predecessor_ref": "predecessor_id",
        "successor_ref": "successor_id",
    },
    (ProposalEntity.blocker, ProposalAction.create): {
        "task_ref": "task_id",
        "blocking_task_ref": "blocking_task_id",
    },
}

# The display label field per entity (folded into before/current snapshots).
_LABEL_FIELDS: dict[ProposalEntity, str] = {
    ProposalEntity.task: "name",
    ProposalEntity.milestone: "name",
    ProposalEntity.blocker: "reason",
    ProposalEntity.risk: "title",
    ProposalEntity.outcome: "statement",
    ProposalEntity.decision: "title",
    ProposalEntity.doc_reference: "url",
}

_RISK_TERMINAL = {RiskStatus.resolved, RiskStatus.accepted, RiskStatus.occurred}

_M = TypeVar("_M")


def _jsonable(value: Any) -> Any:
    """Coerce a snapshot value into something a JSON column can hold."""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return value


def _entity_model(entity: ProposalEntity) -> type[Any]:
    return {
        ProposalEntity.task: Task,
        ProposalEntity.dependency: Dependency,
        ProposalEntity.milestone: Milestone,
        ProposalEntity.blocker: Blocker,
        ProposalEntity.risk: RiskItem,
        ProposalEntity.outcome: Outcome,
        ProposalEntity.decision: ArchitectureDecision,
        ProposalEntity.doc_reference: DocReference,
    }[entity]


async def scope_exists(
    session: AsyncSession, scope_level: ProposalScope, scope_id: int
) -> bool:
    model = Project if scope_level == ProposalScope.project else Initiative
    return await session.get(model, scope_id) is not None


async def _scope_project_ids(
    session: AsyncSession, scope_level: ProposalScope, scope_id: int
) -> set[int]:
    """The project ids a proposal of this scope may touch."""
    if scope_level == ProposalScope.project:
        return {scope_id}
    result = await session.execute(select(Project.id).where(Project.initiative_id == scope_id))
    return {pid for pid in result.scalars().all() if pid is not None}


async def _task_in_scope(session: AsyncSession, task_id: int, projects: set[int]) -> Task | None:
    task = await session.get(Task, task_id)
    if task is None or task.project_id not in projects:
        return None
    return task


def _validate_payload(
    entity: ProposalEntity, action: ProposalAction, payload: dict[str, Any]
) -> dict[str, Any]:
    """Whitelist-check + type-coerce a payload. Returns the coerced field dict; raises
    ValueError with a readable message on any problem."""
    allowed = _ALLOWED_FIELDS.get((entity, action))
    if allowed is None:
        raise ValueError(f"unsupported operation: {entity.value}.{action.value}")
    ref_keys = _REF_KEYS.get((entity, action), {})
    unknown = set(payload) - set(allowed) - set(ref_keys)
    if unknown:
        raise ValueError(f"unknown field(s) for {entity.value}.{action.value}: "
                         f"{', '.join(sorted(unknown))}")
    for ref_key, id_key in ref_keys.items():
        if ref_key in payload and id_key in payload:
            raise ValueError(f"pass either {ref_key} or {id_key}, not both")
        if ref_key in payload and not isinstance(payload[ref_key], str):
            raise ValueError(f"{ref_key} must be a string ref handle")

    concrete = {k: v for k, v in payload.items() if k not in ref_keys}
    # Refs stand in for required ids during shape validation.
    for ref_key, id_key in ref_keys.items():
        if ref_key in payload:
            concrete[id_key] = 0
    try:
        validated = _shape_validate(entity, action, concrete)
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = ".".join(str(part) for part in first.get("loc", ()))
        raise ValueError(f"invalid {entity.value} payload ({loc}: {first['msg']})") from exc
    # Drop the placeholder ids again — apply substitutes the real ones.
    for ref_key, id_key in ref_keys.items():
        if ref_key in payload:
            validated.pop(id_key, None)
            validated[ref_key] = payload[ref_key]
    return validated


def _shape_validate(
    entity: ProposalEntity, action: ProposalAction, concrete: dict[str, Any]
) -> dict[str, Any]:
    """Run the payload through the matching Pydantic shape and return coerced fields
    (updates keep only the keys that were actually provided)."""
    create = action == ProposalAction.create
    if entity == ProposalEntity.task:
        if create:
            return TaskCreate.model_validate(concrete).model_dump()
        return TaskUpdate.model_validate(concrete).model_dump(exclude_unset=True)
    if entity == ProposalEntity.dependency:
        return DependencyCreate.model_validate(concrete).model_dump()
    if entity == ProposalEntity.milestone:
        if create:
            return MilestoneCreate.model_validate(concrete).model_dump()
        return _MilestonePatch.model_validate(concrete).model_dump(exclude_unset=True)
    if entity == ProposalEntity.blocker:
        if create:
            return BlockerCreate.model_validate(
                {k: v for k, v in concrete.items() if k != "task_id"}
            ).model_dump() | ({"task_id": concrete["task_id"]} if "task_id" in concrete else {})
        return {}
    if entity == ProposalEntity.risk:
        if create:
            return RiskItemCreate.model_validate(concrete).model_dump()
        return RiskItemUpdate.model_validate(concrete).model_dump(exclude_unset=True)
    if entity == ProposalEntity.outcome:
        if create:
            return OutcomeCreate.model_validate(concrete).model_dump()
        return OutcomeUpdate.model_validate(concrete).model_dump(exclude_unset=True)
    if entity == ProposalEntity.decision:
        return _DecisionPayload.model_validate(concrete).model_dump()
    return DocReferenceCreate.model_validate(concrete).model_dump()


def _inject_scope_defaults(
    item: ProposalItem, scope_level: ProposalScope, scope_id: int
) -> None:
    """Fill scope-derived defaults so a project-scoped proposal's items may omit them."""
    payload = dict(item.payload or {})
    entity, action = item.entity_type, item.action
    project_bound = (ProposalEntity.task, ProposalEntity.milestone, ProposalEntity.decision)
    if action == ProposalAction.create:
        if entity in project_bound and scope_level == ProposalScope.project:
            payload.setdefault("project_id", scope_id)
        if entity in (ProposalEntity.risk, ProposalEntity.outcome, ProposalEntity.doc_reference):
            payload.setdefault("scope_level", scope_level.value)
            payload.setdefault("scope_id", scope_id)
    item.payload = payload


async def check_items(
    session: AsyncSession,
    scope_level: ProposalScope,
    scope_id: int,
    items: list[ProposalItem],
) -> list[ItemIssue]:
    """Validate every item (shape, refs, target existence, scope containment). Pure read —
    call at stage time (strict 400) and again right before apply (state may have moved)."""
    issues: list[ItemIssue] = []
    projects = await _scope_project_ids(session, scope_level, scope_id)
    declared_refs: set[str] = set()

    for index, item in enumerate(items):
        try:
            _inject_scope_defaults(item, scope_level, scope_id)
            fields = _validate_payload(item.entity_type, item.action, dict(item.payload or {}))
            if item.action == ProposalAction.create:
                if item.entity_id is not None:
                    raise ValueError("a create item must not set entity_id")
                await _check_create(
                    session, item, fields, projects, declared_refs, scope_level, scope_id
                )
                if item.ref:
                    if item.ref in declared_refs:
                        raise ValueError(f"duplicate ref '{item.ref}'")
                    declared_refs.add(item.ref)
            else:
                if item.ref:
                    raise ValueError("only create items may declare a ref")
                if item.entity_id is None:
                    raise ValueError(f"{item.action.value} requires entity_id")
                await _check_target(session, item, fields, projects, scope_level, scope_id)
        except ValueError as exc:
            issues.append(ItemIssue(index=index, error=str(exc), item_id=item.id))
    return issues


async def _check_create(
    session: AsyncSession,
    item: ProposalItem,
    fields: dict[str, Any],
    projects: set[int],
    declared_refs: set[str],
    scope_level: ProposalScope,
    scope_id: int,
) -> None:
    entity = item.entity_type
    payload = dict(item.payload or {})
    for ref_key in _REF_KEYS.get((entity, item.action), {}):
        ref_value = payload.get(ref_key)
        if ref_value is not None and ref_value not in declared_refs:
            raise ValueError(f"{ref_key} '{ref_value}' does not match any earlier item's ref")

    if entity == ProposalEntity.task:
        if not str(fields.get("name") or "").strip():
            raise ValueError("task name is required")
        if fields.get("project_id") not in projects:
            raise ValueError("task project is outside this proposal's scope")
        parent_id = fields.get("parent_id")
        if parent_id is not None and await _task_in_scope(session, parent_id, projects) is None:
            raise ValueError(f"parent task {parent_id} not found in scope")
    elif entity == ProposalEntity.dependency:
        for key in ("predecessor_id", "successor_id"):
            tid = fields.get(key)
            if tid is not None and await _task_in_scope(session, tid, projects) is None:
                raise ValueError(f"{key} {tid} not found in scope")
        pred, succ = fields.get("predecessor_id"), fields.get("successor_id")
        if pred is not None and succ is not None and pred == succ:
            raise ValueError("a task cannot depend on itself")
        pred_ref, succ_ref = payload.get("predecessor_ref"), payload.get("successor_ref")
        if pred_ref is not None and pred_ref == succ_ref:
            raise ValueError("a task cannot depend on itself (same ref on both ends)")
    elif entity == ProposalEntity.milestone:
        if fields.get("project_id") not in projects:
            raise ValueError("milestone project is outside this proposal's scope")
    elif entity == ProposalEntity.blocker:
        task_id = fields.get("task_id")
        if task_id is not None and await _task_in_scope(session, task_id, projects) is None:
            raise ValueError(f"task {task_id} not found in scope")
        if task_id is None and "task_ref" not in payload:
            raise ValueError("a blocker needs task_id or task_ref")
        if not str(fields.get("reason") or "").strip():
            raise ValueError("blocker reason is required")
    elif entity in (ProposalEntity.risk, ProposalEntity.outcome, ProposalEntity.doc_reference):
        await _check_polymorphic_scope(session, entity, fields, projects, scope_level, scope_id)
    elif entity == ProposalEntity.decision:
        if fields.get("project_id") not in projects:
            raise ValueError("decision project is outside this proposal's scope")
        if not str(fields.get("title") or "").strip():
            raise ValueError("decision title is required")


async def _check_polymorphic_scope(
    session: AsyncSession,
    entity: ProposalEntity,
    fields: dict[str, Any],
    projects: set[int],
    scope_level: ProposalScope,
    scope_id: int,
) -> None:
    """A risk / outcome / doc reference hangs off task|project|initiative — confirm the
    declared scope stays inside the proposal's scope."""
    level = str(_jsonable(fields.get("scope_level")) or "")
    target = fields.get("scope_id")
    if target is None:
        raise ValueError("scope_id is required")
    if level == "project":
        if target not in projects:
            raise ValueError(f"{entity.value} project scope is outside this proposal's scope")
    elif level == "task":
        if entity == ProposalEntity.outcome:
            raise ValueError("outcomes may not be task-scoped")
        if await _task_in_scope(session, int(target), projects) is None:
            raise ValueError(f"task {target} not found in scope")
    elif level == "initiative":
        # Only valid when the proposal itself is scoped to this same initiative.
        if scope_level != ProposalScope.initiative or int(target) != scope_id:
            raise ValueError(f"{entity.value} initiative scope does not match this proposal")
    else:
        raise ValueError(f"unknown scope_level '{level}'")


async def _check_target(
    session: AsyncSession,
    item: ProposalItem,
    fields: dict[str, Any],
    projects: set[int],
    scope_level: ProposalScope,
    scope_id: int,
) -> None:
    """Update/resolve items must point at a live entity inside the proposal's scope."""
    entity, entity_id = item.entity_type, item.entity_id
    assert entity_id is not None
    if entity == ProposalEntity.task:
        if await _task_in_scope(session, entity_id, projects) is None:
            raise ValueError(f"task {entity_id} not found in scope")
    elif entity == ProposalEntity.milestone:
        milestone = await session.get(Milestone, entity_id)
        if milestone is None or milestone.project_id not in projects:
            raise ValueError(f"milestone {entity_id} not found in scope")
    elif entity == ProposalEntity.blocker:
        blocker = await session.get(Blocker, entity_id)
        if blocker is None or await _task_in_scope(session, blocker.task_id, projects) is None:
            raise ValueError(f"blocker {entity_id} not found in scope")
    elif entity == ProposalEntity.risk:
        risk = await session.get(RiskItem, entity_id)
        if risk is None:
            raise ValueError(f"risk {entity_id} not found")
        ok = (
            (risk.scope_level == RiskScope.project and risk.scope_id in projects)
            or (
                risk.scope_level == RiskScope.task
                and await _task_in_scope(session, risk.scope_id, projects) is not None
            )
            or (
                risk.scope_level == RiskScope.initiative
                and scope_level == ProposalScope.initiative
                and risk.scope_id == scope_id
            )
        )
        if not ok:
            raise ValueError(f"risk {entity_id} is outside this proposal's scope")
    elif entity == ProposalEntity.outcome:
        outcome = await session.get(Outcome, entity_id)
        if outcome is None:
            raise ValueError(f"outcome {entity_id} not found")
        ok = (outcome.scope_level == OutcomeScope.project and outcome.scope_id in projects) or (
            outcome.scope_level == OutcomeScope.initiative
            and scope_level == ProposalScope.initiative
            and outcome.scope_id == scope_id
        )
        if not ok:
            raise ValueError(f"outcome {entity_id} is outside this proposal's scope")
    else:
        raise ValueError(f"{entity.value} does not support {item.action.value}")


async def snapshot_target(session: AsyncSession, item: ProposalItem) -> dict[str, Any] | None:
    """The current values of an update/resolve item's payload fields on its live target
    (plus the entity's display label). None when the target no longer exists. Used for the
    stage-time `before` snapshot and recomputed at read time to surface staleness."""
    if item.action == ProposalAction.create or item.entity_id is None:
        return None
    target = await session.get(_entity_model(item.entity_type), item.entity_id)
    if target is None:
        return None
    keys = set((item.payload or {}).keys())
    label_field = _LABEL_FIELDS.get(item.entity_type)
    if label_field:
        keys.add(label_field)
    if item.action == ProposalAction.resolve:
        keys.update({"resolved_at"})
    snapshot: dict[str, Any] = {}
    for key in sorted(keys):
        if key.endswith("_ref"):
            continue
        if hasattr(target, key):
            snapshot[key] = _jsonable(getattr(target, key))
    return snapshot


# --- apply ---


async def _next_adr_number(session: AsyncSession, project_id: int) -> int:
    result = await session.execute(
        select(func.max(ArchitectureDecision.number)).where(
            ArchitectureDecision.project_id == project_id
        )
    )
    current = result.scalar_one_or_none()
    return int(current or 0) + 1


def _resolve_refs(
    item: ProposalItem, fields: dict[str, Any], refs: dict[str, int]
) -> dict[str, Any]:
    resolved = dict(fields)
    for ref_key, id_key in _REF_KEYS.get((item.entity_type, item.action), {}).items():
        handle = resolved.pop(ref_key, None)
        if handle is not None:
            created = refs.get(str(handle))
            if created is None:
                raise ValueError(f"{ref_key} '{handle}' was never created")
            resolved[id_key] = created
    return resolved


async def _apply_item(
    session: AsyncSession,
    item: ProposalItem,
    fields: dict[str, Any],
    replan: set[int],
) -> int:
    """Execute one validated item; returns the created/updated entity id and accumulates
    the projects whose schedule must be recomputed."""
    entity, action = item.entity_type, item.action

    if entity == ProposalEntity.task and action == ProposalAction.create:
        fields["tags"] = normalize_tags(list(fields.get("tags") or []))
        task = Task(**fields)
        session.add(task)
        await session.flush()
        assert task.id is not None
        replan.add(task.project_id)
        return task.id

    if entity == ProposalEntity.task and action == ProposalAction.update:
        task = await _require(session, Task, item.entity_id)
        if "tags" in fields and fields["tags"] is not None:
            fields["tags"] = normalize_tags(list(fields["tags"]))
        for key, value in fields.items():
            setattr(task, key, value)
        replan.add(task.project_id)
        assert task.id is not None
        return task.id

    if entity == ProposalEntity.dependency:
        dependency = Dependency(**fields)
        session.add(dependency)
        await session.flush()
        for tid in (dependency.predecessor_id, dependency.successor_id):
            task_row = await session.get(Task, tid)
            if task_row is not None:
                replan.add(task_row.project_id)
        assert dependency.id is not None
        return dependency.id

    if entity == ProposalEntity.milestone and action == ProposalAction.create:
        milestone = Milestone(**fields)
        session.add(milestone)
        await session.flush()
        assert milestone.id is not None
        return milestone.id

    if entity == ProposalEntity.milestone and action == ProposalAction.update:
        milestone = await _require(session, Milestone, item.entity_id)
        for key, value in fields.items():
            setattr(milestone, key, value)
        assert milestone.id is not None
        return milestone.id

    if entity == ProposalEntity.blocker and action == ProposalAction.create:
        blocker = Blocker(**fields)
        session.add(blocker)
        await session.flush()
        assert blocker.id is not None
        return blocker.id

    if entity == ProposalEntity.blocker and action == ProposalAction.resolve:
        blocker = await _require(session, Blocker, item.entity_id)
        if blocker.resolved_at is None:
            blocker.resolved_at = utcnow()
        assert blocker.id is not None
        return blocker.id

    if entity == ProposalEntity.risk and action == ProposalAction.create:
        risk = RiskItem(**fields)
        _risk_status_side_effects(risk)
        session.add(risk)
        await session.flush()
        assert risk.id is not None
        return risk.id

    if entity == ProposalEntity.risk and action == ProposalAction.update:
        risk = await _require(session, RiskItem, item.entity_id)
        for key, value in fields.items():
            setattr(risk, key, value)
        _risk_status_side_effects(risk)
        assert risk.id is not None
        return risk.id

    if entity == ProposalEntity.outcome and action == ProposalAction.create:
        outcome = Outcome(**fields)
        session.add(outcome)
        await session.flush()
        assert outcome.id is not None
        return outcome.id

    if entity == ProposalEntity.outcome and action == ProposalAction.update:
        outcome = await _require(session, Outcome, item.entity_id)
        for key, value in fields.items():
            setattr(outcome, key, value)
        assert outcome.id is not None
        return outcome.id

    if entity == ProposalEntity.decision:
        project_id = int(fields["project_id"])
        adr = ArchitectureDecision(
            number=await _next_adr_number(session, project_id),
            status=ADRStatus.proposed,  # proposals stage *proposed* decisions; the ADR
            **fields,  # lifecycle (review, accept) takes over from there
        )
        session.add(adr)
        await session.flush()
        assert adr.id is not None
        return adr.id

    # doc_reference.create — idempotent per (scope, url), like the harvest path.
    existing = await session.execute(
        select(DocReference).where(
            DocReference.scope_level == DocScope(str(_jsonable(fields["scope_level"]))),
            DocReference.scope_id == int(fields["scope_id"]),
            col(DocReference.url) == str(fields["url"]),
        )
    )
    found = existing.scalars().first()
    if found is not None:
        assert found.id is not None
        return found.id
    doc = DocReference(**fields)
    session.add(doc)
    await session.flush()
    assert doc.id is not None
    return doc.id


def _risk_status_side_effects(risk: RiskItem) -> None:
    if risk.status in _RISK_TERMINAL:
        if risk.resolved_at is None:
            risk.resolved_at = utcnow()
    else:
        risk.resolved_at = None


async def _require(session: AsyncSession, model: type[_M], entity_id: int | None) -> _M:
    assert entity_id is not None
    row = await session.get(model, entity_id)
    if row is None:
        raise ValueError(f"{model.__name__} {entity_id} disappeared during apply")
    return row


async def apply_proposal(
    session: AsyncSession, proposal: Proposal, reviewer_user_id: int | None
) -> ApplyOutcome:
    """Validate and execute every included item, replan the schedule-affected projects,
    and mark the proposal applied — one transaction, all or nothing.

    Raises ProposalValidationError (nothing written) when any included item fails
    validation, or scheduling's CycleError if a staged dependency creates a cycle.
    """
    all_items = await load_items(session, proposal)
    included = [i for i in all_items if not i.excluded]
    issues = await check_items(session, proposal.scope_level, proposal.scope_id, included)
    if issues:
        for issue in issues:
            item = included[issue.index]
            issue.item_id = item.id
            item.error = issue.error
        await session.commit()  # persist per-item errors so the UI can show them
        raise ProposalValidationError(issues)

    refs: dict[str, int] = {}
    replan: set[int] = set()
    for item in included:
        fields = _validate_payload(item.entity_type, item.action, dict(item.payload or {}))
        fields = _resolve_refs(item, fields, refs)
        applied_id = await _apply_item(session, item, fields, replan)
        item.applied_entity_id = applied_id
        item.error = None
        if item.ref:
            refs[item.ref] = applied_id

    for project_id in sorted(replan):
        # Fold each replan into this transaction; a cycle aborts the whole apply.
        await reschedule_project(session, project_id, persist=True, commit=False)

    proposal.status = ProposalStatus.applied
    proposal.reviewed_by_user_id = reviewer_user_id
    proposal.reviewed_at = utcnow()
    proposal.applied_count = len(included)
    await session.commit()

    await publish(
        {
            "type": "proposal",
            "proposal_id": proposal.id,
            "status": proposal.status.value,
            "scope_level": proposal.scope_level.value,
            "scope_id": proposal.scope_id,
        }
    )
    for project_id in sorted(replan):
        await publish({"type": "replan", "project_id": project_id})

    return ApplyOutcome(
        applied=len(included),
        skipped=len(all_items) - len(included),
        replanned_projects=sorted(replan),
    )


async def load_items(session: AsyncSession, proposal: Proposal) -> list[ProposalItem]:
    result = await session.execute(
        select(ProposalItem)
        .where(ProposalItem.proposal_id == proposal.id)
        .order_by(col(ProposalItem.sort_order), col(ProposalItem.id))
    )
    return list(result.scalars().all())
