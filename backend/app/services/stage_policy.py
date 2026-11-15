"""Stage policy (pure, unit-tested) — docs/AGENT_EXECUTION.md §9.

A workflow column can carry a **stage policy**: who works it (an agent role, people, or nobody — a
queue), what must be true to enter it (typed **checks**, each `off | warn | block`), which human
decision guards it (a **checkpoint** on the work in it, or a **decision column**), and where work
goes when a verdict fails. This module holds the vocabulary, validation of stored policy
documents, the built-in default pipeline, `evaluate` (the one function the dry run and the real
hand-off both call — preview equals enforcement), the risk **conditions** that decide whether a
person must look, and routing. No database, no clock reads — callers pass facts in.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from app.services import flow

# --------------------------------------------------------------------------- #
# Vocabulary
# --------------------------------------------------------------------------- #

HUMAN = "human"  # `worked_by` of a decision column
ENFORCEMENTS = ("off", "warn", "block")
AUDIENCES = ("agents", "everyone")
OBSERVED = "observed"  # canopy saw the fact for itself (P8)
ATTESTED = "attested"  # an agent or a person stated it

# check name -> (kind of fact, allowed params)
CHECKS: dict[str, tuple[str, frozenset[str]]] = {
    "dependencies_done": (OBSERVED, frozenset()),
    "no_open_blockers": (OBSERVED, frozenset()),
    "spec_approved": (OBSERVED, frozenset()),
    "artifact": (OBSERVED, frozenset({"kind"})),
    "plan_approved": (OBSERVED, frozenset()),
    "gate_approved": (OBSERVED, frozenset({"kind"})),
    "pr_linked": (OBSERVED, frozenset({"state"})),
    "pr_checks": (OBSERVED, frozenset({"state"})),
    "pr_approved": (OBSERVED, frozenset()),
    "pr_size": (OBSERVED, frozenset({"max_changed_lines"})),
    "verdict": (ATTESTED, frozenset({"kind", "in"})),
    "criteria_met": (ATTESTED, frozenset()),
    "attestations_complete": (ATTESTED, frozenset()),
    "distinct_actor": (OBSERVED, frozenset({"role"})),
    "distinct_issuer": (OBSERVED, frozenset({"role"})),
}

# Checks about *who works* a column, evaluated when a session claims work in it (and when it
# submits its verdict) — never when an earlier role's hand-off moves the task in.
CLAIM_TIME_CHECKS = frozenset({"distinct_actor", "distinct_issuer"})

# A plan's declared change classes that make a change a one-way door on their own.
ONE_WAY_CHANGE_CLASSES = frozenset(
    {"schema_migration", "public_api", "security_boundary", "data_deletion"}
)
CHANGE_CLASSES = ONE_WAY_CHANGE_CLASSES | {"infrastructure", "dependency_upgrade"}
SIMPLE_CONDITIONS = frozenset(
    {"one_way_door", "high_criticality", "unsettled_decision", "no_spec", "low_confidence"}
)
APPROVER_RULES = frozenset(
    {"project_planners", "project_owner", "assignee", "initiative_leads", "team_directors",
     "engineers"}
)
SATISFIED_BY = frozenset({"canopy", "pr_approval", "pr_merge"})
# What a stage's session hands off: the implementer's hand-off, or a review / QA verdict.
ARTIFACTS = ("handoff", "review", "qa_report")
_ROLE_ARTIFACT = {"reviewer": "review", "qa": "qa_report"}
CHECKPOINTS = ("plan", "handoff")

DEFAULT_LEASE_MINUTES = 30
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_MAX_REWORK = 3
DEFAULT_REMIND_HOURS = 4
DEFAULT_ESCALATE_HOURS = 24
# The risk-based plan checkpoint of the agentic-delivery template (open decision D2).
DEFAULT_PLAN_APPROVAL_WHEN: tuple[str, ...] = (
    "one_way_door",
    "unsettled_decision",
    "no_spec",
    "low_confidence",
    "probation:5",
)


class PolicyError(ValueError):
    """A stage policy document that cannot be stored (422 `policy_invalid`)."""

    def __init__(self, message: str, *, column: str | None = None) -> None:
        super().__init__(message)
        self.column = column


@dataclass(frozen=True)
class CheckSpec:
    check: str
    params: Mapping[str, Any] = field(default_factory=dict)
    enforcement: str = "block"
    applies_to: str = "agents"

    def to_doc(self) -> dict[str, Any]:
        doc: dict[str, Any] = {"check": self.check, "enforcement": self.enforcement}
        if self.params:
            doc["params"] = dict(self.params)
        if self.applies_to != "agents":
            doc["applies_to"] = self.applies_to
        return doc

    def label(self) -> str:
        if not self.params:
            return self.check
        return f"{self.check}:" + ",".join(str(v) for v in self.params.values())


@dataclass
class DecisionSpec:
    """Who decides, when, and where each answer sends the task."""

    kind: str = "signoff"
    when: list[str] = field(default_factory=lambda: ["always"])
    approvers: str = "project_planners"
    approver_engineer_ids: list[int] = field(default_factory=list)
    exclude_requester: bool = True
    satisfied_by: list[str] = field(default_factory=lambda: ["canopy"])
    remind_after_hours: int = DEFAULT_REMIND_HOURS
    escalate_after_hours: int = DEFAULT_ESCALATE_HOURS
    on_approve: str | None = None
    on_changes: str | None = None
    on_reject: str | None = None

    def to_doc(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "when": "always" if self.when == ["always"] else list(self.when),
            "approvers": self.approvers,
            **({"approver_engineer_ids": self.approver_engineer_ids}
               if self.approver_engineer_ids else {}),
            "exclude_requester": self.exclude_requester,
            "satisfied_by": list(self.satisfied_by),
            "remind_after_hours": self.remind_after_hours,
            "escalate_after_hours": self.escalate_after_hours,
            "on_approve": self.on_approve,
            "on_changes": self.on_changes,
            "on_reject": self.on_reject,
        }


@dataclass
class CheckpointSpec:
    required: bool = True
    approval_when: list[str] = field(default_factory=lambda: list(DEFAULT_PLAN_APPROVAL_WHEN))
    decision: DecisionSpec | None = None
    # Graduated autonomy (Phase 4): change classes people pre-approved — `tag:<tag>` — whose
    # plans / hand-offs skip the person except for the safety floor (PRE_APPROVAL_FLOOR).
    pre_approved: list[str] = field(default_factory=list)

    def to_doc(self) -> dict[str, Any]:
        doc: dict[str, Any] = {"required": self.required, "approval_when": self.approval_when}
        if self.decision is not None:
            doc["decision"] = self.decision.to_doc()
        if self.pre_approved:
            doc["pre_approved"] = list(self.pre_approved)
        return doc


@dataclass
class StageDef:
    """One column of a pipeline, with its policy (a column without one has every default)."""

    status_name: str
    category: str
    position: int
    worked_by: str | None = None  # None (a queue / terminal column) | "human" | an agent role
    artifact: str | None = None  # what its session hands off; None = by role (see `hands_off`)
    instructions: str = ""
    pulls_from: list[str] | None = None  # None = the queue column just before, if any
    enter_checks: list[CheckSpec] = field(default_factory=list)
    on_changes: str | None = None  # where a failed verdict sends the task
    decision: DecisionSpec | None = None  # set on a decision column
    checkpoints: dict[str, CheckpointSpec] = field(default_factory=dict)
    lease_minutes: int = DEFAULT_LEASE_MINUTES
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    max_rework: int = DEFAULT_MAX_REWORK
    has_policy: bool = False
    source: str = "none"  # policy | default | none

    @property
    def key(self) -> str:
        return self.status_name.casefold()

    @property
    def hands_off(self) -> str:
        """The artifact a session working this stage submits: its policy's `artifact`, else by
        role — a `reviewer` submits a review, `qa` a QA report, any other role a hand-off. A
        claim can only submit this kind (a reviewer token can't hand off code, §18.2)."""
        if self.artifact:
            return self.artifact
        return _ROLE_ARTIFACT.get(self.worked_by or "", "handoff")

    @property
    def is_agent_stage(self) -> bool:
        return self.worked_by is not None and self.worked_by != HUMAN

    @property
    def is_decision_column(self) -> bool:
        return self.worked_by == HUMAN

    @property
    def closed(self) -> bool:
        return self.category in (flow.DONE, flow.CANCELLED)

    def policy_doc(self) -> dict[str, Any]:
        """The stored form of this column's policy."""
        return {
            "worked_by": self.worked_by,
            "artifact": self.artifact,
            "instructions": self.instructions,
            "pulls_from": self.pulls_from,
            "enter": {"checks": [c.to_doc() for c in self.enter_checks]},
            "on_changes": self.on_changes,
            "decision": self.decision.to_doc() if self.decision is not None else None,
            "checkpoints": {k: v.to_doc() for k, v in self.checkpoints.items()},
            "lease_minutes": self.lease_minutes,
            "max_attempts": self.max_attempts,
            "max_rework": self.max_rework,
        }


@dataclass
class Pipeline:
    """A project's columns in order, each with its stage definition."""

    stages: list[StageDef]
    configured: bool = False  # True when stored policies define it (else the built-in default)

    def stage(self, name: str | None) -> StageDef | None:
        if name is None:
            return None
        key = name.strip().casefold()
        return next((s for s in self.stages if s.key == key), None)

    def stages_for(self, role: str) -> list[StageDef]:
        return [s for s in self.stages if s.worked_by == role]

    def roles(self) -> list[str]:
        out: list[str] = []
        for s in self.stages:
            if s.is_agent_stage and s.worked_by not in out:
                out.append(str(s.worked_by))
        return out

    def feeders(self, stage: StageDef) -> list[StageDef]:
        """The columns a stage pulls new work from: `pulls_from`, else the queue column just
        before it (a column nobody works that is still open)."""
        if stage.pulls_from is not None:
            return [s for name in stage.pulls_from if (s := self.stage(name)) is not None]
        before = [s for s in self.stages if s.position < stage.position]
        if not before:
            return []
        prev = max(before, key=lambda s: s.position)
        if prev.worked_by is None and not prev.closed:
            return [prev]
        return []

    def next_after(self, stage: StageDef) -> StageDef | None:
        """Where a hand-off goes by default: the next open-or-done column after this one."""
        later = sorted(
            (
                s
                for s in self.stages
                if s.position > stage.position and s.category != flow.CANCELLED
            ),
            key=lambda s: s.position,
        )
        return later[0] if later else None

    def first_of(self, category: str) -> StageDef | None:
        return next(
            (s for s in sorted(self.stages, key=lambda s: s.position) if s.category == category),
            None,
        )

    def rework_target(self, stage: StageDef) -> StageDef | None:
        """Where a failed verdict / requested changes send work from `stage`: its `on_changes`,
        else the nearest earlier column worked by *another* agent role."""
        if stage.on_changes:
            return self.stage(stage.on_changes)
        earlier = sorted(
            (s for s in self.stages if s.position < stage.position and s.is_agent_stage
             and s.worked_by != stage.worked_by),
            key=lambda s: s.position,
            reverse=True,
        )
        return earlier[0] if earlier else None


# --------------------------------------------------------------------------- #
# Building pipelines
# --------------------------------------------------------------------------- #


def bare_stages(columns: Sequence[flow.ColumnDef]) -> list[StageDef]:
    return [
        StageDef(status_name=c.name, category=c.category, position=c.position)
        for c in sorted(columns, key=lambda c: c.position)
    ]


def default_pipeline(columns: Sequence[flow.ColumnDef]) -> Pipeline:
    """The built-in default for a workflow nobody configured (§6.2): the first `in_progress`
    column is the implementer's stage, fed by the last `todo` column before it. The column after
    it asks for a hand-off and warns when no PR is linked. Nothing else is agent-worked."""
    stages = bare_stages(columns)
    work = next((s for s in stages if s.category == flow.IN_PROGRESS), None)
    if work is None:
        return Pipeline(stages=stages)
    work.worked_by = "implementer"
    work.source = "default"
    work.instructions = (
        "Implement the task: plan first (submit_plan), keep the change small, open a pull "
        "request titled with the task key, then hand off with submit_work."
    )
    todo_before = [s for s in stages if s.position < work.position and s.category == flow.TODO]
    work.pulls_from = [todo_before[-1].status_name] if todo_before else []
    nxt = Pipeline(stages=stages).next_after(work)
    if nxt is not None:
        nxt.source = "default"
        nxt.enter_checks = [
            CheckSpec("artifact", {"kind": "handoff"}, "block"),
            CheckSpec("pr_linked", {}, "warn"),
        ]
    return Pipeline(stages=stages, configured=False)


def pipeline_from_policies(
    columns: Sequence[flow.ColumnDef],
    policies: Mapping[str, Mapping[str, Any]],
    *,
    strict: bool = True,
) -> Pipeline:
    """A pipeline from stored policy documents keyed by column name (case-insensitive). With no
    policies at all, the built-in default applies; a stored policy for a column that no longer
    exists is ignored. `strict` raises PolicyError on an invalid document (saving); otherwise
    that column simply has no policy (loading — a stale document never breaks a board)."""
    if not policies:
        return default_pipeline(columns)
    stages = bare_stages(columns)
    by_key = {k.strip().casefold(): v for k, v in policies.items()}
    names = [s.status_name for s in stages]
    for index, stage in enumerate(stages):
        doc = by_key.get(stage.key)
        if doc is None:
            continue
        candidate = replace(stage)
        try:
            apply_policy_doc(candidate, doc, names)
        except PolicyError:
            if strict:
                raise
            continue
        stages[index] = candidate
    return Pipeline(stages=stages, configured=True)


# --------------------------------------------------------------------------- #
# Validation of stored documents
# --------------------------------------------------------------------------- #


def _column_ref(value: Any, names: Sequence[str], where: str, column: str) -> str | None:
    if value is None or value == "":
        return None
    keys = {n.casefold(): n for n in names}
    found = keys.get(str(value).strip().casefold())
    if found is None:
        raise PolicyError(f"{where}: {value!r} is not a column of this workflow", column=column)
    return found


def _int(value: Any, where: str, column: str, *, lo: int, hi: int, default: int) -> int:
    if value is None:
        return default
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise PolicyError(f"{where} must be a whole number", column=column) from exc
    if not lo <= number <= hi:
        raise PolicyError(f"{where} must be between {lo} and {hi}", column=column)
    return number


def parse_check(doc: Mapping[str, Any], column: str) -> CheckSpec:
    name = str(doc.get("check") or "").strip()
    if name not in CHECKS:
        raise PolicyError(f"Unknown check {name!r}", column=column)
    params = dict(doc.get("params") or {})
    allowed = CHECKS[name][1]
    unknown = set(params) - allowed
    if unknown:
        raise PolicyError(f"Check {name!r} takes no parameter {sorted(unknown)}", column=column)
    enforcement = str(doc.get("enforcement") or "block")
    if enforcement not in ENFORCEMENTS:
        raise PolicyError(f"Check {name!r}: enforcement must be off|warn|block", column=column)
    applies_to = str(doc.get("applies_to") or "agents")
    if applies_to not in AUDIENCES:
        raise PolicyError(f"Check {name!r}: applies_to must be agents|everyone", column=column)
    if name in ("artifact", "verdict") and not params.get("kind"):
        raise PolicyError(f"Check {name!r} needs params.kind", column=column)
    if name == "verdict":
        allowed_verdicts = params.get("in") or ["pass"]
        if not isinstance(allowed_verdicts, list) or not set(allowed_verdicts) <= {
            "pass", "concerns", "fail",
        }:
            raise PolicyError("Check 'verdict': params.in must list pass|concerns|fail",
                              column=column)
        params["in"] = list(allowed_verdicts)
    if name == "pr_size":
        params["max_changed_lines"] = _int(
            params.get("max_changed_lines"), "pr_size max_changed_lines", column,
            lo=1, hi=100000, default=400,
        )
    if name in ("distinct_actor", "distinct_issuer") and not params.get("role"):
        raise PolicyError(f"Check {name!r} needs params.role", column=column)
    return CheckSpec(check=name, params=params, enforcement=enforcement, applies_to=applies_to)


def validate_conditions(values: Any, column: str) -> list[str]:
    if values in (None, "always"):
        return ["always"]
    if values == "never":
        return ["never"]
    if not isinstance(values, list):
        raise PolicyError("Conditions must be 'always', 'never' or a list", column=column)
    out: list[str] = []
    for raw in values:
        cond = str(raw).strip()
        head, _, arg = cond.partition(":")
        known = (
            cond in ("always", "never")
            or (head in SIMPLE_CONDITIONS and not arg)
            or (head == "probation" and arg.isdigit())
            or (head == "tag" and bool(arg))
            or head == "large_change"
        )
        if not known:
            raise PolicyError(f"Unknown condition {cond!r}", column=column)
        out.append(cond)
    return out or ["never"]


def parse_decision(doc: Mapping[str, Any], names: Sequence[str], column: str) -> DecisionSpec:
    approvers = str(doc.get("approvers") or "project_planners")
    if approvers not in APPROVER_RULES:
        raise PolicyError(f"approvers must be one of {sorted(APPROVER_RULES)}", column=column)
    satisfied = [str(s) for s in (doc.get("satisfied_by") or ["canopy"])]
    if not set(satisfied) <= SATISFIED_BY or "canopy" not in satisfied:
        raise PolicyError("satisfied_by lists canopy, and may add pr_approval / pr_merge",
                          column=column)
    ids = [int(i) for i in doc.get("approver_engineer_ids") or []]
    if approvers == "engineers" and not ids:
        raise PolicyError("approvers 'engineers' needs approver_engineer_ids", column=column)
    return DecisionSpec(
        kind=str(doc.get("kind") or "signoff").strip() or "signoff",
        when=validate_conditions(doc.get("when"), column),
        approvers=approvers,
        approver_engineer_ids=ids,
        exclude_requester=bool(doc.get("exclude_requester", True)),
        satisfied_by=satisfied,
        remind_after_hours=_int(doc.get("remind_after_hours"), "remind_after_hours", column,
                                lo=1, hi=24 * 30, default=DEFAULT_REMIND_HOURS),
        escalate_after_hours=_int(doc.get("escalate_after_hours"), "escalate_after_hours",
                                  column, lo=1, hi=24 * 60, default=DEFAULT_ESCALATE_HOURS),
        on_approve=_column_ref(doc.get("on_approve"), names, "on_approve", column),
        on_changes=_column_ref(doc.get("on_changes"), names, "on_changes", column),
        on_reject=_column_ref(doc.get("on_reject"), names, "on_reject", column),
    )


def apply_policy_doc(stage: StageDef, doc: Mapping[str, Any], names: Sequence[str]) -> None:
    """Validate one stored policy document and apply it to `stage` (raises PolicyError)."""
    column = stage.status_name
    worked_by = doc.get("worked_by")
    if worked_by is not None:
        worked_by = str(worked_by).strip().lower() or None
    if worked_by is not None and worked_by != HUMAN:
        from app.services.agent_tokens import ROLE_KEY_RE

        if not ROLE_KEY_RE.match(worked_by):
            raise PolicyError(f"worked_by {worked_by!r} is not a role key", column=column)
    if worked_by is not None and stage.closed:
        raise PolicyError("A done or cancelled column cannot be worked", column=column)
    stage.worked_by = worked_by
    artifact = doc.get("artifact")
    if artifact not in (None, ""):
        artifact = str(artifact).strip()
        if artifact not in ARTIFACTS:
            raise PolicyError("artifact must be handoff | review | qa_report", column=column)
        if not stage.is_agent_stage:
            raise PolicyError("Only a column an agent role works hands something off",
                              column=column)
        stage.artifact = artifact
    else:
        stage.artifact = None
    stage.instructions = str(doc.get("instructions") or "")[:8000]
    pulls = doc.get("pulls_from")
    if pulls is not None:
        if not isinstance(pulls, list):
            raise PolicyError("pulls_from must be a list of column names", column=column)
        stage.pulls_from = [
            name for raw in pulls
            if (name := _column_ref(raw, names, "pulls_from", column)) is not None
        ]
    else:
        stage.pulls_from = None
    enter = doc.get("enter") or {}
    stage.enter_checks = [parse_check(c, column) for c in (enter.get("checks") or [])]
    stage.on_changes = _column_ref(doc.get("on_changes"), names, "on_changes", column)
    decision = doc.get("decision")
    stage.decision = parse_decision(decision, names, column) if decision else None
    if stage.decision is not None and worked_by != HUMAN:
        raise PolicyError("Only a decision column (worked_by 'human') has a decision",
                          column=column)
    if worked_by == HUMAN and stage.decision is None:
        stage.decision = DecisionSpec()
    checkpoints: dict[str, CheckpointSpec] = {}
    for name, cp in (doc.get("checkpoints") or {}).items():
        if name not in CHECKPOINTS:
            raise PolicyError(f"Unknown checkpoint {name!r} (plan | handoff)", column=column)
        if not stage.is_agent_stage:
            raise PolicyError("Checkpoints belong on a column an agent role works",
                              column=column)
        cp_doc = cp or {}
        decision_doc = cp_doc.get("decision")
        checkpoints[name] = CheckpointSpec(
            required=bool(cp_doc.get("required", True)),
            approval_when=validate_conditions(
                cp_doc.get("approval_when", decision_doc.get("when") if decision_doc else None),
                column,
            ),
            decision=parse_decision(decision_doc, names, column) if decision_doc else None,
            pre_approved=validate_change_classes(cp_doc.get("pre_approved"), column),
        )
    stage.checkpoints = checkpoints
    stage.lease_minutes = _int(doc.get("lease_minutes"), "lease_minutes", column, lo=5, hi=720,
                               default=DEFAULT_LEASE_MINUTES)
    stage.max_attempts = _int(doc.get("max_attempts"), "max_attempts", column, lo=1, hi=20,
                              default=DEFAULT_MAX_ATTEMPTS)
    stage.max_rework = _int(doc.get("max_rework"), "max_rework", column, lo=1, hi=20,
                            default=DEFAULT_MAX_REWORK)
    stage.has_policy = True
    stage.source = "policy"


# --------------------------------------------------------------------------- #
# Evaluation (preview == enforcement)
# --------------------------------------------------------------------------- #


@dataclass
class ArtifactFact:
    kind: str
    revision: int
    created_at: datetime
    verdict: str | None = None
    head_sha: str | None = None
    data: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class PullRequestFact:
    state: str
    merged: bool = False
    head_sha: str | None = None
    checks_state: str | None = None
    approved_by: Sequence[str] = ()
    changed_lines: int | None = None


@dataclass
class ActorFact:
    """Who completed a stage (or holds the current claim): their token and issuer."""

    agent_token_id: int | None
    user_id: int | None


@dataclass
class EvalContext:
    """Everything `evaluate` reads. `round_started_at` is when the current round of work began
    (the last return for rework, else the first claim); artifacts older than it don't count."""

    actor: str = "agent"  # agent | human | system
    dependencies_done: bool = True
    open_blockers: int = 0
    spec_status: str | None = None
    criteria: Sequence[str] = ()  # each criterion's status (waived ones included)
    artifacts: Sequence[ArtifactFact] = ()
    round_started_at: datetime | None = None
    approved_plan_revision: int | None = None  # the plan revision a gate approved
    plan_approval_required: bool = False  # the latest plan revision needed an approval
    approved_gate_kinds: frozenset[str] = frozenset()  # approved since the last rework
    pull_request: PullRequestFact | None = None
    requester_logins: frozenset[str] = frozenset()  # the issuer's GitHub login(s)
    rules_required: Sequence[str] = ()  # attestation rule keys that apply
    attested: Mapping[str, str] = field(default_factory=dict)  # rule key -> status
    # A rule's own enforcement (warn | block): an unattested `block` rule refuses the move even
    # where the column's `attestations_complete` check only warns.
    rule_enforcement: Mapping[str, str] = field(default_factory=dict)
    current: ActorFact | None = None  # the claim being handed off (or the mover)
    stage_actors: Mapping[str, ActorFact] = field(default_factory=dict)  # role -> who did it


@dataclass
class CheckResult:
    check: str
    label: str
    enforcement: str
    fact: str  # observed | attested
    passed: bool
    message: str
    applies_to: str = "agents"

    def to_dict(self) -> dict[str, Any]:
        return {
            "check": self.check,
            "label": self.label,
            "enforcement": self.enforcement,
            "fact": self.fact,
            "passed": self.passed,
            "message": self.message,
            "applies_to": self.applies_to,
        }


@dataclass
class Evaluation:
    target: str
    allowed: bool
    failures: list[CheckResult]
    warnings: list[CheckResult]
    results: list[CheckResult]

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "allowed": self.allowed,
            "failures": [r.to_dict() for r in self.failures],
            "warnings": [r.to_dict() for r in self.warnings],
            "results": [r.to_dict() for r in self.results],
        }


