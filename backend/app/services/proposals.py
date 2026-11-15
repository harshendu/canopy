"""Change proposals: validation, before-snapshots, and the apply engine.

A proposal is a batch of staged mutations (`ProposalItem`s) an agent assembled — usually
from external signal (Slack/email/meetings/Jira/GitHub/Drive) — that a human reviews and
**applies** from the UI. This module is the whole write path:

- **Whitelisted payloads.** Every (entity, action) pair has an explicit field whitelist
  and a Pydantic validator (reusing the API's own request schemas where they exist), so a
  staged payload can never mass-assign arbitrary columns. `Task.status` is stageable only on
  canopy-owned tasks (and must name a column of the project's workflow); a mirrored task's
  status belongs to its tracker and is refused (the source-of-truth rule holds). Apply writes
  it through `workflow.record_transition`, like every status change.
- **Scope containment.** A proposal is scoped to one project or initiative; every item
  must target that scope (a proposal reviewed under project A cannot mutate project B).
- **Refs.** A create item may declare a `ref` handle; later items may point at it with
  `*_ref` payload keys (`parent_ref`, `predecessor_ref`, `task_ref`, …) so a proposal can
  stage "create phase → create task under it → link them" before any ids exist.
- **Before snapshots** are captured at stage time for update/resolve items; the same
  snapshot recomputed at read time shows the reviewer live drift since staging.
- **Apply** is all-or-nothing: validate every included item, then execute in order in one
  transaction, replan the schedule-affected projects, and publish live-refresh events.
- **Revise** rewrites an open proposal in place (add / rewrite / remove items) — the
  conversational co-review loop: the author's session amends the staged set while the human
  watches it change in the UI. It may never make the proposal *less* valid than it was.

The before/after **plan preview** the reviewer toggles lives in `proposal_preview.py`.

Called from `app/api/v1/proposals.py`; the review/commit endpoints there are human-only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.core.events import publish
from app.models.architecture import ArchitectureDecision
from app.models.base import (
    CANOPY_OWNER,
    ADRStatus,
    DocLinkEntity,
    DocRelation,
    DocScope,
    DocSource,
    DocVisibility,
    OutcomeScope,
    ProposalAction,
    ProposalEntity,
    ProposalScope,
    ProposalStatus,
    Reversibility,
    RiskScope,
    RiskStatus,
    SprintState,
    StatusSource,
    utcnow,
)
from app.models.doc import DocLink, DocReference
from app.models.outcome import Outcome
from app.models.policy import DeliveryRule
from app.models.project import Blocker, Dependency, Initiative, Milestone, Project, Task
from app.models.proposal import Proposal, ProposalItem
from app.models.risk_register import RiskItem
from app.models.spec import Spec
from app.models.sprint import Sprint
from app.models.team import Engineer
from app.models.user import User
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
from app.schemas.proposal import ProposalReviseRequest
from app.services import design_docs, sprint_service, workflow
from app.services.features import feature_enabled
from app.services.metadata import normalize_tags
from app.services.org import project_team_id
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


@dataclass
class RevisionIssue:
    """A problem a revision would introduce. Exactly one locator is set: `item_id` for a
    staged item, or `add_index` for the n-th entry of the revision's `add_items`."""

    error: str
    item_id: int | None = None
    add_index: int | None = None


class RevisionRejectedError(Exception):
    """The revision would leave the proposal less valid than it found it; nothing changed."""

    def __init__(self, issues: list[RevisionIssue]) -> None:
        super().__init__("; ".join(i.error for i in issues))
        self.issues = issues


# --- payload validators (partial-update shapes the REST API doesn't need) ---


class _TaskPatch(TaskUpdate):
    """A staged task update may also move the task to another workflow column, or into/out of
    a sprint (null = back to the backlog) — only where canopy owns the status / the sprint
    membership (checked against the live task in `_check_target`)."""

    status: str | None = None
    sprint_id: int | None = None


class _MilestonePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    description: str | None = None
    target_date: date | None = None
    status: str | None = None  # planned | at_risk | hit | missed


class _DocLinkPayload(BaseModel):
    doc_id: int
    entity_type: DocLinkEntity
    entity_id: int
    relation: DocRelation = DocRelation.reference


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