def _in_round(fact: ArtifactFact, ctx: EvalContext) -> bool:
    return ctx.round_started_at is None or fact.created_at >= ctx.round_started_at


def latest_artifact(ctx: EvalContext, kind: str) -> ArtifactFact | None:
    rows = [a for a in ctx.artifacts if a.kind == kind]
    return max(rows, key=lambda a: a.revision) if rows else None


def _check(spec: CheckSpec, ctx: EvalContext) -> tuple[bool, str]:
    name, params = spec.check, spec.params
    pr = ctx.pull_request
    if name == "dependencies_done":
        return ctx.dependencies_done, "Predecessors are done" if ctx.dependencies_done else (
            "A predecessor isn't done yet")
    if name == "no_open_blockers":
        ok = ctx.open_blockers == 0
        return ok, "No open blockers" if ok else f"{ctx.open_blockers} open blocker(s)"
    if name == "spec_approved":
        ok = ctx.spec_status in ("approved", "in_progress", "verified")
        return ok, "The spec is approved" if ok else "No approved spec"
    if name == "artifact":
        kind = str(params.get("kind"))
        art = latest_artifact(ctx, kind)
        ok = art is not None and _in_round(art, ctx)
        return ok, f"A {kind} was recorded" if ok else f"No {kind} in this round"
    if name == "plan_approved":
        plan = latest_artifact(ctx, "plan")
        if plan is None or not ctx.plan_approval_required:
            return True, "No plan approval was needed"
        ok = ctx.approved_plan_revision == plan.revision
        return ok, ("The plan was approved" if ok
                    else f"Plan revision {plan.revision} is waiting for approval")
    if name == "gate_approved":
        kind = str(params.get("kind"))
        ok = kind in ctx.approved_gate_kinds
        return ok, f"{kind} approved" if ok else f"{kind} not approved yet"
    if name == "pr_linked":
        want = params.get("state")
        if pr is None:
            return False, "No pull request is linked"
        if want == "merged":
            return pr.merged, "The PR is merged" if pr.merged else "The PR isn't merged"
        if want == "open":
            ok = pr.state == "open" and not pr.merged
            return ok, "An open PR is linked" if ok else "The linked PR isn't open"
        return True, "A pull request is linked"
    if name == "pr_checks":
        ok = pr is not None and pr.checks_state == "passing"
        state = pr.checks_state if pr is not None else None
        return ok, "PR checks pass" if ok else f"PR checks: {state or 'none seen'}"
    if name == "pr_approved":
        others = [
            login for login in (pr.approved_by if pr is not None else [])
            if login not in ctx.requester_logins
        ]
        ok = bool(others)
        return ok, (f"Approved by {', '.join(others)}" if ok
                    else "No approval from someone other than the requester")
    if name == "pr_size":
        limit = int(params.get("max_changed_lines") or 400)
        lines = pr.changed_lines if pr is not None else None
        if lines is None:
            return True, "PR size unknown"
        return lines <= limit, f"{lines} changed lines (limit {limit})"
    if name == "verdict":
        kind = str(params.get("kind"))
        allowed = list(params.get("in") or ["pass"])
        art = latest_artifact(ctx, kind)
        if art is None or not _in_round(art, ctx):
            return False, f"No {kind} verdict in this round"
        stale = bool(pr and pr.head_sha and art.head_sha and art.head_sha != pr.head_sha)
        if stale:
            return False, f"The {kind} verdict is stale (the PR moved past it)"
        ok = art.verdict in allowed
        return ok, f"{kind}: {art.verdict}" + ("" if ok else f" (needs {'/'.join(allowed)})")
    if name == "criteria_met":
        open_ones = [c for c in ctx.criteria if c not in ("met", "waived")]
        if not ctx.criteria:
            return True, "No acceptance criteria"
        return not open_ones, ("Every criterion is met or waived" if not open_ones
                               else f"{len(open_ones)} criterion(s) not met")
    if name == "attestations_complete":
        missing = [k for k in ctx.rules_required if ctx.attested.get(k) not in ("done", "n/a")]
        return not missing, ("Every Definition-of-Done item is attested" if not missing
                             else "Not attested: " + ", ".join(missing))
    if name in ("distinct_actor", "distinct_issuer"):
        role = str(params.get("role"))
        before = ctx.stage_actors.get(role)
        now = ctx.current
        if before is None or now is None:
            return True, f"No {role} work to compare against"
        if name == "distinct_actor":
            same = (before.agent_token_id is not None
                    and before.agent_token_id == now.agent_token_id)
            if before.agent_token_id is None and now.agent_token_id is None:
                same = before.user_id == now.user_id
            return not same, (f"A different session than the {role}" if not same
                              else f"The same session that did the {role} work")
        same_user = before.user_id is not None and before.user_id == now.user_id
        return not same_user, (f"A different person than the {role}'s issuer" if not same_user
                               else f"The same person who issued the {role} session")
    return True, "Unknown check"  # pragma: no cover - validated on save


def evaluate(target: StageDef, ctx: EvalContext, *, phase: str = "enter") -> Evaluation:
    """Can a task enter `target` (`phase="enter"`), or may this session work it there
    (`phase="claim"`: the claim-time checks only)? Blocking checks that fail refuse it; warning
    checks are reported. A person's move only feels checks marked `everyone` as refusals (D4)."""
    failures: list[CheckResult] = []
    warnings: list[CheckResult] = []
    results: list[CheckResult] = []
    for spec in target.enter_checks:
        if spec.enforcement == "off":
            continue
        if (spec.check in CLAIM_TIME_CHECKS) != (phase == "claim"):
            continue
        passed, message = _check(spec, ctx)
        result = CheckResult(
            check=spec.check, label=spec.label(), enforcement=spec.enforcement,
            fact=CHECKS[spec.check][0], passed=passed, message=message,
            applies_to=spec.applies_to,
        )
        results.append(result)
        if passed:
            continue
        strict = spec.enforcement == "block" or (
            spec.check == "attestations_complete"
            and any(ctx.rule_enforcement.get(k) == "block" for k in ctx.rules_required
                    if ctx.attested.get(k) not in ("done", "n/a"))
        )
        blocking = strict and (ctx.actor != "human" or spec.applies_to == "everyone")
        (failures if blocking else warnings).append(result)
    return Evaluation(target=target.status_name, allowed=not failures, failures=failures,
                      warnings=warnings, results=results)