class _RulePayload(BaseModel):
    """A project rule a session suggests (Phase 4: recurring review notes). Rules stay
    human-written — the proposal is how a person accepts one."""

    model_config = ConfigDict(extra="forbid")
    scope_level: Literal["project"] = "project"
    scope_id: int
    key: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_.-]*$")
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(default="", max_length=800)
    kind: Literal["guidance", "attestation"] = "guidance"
    enforcement: Literal["off", "warn", "block"] = "warn"
    roles: list[str] = []
    tags: list[str] = []
    paths: list[str] = []


# Payload field whitelists per (entity, action). `*_ref` keys are the intra-proposal
# reference alternative for the matching `*_id` key and are validated separately.
_ALLOWED_FIELDS: dict[tuple[ProposalEntity, ProposalAction], frozenset[str]] = {
    (ProposalEntity.task, ProposalAction.create): frozenset(
        {
            "project_id", "parent_id", "name", "description", "type", "start", "duration",
            "constraint_start", "deadline", "assignee_engineer_id", "spec_id", "tags",
            "estimate_optimistic", "estimate_likely", "estimate_pessimistic", "status",
            "story_points",
        }
    ),
    (ProposalEntity.task, ProposalAction.update): frozenset(
        {
            "name", "description", "parent_id", "start", "duration", "constraint_start",
            "deadline", "percent_complete", "assignee_engineer_id", "spec_id", "tags",
            "estimate_optimistic", "estimate_likely", "estimate_pessimistic", "status",
            "sprint_id", "story_points",
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
        {"scope_level", "scope_id", "url", "kind", "title", "owner_engineer_id", "visibility"}
    ),
    # Link a tracked design doc (or one staged in this proposal) to the work it serves.
    (ProposalEntity.doc_link, ProposalAction.create): frozenset(
        {"doc_id", "entity_type", "entity_id", "relation"}
    ),
    (ProposalEntity.rule, ProposalAction.create): frozenset(
        {"scope_level", "scope_id", "key", "title", "body", "kind", "enforcement", "roles",
         "tags", "paths"}
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
    (ProposalEntity.doc_link, ProposalAction.create): {
        "doc_ref": "doc_id",  # a doc_reference.create item in this proposal
        "entity_ref": "entity_id",  # a task / milestone / decision / risk / outcome created here
    },
}

# The staged entity a `doc_link.entity_ref` may name, per link target type.
_LINKABLE_REF_ENTITIES: dict[str, ProposalEntity] = {
    DocLinkEntity.task.value: ProposalEntity.task,
    DocLinkEntity.milestone.value: ProposalEntity.milestone,
    DocLinkEntity.decision.value: ProposalEntity.decision,
    DocLinkEntity.risk.value: ProposalEntity.risk,
    DocLinkEntity.outcome.value: ProposalEntity.outcome,
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
    ProposalEntity.rule: "title",
    ProposalEntity.doc_link: "relation",
}

_RISK_TERMINAL = {RiskStatus.resolved, RiskStatus.accepted, RiskStatus.occurred}

# Whitelisted fields a reviewer may NOT introduce through an inline override: they decide
# *where* the change lands (scope / structure) rather than a value on it, or are not plain
# scalars. A field the agent already staged stays editable under the older rule.
_NOT_ADDABLE: frozenset[str] = frozenset(
    {
        "project_id", "scope_level", "scope_id", "task_id", "parent_id", "predecessor_id",
        "successor_id", "blocking_task_id", "type", "start", "spec_id", "tags",
        "alternatives", "percent_complete",
    }
)

# Scope plumbing the stager fills in (which project / what the entity hangs off). Never a
# reviewable value: moving a change to another scope is a different proposal.
_SCOPE_FIELDS: frozenset[str] = frozenset({"project_id", "scope_level", "scope_id"})

# Payload fields that hold another entity's id → the lookup bucket that names it, so the
# review UI (and an agent reading the proposal) sees "Dana Lee", not 14.
_ID_FIELD_KINDS: dict[str, str] = {
    "parent_id": "task",
    "predecessor_id": "task",
    "successor_id": "task",
    "task_id": "task",
    "blocking_task_id": "task",
    "assignee_engineer_id": "engineer",
    "owner_engineer_id": "engineer",
    "raised_by_engineer_id": "engineer",
    "decision_owner_id": "engineer",
    "proposed_by_id": "engineer",
    "project_id": "project",
    "spec_id": "spec",
    "doc_id": "doc",
}

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
        ProposalEntity.rule: DeliveryRule,
        ProposalEntity.doc_link: DocLink,
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


def effective_payload(item: ProposalItem) -> dict[str, Any]:
    """The values that will actually be applied: the agent's `payload` with the reviewer's
    `overrides` layered on top (§AA2/T17 audit-preserving override). `payload` itself is never
    mutated — it stays the original proposal for the audit trail — so this merge is the single
    place validation and apply read from."""
    return {**(item.payload or {}), **(item.overrides or {})}


def validate_effective(item: ProposalItem) -> None:
    """Shape/whitelist/coerce-check the effective (overridden) payload so a bad inline override is
    rejected at edit time, not deferred to apply. Raises ValueError on any problem."""
    _validate_payload(item.entity_type, item.action, effective_payload(item))


def coerced_fields(item: ProposalItem) -> dict[str, Any]:
    """The item's effective payload, validated and type-coerced (dates are `date`s, enums are
    enums) — exactly what apply would write. Raises ValueError when the item is invalid."""
    return _validate_payload(item.entity_type, item.action, effective_payload(item))


def addable_fields(item: ProposalItem) -> list[str]:
    """Whitelisted fields the proposal does not set yet that a reviewer may add inline (e.g.
    give a staged task an assignee or a deadline) instead of rejecting and restaging."""
    key = (item.entity_type, item.action)
    allowed = _ALLOWED_FIELDS.get(key, frozenset())
    taken = set(item.payload or {}) | set(item.overrides or {})
    # A field already expressed through a `*_ref` handle is taken too.
    for ref_key, id_key in _REF_KEYS.get(key, {}).items():
        if ref_key in taken:
            taken.add(id_key)
    return sorted(allowed - taken - _NOT_ADDABLE)


def overridable_fields(item: ProposalItem) -> set[str]:
    """Every field an inline override may touch on this item: what the proposal already sets
    (minus structural `*_ref` handles and scope plumbing) plus the reviewer-addable ones."""
    key = (item.entity_type, item.action)
    allowed = _ALLOWED_FIELDS.get(key, frozenset())
    staged = {k for k in (item.payload or {}) if not k.endswith("_ref")} - _SCOPE_FIELDS
    return staged | set(allowed - _NOT_ADDABLE)


def drifted(before: dict[str, Any] | None, current: dict[str, Any] | None) -> bool:
    """Did the live target move since the stage-time snapshot? True when it vanished, or any
    field both snapshots hold now differs. Fields only one side holds are ignored (a reviewer
    may add or drop an override field after the snapshot was taken). Pure."""
    if current is None:
        return True
    if before is None:
        return False
    return any(key in before and before[key] != value for key, value in current.items())


def order_by_refs(items: list[ProposalItem]) -> list[ProposalItem]:
    """Stable reorder so every item comes after the create items whose `ref` it points at —
    apply executes in order, so a handle must exist before it is used. Lets a revision add a
    phase late and re-point earlier staged tasks under it without the author hand-sorting.
    A reference cycle is left as-is for validation to report. Pure."""
    declared: dict[str, ProposalItem] = {}
    for item in items:
        if item.ref and item.action == ProposalAction.create:
            declared.setdefault(item.ref, item)
    placed: list[ProposalItem] = []
    done: set[int] = set()

    def place(item: ProposalItem, trail: set[int]) -> None:
        if id(item) in done or id(item) in trail:
            return
        trail.add(id(item))
        for ref_key in _REF_KEYS.get((item.entity_type, item.action), {}):
            handle = (item.payload or {}).get(ref_key)
            target = declared.get(handle) if isinstance(handle, str) else None
            if target is not None and target is not item:
                place(target, trail)
        done.add(id(item))
        placed.append(item)

    for item in items:
        place(item, set())
    return placed


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
        return _TaskPatch.model_validate(concrete).model_dump(exclude_unset=True)
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
    if entity == ProposalEntity.rule:
        return _RulePayload.model_validate(concrete).model_dump()
    if entity == ProposalEntity.doc_link:
        return _DocLinkPayload.model_validate(concrete).model_dump()
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
        if entity == ProposalEntity.rule and scope_level == ProposalScope.project:
            payload.setdefault("scope_level", "project")
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
    # what each ref handle names, for links that must point at the right kind of entity
    ref_types = {
        item.ref: item.entity_type
        for item in items
        if item.ref and item.action == ProposalAction.create
    }

    for index, item in enumerate(items):
        try:
            _inject_scope_defaults(item, scope_level, scope_id)
            fields = _validate_payload(item.entity_type, item.action, effective_payload(item))
            await _check_people(session, fields)
            if item.action == ProposalAction.create:
                if item.entity_id is not None:
                    raise ValueError("a create item must not set entity_id")
                await _check_create(
                    session, item, fields, projects, declared_refs, scope_level, scope_id,
                    ref_types,
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


async def _check_people(session: AsyncSession, fields: dict[str, Any]) -> None:
    """Every engineer a payload names (assignee, owner, …) must exist — otherwise apply would
    die on the foreign key (PG/MySQL) or silently orphan the reference (SQLite)."""
    for key, kind in _ID_FIELD_KINDS.items():
        value = fields.get(key)
        if kind != "engineer" or value is None:
            continue
        if await session.get(Engineer, int(value)) is None:
            raise ValueError(f"{key} {value} is not a known engineer")


async def _check_create(
    session: AsyncSession,
    item: ProposalItem,
    fields: dict[str, Any],
    projects: set[int],
    declared_refs: set[str],
    scope_level: ProposalScope,
    scope_id: int,
    ref_types: dict[str, ProposalEntity] | None = None,
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
        if fields.get("status") is not None:
            await _check_status(session, int(fields["project_id"]), str(fields["status"]))
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
        if entity == ProposalEntity.doc_reference:
            await _check_doc_shareable(session, fields)
    elif entity == ProposalEntity.decision:
        if fields.get("project_id") not in projects:
            raise ValueError("decision project is outside this proposal's scope")
        if not str(fields.get("title") or "").strip():
            raise ValueError("decision title is required")
    elif entity == ProposalEntity.rule:
        if not await feature_enabled(session, "ai.stage_policy"):
            raise ValueError("rules are switched off (feature ai.stage_policy)")
        if fields.get("scope_id") not in projects:
            raise ValueError("a proposed rule belongs to a project in this proposal's scope")
        await _check_rule_key(session, int(fields["scope_id"]), str(fields["key"]))
    elif entity == ProposalEntity.doc_link:
        await _check_doc_link(
            session, payload, fields, projects, scope_level, scope_id, ref_types or {}
        )


async def _check_rule_key(session: AsyncSession, project_id: int, key: str) -> None:
    existing = (await session.execute(
        select(DeliveryRule.id).where(
            DeliveryRule.scope_level == "project", DeliveryRule.scope_id == project_id,
            DeliveryRule.key == key)
    )).scalars().first()
    if existing is not None:
        raise ValueError(f"the project already has a rule {key!r} — propose a new key")


async def _check_doc_link(
    session: AsyncSession,
    payload: dict[str, Any],
    fields: dict[str, Any],
    projects: set[int],
    scope_level: ProposalScope,
    scope_id: int,
    ref_types: dict[str, ProposalEntity],
) -> None:
    """A staged doc link: the doc is a shared, tracked doc (or a doc staged here), shared in
    Claude; the target is in this proposal's scope (or created by it)."""
    doc_ref = payload.get("doc_ref")
    if doc_ref is not None:
        if ref_types.get(str(doc_ref)) != ProposalEntity.doc_reference:
            raise ValueError(f"doc_ref '{doc_ref}' does not name a doc staged in this proposal")
    else:
        doc = await session.get(DocReference, int(fields["doc_id"]))
        if doc is None or doc.private_to_user_id is not None:
            raise ValueError(f"doc {fields['doc_id']} not found")
        try:
            design_docs.require_shared(doc)
        except design_docs.DocError as exc:
            raise ValueError(exc.message) from exc
    target_type = str(_jsonable(fields.get("entity_type")))
    entity_ref = payload.get("entity_ref")
    if entity_ref is not None:
        wanted = _LINKABLE_REF_ENTITIES.get(target_type)
        if wanted is None or ref_types.get(str(entity_ref)) != wanted:
            raise ValueError(
                f"entity_ref '{entity_ref}' does not name a {target_type} staged in this proposal"
            )
        return
    try:
        target = await design_docs.resolve_entity(
            session, DocLinkEntity(target_type), int(fields["entity_id"])
        )
    except design_docs.DocError as exc:
        raise ValueError(f"{target_type} {fields.get('entity_id')} not found") from exc
    in_scope = (
        target.project_id in projects
        if target.project_id is not None
        else scope_level == ProposalScope.initiative and target.initiative_id == scope_id
    )
    if not in_scope:
        raise ValueError(
            f"{target_type} {fields.get('entity_id')} is outside this proposal's scope"
        )


async def _check_status(session: AsyncSession, project_id: int, status: str) -> None:
    """A staged status must be a column of the project's workflow, and canopy must be allowed
    to own status at all (feature `tracking.native`)."""
    if not await feature_enabled(session, "tracking.native"):
        raise ValueError("canopy-owned status is disabled (feature tracking.native)")
    project = await session.get(Project, project_id)
    if project is None:
        raise ValueError(f"project {project_id} not found")
    view = await workflow.resolve_workflow(session, project)
    if view.column(status) is None:
        names = ", ".join(c.name for c in view.columns)
        raise ValueError(f"status {status!r} is not a column of this project's workflow ({names})")


async def _check_sprint(session: AsyncSession, task: Task, sprint_id: int | None) -> None:
    """A staged sprint change: canopy must own the task's membership, and the sprint must be a
    live sprint of the task's team (null = back to the backlog)."""
    owner = await sprint_service.membership_owner(session, task)
    if owner != CANOPY_OWNER:
        raise ValueError(f"task {task.id}'s sprint is set in {owner} and is not stageable")
    if sprint_id is None:
        return
    sprint = await session.get(Sprint, int(sprint_id))
    project = await session.get(Project, task.project_id)
    team_id = await project_team_id(session, project) if project is not None else None
    if sprint is None or sprint.team_id != team_id:
        raise ValueError(f"sprint {sprint_id} is not a sprint of this task's team")
    if sprint.state == SprintState.completed.value:
        raise ValueError(f"sprint {sprint_id} is completed")


async def _check_doc_shareable(session: AsyncSession, fields: dict[str, Any]) -> None:
    """The sharing rule for a staged doc link: a Claude doc must be shared in Claude before it
    joins shared work (USER_FLOWS §V5)."""
    try:
        info = design_docs.classify(str(fields.get("url") or ""), strict=False)
        visibility = DocVisibility(str(_jsonable(fields.get("visibility")) or "unknown"))
        await design_docs.require_shareable(session, info, visibility, fields.get("title"))
    except design_docs.DocError as exc:
        raise ValueError(exc.message) from exc
    except ValueError as exc:
        raise ValueError(f"invalid doc link: {exc}") from exc


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
        task = await _task_in_scope(session, entity_id, projects)
        if task is None:
            raise ValueError(f"task {entity_id} not found in scope")
        if fields.get("status") is not None:
            if task.status_owner != CANOPY_OWNER:
                raise ValueError(
                    f"task {entity_id}'s status is owned by {task.status_owner} and is not "
                    "stageable — change it there"
                )
            await _check_status(session, task.project_id, str(fields["status"]))
        if "sprint_id" in fields:
            await _check_sprint(session, task, fields["sprint_id"])
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
    keys = set((item.payload or {}).keys()) | set((item.overrides or {}).keys())
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
    author: str | None = None,
    reviewer_id: int | None = None,
) -> int:
    """Execute one validated item; returns the created/updated entity id and accumulates
    the projects whose schedule must be recomputed."""
    entity, action = item.entity_type, item.action

    if entity == ProposalEntity.task and action == ProposalAction.create:
        fields["tags"] = normalize_tags(list(fields.get("tags") or []))
        staged_status = fields.pop("status", None)
        task = Task(**fields)
        session.add(task)
        await session.flush()
        assert task.id is not None
        try:
            # Its key and first status (the staged one, else the default for its progress).
            await workflow.initialise_native_task(
                session,
                task,
                status=staged_status,
                native_enabled=await feature_enabled(session, "tracking.native"),
                author=author,
            )
        except workflow.TrackingError as exc:
            raise ValueError(exc.message) from exc
        replan.add(task.project_id)
        return task.id

    if entity == ProposalEntity.task and action == ProposalAction.update:
        task = await _require(session, Task, item.entity_id)
        if "tags" in fields and fields["tags"] is not None:
            fields["tags"] = normalize_tags(list(fields["tags"]))
        staged_status = fields.pop("status", None)
        staged_sprint = fields.pop("sprint_id", _UNSET)
        for key, value in fields.items():
            setattr(task, key, value)
        if staged_status is not None:
            await _apply_status(session, task, str(staged_status), author)
        if staged_sprint is not _UNSET:
            sprint = await session.get(Sprint, int(staged_sprint)) if staged_sprint else None
            sprint_service.record_membership(
                session, task, sprint, source=StatusSource.canopy, author=author
            )
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

    if entity == ProposalEntity.rule:
        project_id = int(fields["scope_id"])
        await _check_rule_key(session, project_id, str(fields["key"]))
        rule = DeliveryRule(
            scope_level="project", scope_id=project_id, key=str(fields["key"]),
            title=str(fields["title"]).strip(), body=str(fields.get("body") or "").strip(),
            kind=str(fields.get("kind") or "guidance"),
            enforcement=str(fields.get("enforcement") or "warn"),
            roles=[str(r).strip().lower() for r in fields.get("roles") or [] if str(r).strip()],
            selector={"tags": [str(t).strip().lower() for t in fields.get("tags") or []],
                      "components": [], "paths": [str(p) for p in fields.get("paths") or []]},
            created_by_user_id=reviewer_id,  # the person who accepted it: rules stay theirs
        )
        session.add(rule)
        await session.flush()
        assert rule.id is not None
        return rule.id

    if entity == ProposalEntity.doc_link:
        doc = await _require(session, DocReference, int(fields["doc_id"]))
        try:
            design_docs.require_shared(doc)
        except design_docs.DocError as exc:
            raise ValueError(exc.message) from exc
        link = await design_docs.upsert_link(
            session, doc, DocLinkEntity(str(_jsonable(fields["entity_type"]))),
            int(fields["entity_id"]), DocRelation(str(_jsonable(fields.get("relation"))
                                                     or DocRelation.reference.value)),
        )
        assert link.id is not None
        return link.id

    # doc_reference.create — the shared register-or-link path: one document is one record, and
    # a document already tracked elsewhere gets a link to this scope instead of a copy.
    result = await design_docs.register_core(
        session,
        info=design_docs.classify(str(fields["url"]), strict=False),
        kind=fields.get("kind"),
        title=fields.get("title"),
        scope_level=DocScope(str(_jsonable(fields["scope_level"]))),
        scope_id=int(fields["scope_id"]),
        source=DocSource.agent,
        created_by=None,
        visibility=DocVisibility(str(_jsonable(fields.get("visibility")) or "unknown")),
        owner_engineer_id=fields.get("owner_engineer_id"),
    )
    assert result.doc.id is not None
    return result.doc.id


_UNSET = object()


async def _apply_status(session: AsyncSession, task: Task, status: str, author: str | None) -> None:
    """Move a canopy-owned task to a workflow column through the one status write path."""
    if task.status_owner != CANOPY_OWNER:
        raise ValueError(f"task {task.id}'s status is owned by {task.status_owner}")
    project = await session.get(Project, task.project_id)
    if project is None:
        raise ValueError(f"project {task.project_id} not found")
    column = (await workflow.resolve_workflow(session, project)).column(status)
    if column is None:
        raise ValueError(f"status {status!r} is not a column of this project's workflow")
    workflow.record_transition(
        session,
        task,
        column.name,
        category=column.category,
        source=StatusSource.canopy,
        author=author,
    )


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
    reviewer = await session.get(User, reviewer_user_id) if reviewer_user_id else None
    author = (reviewer.full_name or reviewer.email) if reviewer is not None else None
    for item in included:
        fields = _validate_payload(item.entity_type, item.action, effective_payload(item))
        fields = _resolve_refs(item, fields, refs)
        applied_id = await _apply_item(session, item, fields, replan, author, reviewer_user_id)
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


# --- display lookups ---


def _referenced_ids(items: list[ProposalItem]) -> dict[str, set[int]]:
    """Every entity id the items mention (payload, override, and both snapshots), bucketed
    by lookup kind. Pure."""
    found: dict[str, set[int]] = {}

    def note(kind: str, value: Any) -> None:
        if isinstance(value, int) and not isinstance(value, bool):
            found.setdefault(kind, set()).add(value)

    for item in items:
        for blob in (item.payload, item.overrides, item.before):
            if not blob:
                continue
            for key, value in blob.items():
                kind = _ID_FIELD_KINDS.get(key)
                if kind:
                    note(kind, value)
            level = blob.get("scope_level")
            if level in ("task", "project", "initiative"):
                note(str(level), blob.get("scope_id"))
            # a doc link's target, when a lookup bucket can name it
            target = blob.get("entity_type")
            if item.entity_type == ProposalEntity.doc_link and target in (
                "task", "project", "initiative", "spec"
            ):
                note(str(target), blob.get("entity_id"))
    return found


async def collect_lookups(
    session: AsyncSession, items: list[ProposalItem]
) -> dict[str, dict[str, str]]:
    """Display names for the ids a proposal's items reference: `{kind: {"<id>": name}}`."""
    wanted = _referenced_ids(items)
    lookups: dict[str, dict[str, str]] = {}

    async def names(kind: str, model: type[Any], label: str) -> None:
        ids = wanted.get(kind)
        if not ids:
            return
        rows = await session.execute(select(model).where(col(model.id).in_(sorted(ids))))
        lookups[kind] = {str(row.id): str(getattr(row, label)) for row in rows.scalars().all()}

    await names("task", Task, "name")
    await names("engineer", Engineer, "name")
    await names("spec", Spec, "title")
    if wanted.get("doc"):
        docs = await session.execute(
            select(DocReference).where(
                col(DocReference.id).in_(sorted(wanted["doc"])),
                col(DocReference.private_to_user_id).is_(None),
            )
        )
        lookups["doc"] = {str(r.id): str(r.title or r.url) for r in docs.scalars().all()}
    if wanted.get("project"):
        projects = await session.execute(
            select(Project).where(col(Project.id).in_(sorted(wanted["project"])))
        )
        lookups["project"] = {str(r.id): f"{r.key} · {r.name}" for r in projects.scalars().all()}
    if wanted.get("initiative"):
        initiatives = await session.execute(
            select(Initiative).where(col(Initiative.id).in_(sorted(wanted["initiative"])))
        )
        lookups["initiative"] = {
            str(r.id): f"{r.key} · {r.name}" for r in initiatives.scalars().all()
        }
    return lookups


# --- revise (the conversational co-review loop) ---


async def revise_proposal(
    session: AsyncSession, proposal: Proposal, request: ProposalReviseRequest
) -> None:
    """Rewrite an open proposal in place: remove items, merge new values into staged ones,
    append new ones — then bump `revision` so the reviewer's open page shows what changed.

    The rule is *don't make it worse*: the revised set is re-validated and the revision is
    refused (`RevisionRejectedError`, nothing written) if it introduces any problem that was not
    already there. A pre-existing problem the revision doesn't touch (say, a target that
    vanished after staging) does not block it. A value the author rewrites supersedes the
    reviewer's inline override on that same field; untouched items keep their overrides and
    exclusions. Raises ValueError for a malformed request (unknown item ids, an item both
    updated and removed, or nothing to do)."""
    items = await load_items(session, proposal)
    by_id = {item.id: item for item in items if item.id is not None}
    remove_ids = set(request.remove_item_ids)
    update_ids = [rev.item_id for rev in request.update_items]

    unknown = sorted((remove_ids | set(update_ids)) - set(by_id))
    if unknown:
        raise ValueError(f"no such item(s) in this proposal: {unknown}")
    if remove_ids & set(update_ids):
        raise ValueError("an item cannot be both updated and removed in one revision")
    if len(update_ids) != len(set(update_ids)):
        raise ValueError("each item may be updated only once per revision")
    relabel = request.title is not None or request.summary is not None
    if not (request.add_items or request.update_items or remove_ids or relabel):
        raise ValueError("an empty revision — pass add_items, update_items, remove_item_ids, "
                         "title or summary")

    known_errors = {
        issue.item_id: issue.error
        for issue in await check_items(session, proposal.scope_level, proposal.scope_id, items)
    }

    changed: list[ProposalItem] = []
    for rev in request.update_items:
        item = by_id[rev.item_id]
        payload = dict(item.payload or {})
        for key in rev.remove_fields:
            payload.pop(key, None)
        payload.update(rev.payload)
        # Switching a link between a live id and an intra-proposal ref replaces the other.
        for ref_key, id_key in _REF_KEYS.get((item.entity_type, item.action), {}).items():
            if ref_key in rev.payload:
                payload.pop(id_key, None)
            elif id_key in rev.payload:
                payload.pop(ref_key, None)
        item.payload = payload
        rewritten = set(rev.payload) | set(rev.remove_fields)
        if item.overrides:
            kept = {k: v for k, v in item.overrides.items() if k not in rewritten}
            item.overrides = kept or None
            if not kept:
                item.overridden_by_user_id = None
                item.overridden_at = None
        for attr in ("reason", "source_kind", "source_label", "source_url"):
            if attr in rev.model_fields_set:
                setattr(item, attr, getattr(rev, attr))
        item.error = None
        changed.append(item)

    assert proposal.id is not None
    added = [
        ProposalItem(
            proposal_id=proposal.id,
            entity_type=new.entity_type,
            action=new.action,
            entity_id=new.entity_id,
            ref=new.ref,
            payload=dict(new.payload),
            reason=new.reason,
            source_kind=new.source_kind,
            source_label=new.source_label,
            source_url=new.source_url,
        )
        for new in request.add_items
    ]
    add_index = {id(item): index for index, item in enumerate(added)}

    kept_items = [item for item in items if item.id not in remove_ids]
    if not kept_items and not added:
        raise ValueError("a revision cannot empty the proposal — withdraw it instead")
    sequence = order_by_refs(kept_items + added)

    # Autoflush stays off while validating: the rewritten payloads must not reach the
    # database (even uncommitted) before we know the revision holds.
    with session.no_autoflush:
        after = await check_items(session, proposal.scope_level, proposal.scope_id, sequence)
    introduced: list[RevisionIssue] = []
    for issue in after:
        item = sequence[issue.index]
        if id(item) in add_index:
            introduced.append(RevisionIssue(error=issue.error, add_index=add_index[id(item)]))
        elif known_errors.get(item.id) != issue.error:
            introduced.append(RevisionIssue(error=issue.error, item_id=item.id))
    if introduced:
        await session.rollback()
        raise RevisionRejectedError(introduced)

    proposal.revision += 1
    proposal.revised_at = utcnow()
    proposal.revision_note = request.note
    if request.title is not None:
        proposal.title = request.title
    if request.summary is not None:
        proposal.summary = request.summary
    for item in items:
        if item.id in remove_ids:
            await session.delete(item)
    for order, item in enumerate(sequence):
        item.sort_order = order
    for item in changed + added:
        item.revision = proposal.revision
        item.before = await snapshot_target(session, item)
    session.add_all(added)
    await session.commit()
    await session.refresh(proposal)

    await publish(
        {
            "type": "proposal",
            "proposal_id": proposal.id,
            "status": proposal.status.value,
            "scope_level": proposal.scope_level.value,
            "scope_id": proposal.scope_id,
            "revision": proposal.revision,
        }
    )