# --------------------------------------------------------------------------- #
# Conditions: must a person look?
# --------------------------------------------------------------------------- #


@dataclass
class DecisionFact:
    adr_id: int
    number: int
    title: str
    status: str
    reversibility: str | None


@dataclass
class ConditionFacts:
    governing: Sequence[DecisionFact] = ()  # accepted decisions on the touched components
    unsettled: Sequence[DecisionFact] = ()  # proposed / under-discussion ones
    high_criticality: Sequence[str] = ()  # names of touched high-criticality components
    spec_approved: bool = False
    criteria_count: int = 0
    plan_confidence: str | None = None
    change_classes: Sequence[str] = ()
    affected_paths: int = 0
    task_duration_days: int | None = None
    tags: Sequence[str] = ()
    agent_done_count: int = 0


# What a pre-approved change class can never skip: a one-way door, a high-criticality
# component, a decision still under discussion, a plan unsure of itself.
PRE_APPROVAL_FLOOR = frozenset({"one_way_door", "high_criticality", "unsettled_decision",
                                "low_confidence"})
_CLASS_RE = re.compile(r"^tag:[a-z0-9][a-z0-9_.-]{0,63}$")


def validate_change_classes(raw: Any, column: str) -> list[str]:
    """`pre_approved`: a list of `tag:<tag>` change classes."""
    if raw in (None, []):
        return []
    if not isinstance(raw, list):
        raise PolicyError("pre_approved must be a list of change classes", column=column)
    out: list[str] = []
    for item in raw:
        value = str(item).strip().lower()
        if not _CLASS_RE.match(value):
            raise PolicyError(f"{item!r} isn't a change class (tag:<tag>)", column=column)
        if value not in out:
            out.append(value)
    return out


def pre_approval_class(pre_approved: Sequence[str], tags: Sequence[str]) -> str | None:
    """The first pre-approved change class this task belongs to (None: none)."""
    have = {t.strip().lower() for t in tags}
    for cls in pre_approved:
        head, _, arg = cls.partition(":")
        if head == "tag" and arg in have:
            return cls
    return None


def checkpoint_outcome(
    conditions: Sequence[str], facts: ConditionFacts, pre_approved: Sequence[str] = ()
) -> tuple[list[str], list[str], str | None]:
    """(reasons a person must decide, reasons a pre-approval waived, the class that waived
    them). A pre-approved class skips everything but the safety floor — and a condition that
    names another tag ("always ask for security work") stays a team's explicit call."""
    pairs = _matched(conditions, facts)
    cls = pre_approval_class(pre_approved, facts.tags) if pre_approved else None
    if cls is None:
        return _dedupe(r for _, r in pairs), [], None
    own_tag = cls.partition(":")[2]

    def holds(cond: str) -> bool:
        head, _, arg = cond.partition(":")
        return head in PRE_APPROVAL_FLOOR or (head == "tag" and arg != own_tag)

    kept = _dedupe(r for cond, r in pairs if holds(cond))
    waived = _dedupe(r for cond, r in pairs if not holds(cond))
    return kept, waived, cls


def _dedupe(reasons: Any) -> list[str]:
    out: list[str] = []
    for reason in reasons:
        if reason not in out:
            out.append(reason)
    return out


def matched_conditions(conditions: Sequence[str], facts: ConditionFacts) -> list[str]:
    """The reasons a person must decide, in plain words — empty means no approval is needed.
    Fail closed: a decision with no reversibility recorded counts as a one-way door (§A6)."""
    return _dedupe(r for _, r in _matched(conditions, facts))


def _matched(conditions: Sequence[str], facts: ConditionFacts) -> list[tuple[str, str]]:
    """(condition, reason) for every condition that holds — the whole condition, e.g.
    `tag:security`, so a pre-approval can tell which tag a condition names."""
    reasons: list[tuple[str, str]] = []
    for cond in conditions:
        head, _, arg = cond.partition(":")
        if cond == "always":
            reasons.append((cond, "This stage always asks a person"))
        elif cond == "never":
            continue
        elif head == "one_way_door":
            doors = [d for d in facts.governing if d.reversibility != "two_way"]
            for d in doors:
                reasons.append((cond,
                    f"Touches what ADR-{d.number:04d} “{d.title}” governs as a one-way door"
                    if d.reversibility == "one_way"
                    else f"Touches what ADR-{d.number:04d} “{d.title}” governs, and that "
                         "decision isn't classified as reversible"
                ))
            declared = sorted(set(facts.change_classes) & ONE_WAY_CHANGE_CLASSES)
            if declared:
                reasons.append((cond, "The plan declares " + ", ".join(
                    c.replace("_", " ") for c in declared)))
        elif head == "high_criticality" and facts.high_criticality:
            reasons.append((cond, "Touches high-criticality "
                            + ", ".join(facts.high_criticality)))
        elif head == "unsettled_decision" and facts.unsettled:
            reasons.extend(
                (cond, f"ADR-{d.number:04d} “{d.title}” is still {d.status.replace('_', ' ')}")
                for d in facts.unsettled
            )
        elif head == "no_spec" and (not facts.spec_approved or facts.criteria_count == 0):
            reasons.append((cond, "No approved spec with acceptance criteria"))
        elif head == "low_confidence" and facts.plan_confidence == "low":
            reasons.append((cond, "The plan's own confidence is low"))
        elif head == "large_change":
            max_paths, max_days = _large_change_limits(arg)
            if facts.affected_paths > max_paths:
                reasons.append((cond, f"The plan touches {facts.affected_paths} paths "
                                f"(limit {max_paths})"))
            if facts.task_duration_days is not None and facts.task_duration_days > max_days:
                reasons.append((cond,
                    f"The task is sized at {facts.task_duration_days} days (limit {max_days})"
                ))
        elif head == "probation" and arg.isdigit() and facts.agent_done_count < int(arg):
            reasons.append((cond,
                f"Fewer than {arg} agent-worked tasks have reached done in this project"
            ))
        elif head == "tag" and arg and arg in facts.tags:
            reasons.append((cond, f"The task is tagged {arg}"))
    return reasons


def _large_change_limits(arg: str) -> tuple[int, int]:
    """`large_change` or `large_change:<max_paths>,<max_days>` (defaults 12 paths, 5 days)."""
    parts = [p for p in arg.split(",") if p.strip()]
    try:
        max_paths = int(parts[0]) if parts else 12
        max_days = int(parts[1]) if len(parts) > 1 else 5
    except ValueError:
        return 12, 5
    return max_paths, max_days


# --------------------------------------------------------------------------- #
# The agentic-delivery template (Appendix A)
# --------------------------------------------------------------------------- #

TEMPLATE_KEY = "agentic-delivery"


def agentic_delivery_template() -> tuple[list[tuple[str, str]], dict[str, dict[str, Any]]]:
    """The Appendix A columns (name, category) and their policy documents."""
    columns = [
        ("Backlog", flow.TODO),
        ("Ready", flow.TODO),
        ("In Progress", flow.IN_PROGRESS),
        ("In Review", flow.IN_PROGRESS),
        ("QA", flow.IN_PROGRESS),
        ("Sign-off", flow.IN_PROGRESS),
        ("Done", flow.DONE),
        ("Cancelled", flow.CANCELLED),
    ]
    policies: dict[str, dict[str, Any]] = {
        "In Progress": {
            "worked_by": "implementer",
            "artifact": "handoff",
            "instructions": (
                "Plan first: submit_plan before writing code, and wait if a person must approve. "
                "Keep the PR under 400 changed lines; split the task if it can't be. Title the PR "
                "with the task key, run the tests, then hand off with submit_work."
            ),
            "pulls_from": ["Ready"],
            "enter": {"checks": [
                {"check": "dependencies_done", "enforcement": "block"},
                {"check": "no_open_blockers", "enforcement": "block"},
            ]},
            "checkpoints": {"plan": {"required": True,
                                     "approval_when": list(DEFAULT_PLAN_APPROVAL_WHEN)}},
        },
        "In Review": {
            "worked_by": "reviewer",
            "artifact": "review",
            "instructions": (
                "Review the PR against the spec, the approved plan, the binding decisions and the "
                "team's rules. Run the pr-to-adr-linker. Record findings by severity; don't fix "
                "them yourself — a failed review goes back to the implementer."
            ),
            "enter": {"checks": [
                {"check": "artifact", "params": {"kind": "handoff"}, "enforcement": "block"},
                {"check": "pr_linked", "params": {"state": "open"}, "enforcement": "block"},
                {"check": "pr_checks", "params": {"state": "passing"}, "enforcement": "block"},
                {"check": "plan_approved", "enforcement": "block"},
                {"check": "distinct_actor", "params": {"role": "implementer"},
                 "enforcement": "block"},
                {"check": "attestations_complete", "enforcement": "warn"},
                {"check": "pr_size", "params": {"max_changed_lines": 400},
                 "enforcement": "warn"},
            ]},
        },
        "QA": {
            "worked_by": "qa",
            "artifact": "qa_report",
            "instructions": (
                "Verify each acceptance criterion against the running change and record what you "
                "did and saw. A failed criterion is a fail verdict."
            ),
            "enter": {"checks": [
                {"check": "verdict", "params": {"kind": "review", "in": ["pass", "concerns"]},
                 "enforcement": "block"},
                {"check": "distinct_actor", "params": {"role": "implementer"},
                 "enforcement": "block"},
            ]},
        },
        "Sign-off": {
            "worked_by": HUMAN,
            "enter": {"checks": [
                {"check": "verdict", "params": {"kind": "qa_report", "in": ["pass", "concerns"]},
                 "enforcement": "block"},
                {"check": "criteria_met", "enforcement": "warn"},
            ]},
            "decision": {
                "kind": "signoff",
                "when": "always",
                "approvers": "project_planners",
                "exclude_requester": True,
                "satisfied_by": ["canopy", "pr_approval", "pr_merge"],
                "remind_after_hours": DEFAULT_REMIND_HOURS,
                "escalate_after_hours": DEFAULT_ESCALATE_HOURS,
                "on_approve": "Done",
                "on_changes": "In Progress",
                "on_reject": "Cancelled",
            },
        },
        "Done": {
            "worked_by": None,
            "enter": {"checks": [
                {"check": "pr_linked", "params": {"state": "merged"}, "enforcement": "block"},
            ]},
        },
    }
    return columns, policies
