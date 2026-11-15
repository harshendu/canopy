from datetime import UTC, datetime
from enum import StrEnum

import sqlalchemy as sa
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    # Naive UTC: the DB columns are TIMESTAMP WITHOUT TIME ZONE, and asyncpg (Postgres)
    # rejects tz-aware datetimes for them. Storing naive UTC keeps writes portable across
    # Postgres / MySQL / SQLite and matches how rows read back from every dialect.
    return datetime.now(UTC).replace(tzinfo=None)


class TimestampMixin(SQLModel):
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class TaskType(StrEnum):
    task = "task"
    milestone = "milestone"
    summary = "summary"  # a summary task acts as a phase / workstream in the WBS


# --- Work tracking (status ownership, categories, workflows) ---
# These closed sets are stored as plain VARCHAR columns (no native DB enum type) and validated
# by these StrEnums at the API boundary — the pattern `Milestone.status` already uses — so
# adding a value never needs a dialect-branched enum migration.
class TrackingMode(StrEnum):
    """Who owns a project's work items: canopy itself, or an external tracker it mirrors."""

    native = "native"
    mirrored = "mirrored"


class StatusCategory(StrEnum):
    """What a status *means* — every flow metric reads this, never the display name."""

    todo = "todo"  # not started
    in_progress = "in_progress"  # started, not finished (counts as WIP)
    done = "done"  # completed — counts as throughput
    cancelled = "cancelled"  # dropped — leaves WIP, never counts as throughput


class WipEnforcement(StrEnum):
    off = "off"
    warn = "warn"  # the move succeeds and reports `wip_limit_exceeded`
    block = "block"  # the move is refused with 409 `wip_limit_reached`


class StatusSource(StrEnum):
    """Where a `TaskStatusHistory` row came from (approximate rows can later be replaced)."""

    canopy = "canopy"  # a move made in canopy (board, API, MCP, proposal apply)
    sync = "sync"  # observed by a sync/webhook/ingest; dated by the item's `updated`
    backfill = "backfill"  # replayed from a tracker's changelog (exact transition times)


# The `status_owner` value of a task whose status canopy owns (else a provider key, e.g. "jira").
CANOPY_OWNER = "canopy"


class ActorKind(StrEnum):
    """Who made a change canopy recorded (status history, work events)."""

    human = "human"  # a person's own (full-scope) session
    agent = "agent"  # an agent-scope token, acting for the person who issued it
    system = "system"  # canopy itself: routing after a gate decision, a PR event, the reaper


# --- Agent execution (docs/AGENT_EXECUTION.md): the work queue, claims, artifacts, gates ---
# Stored as VARCHAR and validated by these StrEnums at the API boundary (the TrackingMode
# pattern), so adding a value never needs a dialect-branched enum migration.
class AgentIntake(StrEnum):
    """A project's switch for agent work."""

    off = "off"  # nothing in the project is offered to agents (the default)
    on = "on"
    paused = "paused"  # no new claims; sessions already working may finish


class Delegation(StrEnum):
    """A person's mark on a task: agents may work it. The assignee stays accountable."""

    agent = "agent"


class AgentRole(StrEnum):
    """The built-in agent roles. A team may add its own keys (planner, security-reviewer, …);
    roles are plain strings everywhere they are stored."""

    implementer = "implementer"
    reviewer = "reviewer"
    qa = "qa"


class ClaimState(StrEnum):
    active = "active"  # the session holds the lease
    completed = "completed"  # handed off, returned for rework, or ended at a gate
    released = "released"  # the session gave the task back
    failed = "failed"  # the session said a person is needed
    expired = "expired"  # the lease ran out
    superseded = "superseded"  # a person took over, or the task was cancelled / undelegated


class ClaimOutcome(StrEnum):
    advanced = "advanced"  # handed off; the task moved on
    returned = "returned"  # a review / QA verdict sent the task back for rework
    gated = "gated"  # ended because a person must decide (a question, a checkpoint)
    released = "released"
    failed = "failed"
    expired = "expired"
    superseded = "superseded"


class ArtifactKind(StrEnum):
    plan = "plan"
    handoff = "handoff"
    review = "review"
    qa_report = "qa_report"
    note = "note"


class Verdict(StrEnum):
    """A review / QA verdict (the BMAD-style vocabulary, waivers live on the sign-off)."""

    passed = "pass"
    concerns = "concerns"
    failed = "fail"


class GateKind(StrEnum):
    plan_approval = "plan_approval"  # a plan checkpoint fired
    handoff_approval = "handoff_approval"  # a hand-off checkpoint fired
    signoff = "signoff"  # the default kind of a decision column
    question = "question"  # the agent needs an answer to proceed
    escalation = "escalation"  # the agent (or canopy) says it should not proceed


class GateOrigin(StrEnum):
    checkpoint = "checkpoint"
    column = "column"
    agent = "agent"
    system = "system"


class GateStatus(StrEnum):
    """A gate's coarse outcome; the exact response is `Gate.decision`."""

    open = "open"
    approved = "approved"
    changes_requested = "changes_requested"
    rejected = "rejected"
    answered = "answered"
    cancelled = "cancelled"


class GateDecision(StrEnum):
    approve = "approve"
    edit_and_approve = "edit_and_approve"
    approve_with_conditions = "approve_with_conditions"
    request_changes = "request_changes"
    reject = "reject"
    take_over = "take_over"
    answer = "answer"
    retry = "retry"  # escalations: try again with guidance (attempts reset)
    cancelled = "cancelled"  # withdrawn, or closed because the task left the queue


class DecidedVia(StrEnum):
    canopy = "canopy"  # a person decided in canopy
    pr_review = "pr_review"  # a GitHub review satisfied it
    pr_merge = "pr_merge"  # the PR was merged
    policy = "policy"  # canopy closed it (the task was cancelled, undelegated, merged ahead)


class WorkEventKind(StrEnum):
    delegated = "delegated"  # also undelegation (data.delegation = null)
    intake_changed = "intake_changed"
    components_changed = "components_changed"
    claimed = "claimed"
    claim_ended = "claim_ended"  # data.outcome
    artifact_added = "artifact_added"
    checks_evaluated = "checks_evaluated"  # the decision log of a policy evaluation
    advanced = "advanced"
    returned = "returned"
    gate_opened = "gate_opened"
    gate_decided = "gate_decided"
    gate_escalated = "gate_escalated"
    gate_reassigned = "gate_reassigned"
    override = "override"
    merged_ahead_of_stage = "merged_ahead_of_stage"
    moved_without_clearance = "moved_without_clearance"
    policy_changed = "policy_changed"


class DeliveryMethod(StrEnum):
    """How a team runs its work, across all of its projects (USER_FLOWS §C11)."""

    kanban = "kanban"  # continuous flow: WIP limits, cycle time, weekly forecast
    sprint = "sprint"  # time boxes: planning, sprint burndown, velocity
    both = "both"  # sprints on top of a WIP-limited board


class EstimateUnit(StrEnum):
    points = "points"  # Task.story_points
    days = "days"  # Task.duration (working days)
    item_count = "count"  # every task counts 1 (member name avoids shadowing str.count)


class SprintState(StrEnum):
    planned = "planned"
    active = "active"
    completed = "completed"


class DependencyType(StrEnum):
    FS = "FS"  # finish-to-start (default)
    SS = "SS"  # start-to-start
    FF = "FF"  # finish-to-finish
    SF = "SF"  # start-to-finish


class ADRStatus(StrEnum):
    proposed = "proposed"
    under_discussion = "under_discussion"
    accepted = "accepted"
    rejected = "rejected"
    superseded = "superseded"
    deprecated = "deprecated"
    deferred = "deferred"


class Reversibility(StrEnum):
    one_way = "one_way"  # a hard-to-reverse decision (Bezos "type 1" door)
    two_way = "two_way"  # an easily reversible decision (Bezos "type 2" door)


class ADRCommentKind(StrEnum):
    comment = "comment"
    approve = "approve"
    request_changes = "request_changes"
    reject = "reject"


class DecisionRule(StrEnum):
    owner_decides = "owner_decides"
    consensus = "consensus"  # every stakeholder must approve
    lazy_consensus = "lazy_consensus"  # accept unless a stakeholder requests changes


class RetrospectiveKind(StrEnum):
    project_retro = "project_retro"
    incident_postmortem = "incident_postmortem"


class ActivityKind(StrEnum):
    deploy = "deploy"
    build_failure = "build_failure"
    incident_open = "incident_open"
    incident_close = "incident_close"


class Provider(StrEnum):
    jira = "jira"
    github = "github"
    gdrive = "gdrive"
    # Work trackers beyond Jira (USER_FLOWS §J0) — opt-in through TRACKERS_ENABLED.
    linear = "linear"
    generic = "generic"


# `provider` columns are VARCHAR (not a native DB enum), so adding a tracker is one enum member
# + one module — no dialect-branched enum migration (USER_FLOWS §J0).
ProviderType = sa.Enum(Provider, native_enum=False, create_constraint=False, length=32)


class ReadStrategy(StrEnum):
    """How canopy reads a provider's data (per-provider, admin-chosen integration policy).

    `direct` polls / accepts webhooks using canopy's own credentials (the shared service
    connection today; a per-user OAuth connection in a later phase) **when they are available**,
    degrading silently when they are not. `mcp` / `file` mean canopy does not call the provider
    API itself — data arrives via Claude over MCP, or via a file drop into shared storage.
    """

    direct = "direct"
    mcp = "mcp"
    file = "file"


class WriteStrategy(StrEnum):
    """How writes back to a provider happen (per-provider, admin-chosen integration policy).

    `direct` writes from canopy with its own credentials; `mcp` routes the write through Claude
    (canopy's own direct write paths refuse); `disabled` blocks writes entirely.
    """

    direct = "direct"
    mcp = "mcp"
    disabled = "disabled"


class UserRole(StrEnum):
    admin = "admin"
    architect = "architect"
    engineering_manager = "engineering_manager"
    engineer = "engineer"
    viewer = "viewer"
    member = "member"  # legacy default (pre-roles); treated as ~architect


# --- Delivery metadata (tags / estimates / risk register / health) ---
class RiskScope(StrEnum):
    """What a risk-register entry hangs off of."""

    task = "task"
    project = "project"
    initiative = "initiative"


class RiskCategory(StrEnum):
    schedule = "schedule"
    scope = "scope"
    technical = "technical"
    resource = "resource"
    external = "external"
    quality = "quality"
    security = "security"


class RiskStatus(StrEnum):
    open = "open"
    mitigating = "mitigating"
    accepted = "accepted"  # consciously tolerated
    resolved = "resolved"  # no longer a threat
    occurred = "occurred"  # the risk materialised (became an issue)


class RiskGrade(StrEnum):
    """An ordinal grade for probability/impact (maps to 1..3)."""

    low = "low"
    medium = "medium"
    high = "high"


class BlockerCategory(StrEnum):
    dependency = "dependency"
    resource = "resource"
    decision = "decision"
    external = "external"
    technical = "technical"


class BlockerSeverity(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class ProjectHealth(StrEnum):
    """A human-set status colour that overrides the computed on-track signal."""

    on_track = "on_track"
    at_risk = "at_risk"
    off_track = "off_track"


# --- Document graph (link, don't store) ---
class DocKind(StrEnum):
    """The kind of document a reference points at (canopy links it; never stores it)."""

    prd = "prd"
    design = "design"
    tech_design = "tech_design"
    architecture = "architecture"
    release = "release"
    qa = "qa"
    runbook = "runbook"
    other = "other"


class DocScope(StrEnum):
    """What a document reference hangs off of (polymorphic, like RiskScope)."""

    project = "project"
    initiative = "initiative"
    task = "task"


class DocSource(StrEnum):
    """How a document reference entered canopy."""

    jira_epic = "jira_epic"  # harvested from a Jira epic's fields / links
    manual = "manual"  # added by hand in canopy
    repo = "repo"  # from a GitHub repo doc
    drive = "drive"  # from a Google Drive folder


class DocLinkHealth(StrEnum):
    """Liveness of a referenced document (the missing/stale/broken signal)."""

    unchecked = "unchecked"
    ok = "ok"
    stale = "stale"
    broken = "broken"


# --- Specs (spec-driven development: intent as the source of truth) ---
class SpecStatus(StrEnum):
    draft = "draft"
    approved = "approved"  # reviewed, ready to build
    in_progress = "in_progress"  # work linked / under way
    verified = "verified"  # all acceptance criteria met
    archived = "archived"


class CriterionStatus(StrEnum):
    """State of one acceptance criterion in the agent self-audit."""

    open = "open"  # not yet verified
    met = "met"
    unmet = "unmet"
    waived = "waived"  # consciously dropped (excluded from readiness)


class TokenScope(StrEnum):
    """Bounded agency for access tokens. A `full` (human) token can do anything its role
    allows; an `agent` token is restricted from one-way-door / external-write actions — the
    reversibility distinction *is* the human-in-the-loop policy (AI_NATIVE_EXECUTION.md §3/§8)."""

    full = "full"
    agent = "agent"


# --- Outcomes (outcomes over output: a project/initiative is a bet) ---
class OutcomeScope(StrEnum):
    project = "project"
    initiative = "initiative"


class OutcomeStatus(StrEnum):
    pending = "pending"  # not yet measured
    on_track = "on_track"
    at_risk = "at_risk"
    validated = "validated"  # the bet paid off (terminal)
    invalidated = "invalidated"  # the bet didn't (terminal)


# --- Change proposals (agent-staged writes, human-reviewed in the UI) ---
class ProposalScope(StrEnum):
    """What a change proposal targets (polymorphic, like RiskScope/OutcomeScope)."""

    project = "project"
    initiative = "initiative"


class ProposalStatus(StrEnum):
    open = "open"  # staged, awaiting human review
    applied = "applied"  # a human reviewed and committed it from the UI
    rejected = "rejected"  # a human turned it down (see review_note)
    withdrawn = "withdrawn"  # the author (often the agent) pulled it back


class ProposalEntity(StrEnum):
    """The canopy entity a proposal item mutates."""

    task = "task"
    dependency = "dependency"
    milestone = "milestone"
    blocker = "blocker"
    risk = "risk"
    outcome = "outcome"
    decision = "decision"
    doc_reference = "doc_reference"


class ProposalAction(StrEnum):
    create = "create"
    update = "update"
    resolve = "resolve"  # blockers only: mark the impediment cleared


class UserFunction(StrEnum):
    """A user's cross-functional persona — orthogonal to their access `role`. Drives the default
    landing surface and digest cadence, not CRUD (reads stay open; writes are gated by `role`).
    AI_NATIVE_EXECUTION.md §5: PM/UX/staff/director/exec are first-class, not all 'viewer'."""

    engineering = "engineering"
    product = "product"
    design = "design"
    architecture = "architecture"
    management = "management"  # eng manager / director
    leadership = "leadership"  # executive


class LeadRole(StrEnum):
    """An initiative owner's seat: a pod's technical / product / design lead, or a manager.
    An initiative may have several owners, and one person may own several initiatives."""

    technical = "technical"
    product = "product"
    design = "design"
    manager = "manager"


class TeamRole(StrEnum):
    """A team-level seat above the pods: the team's director(s) and engineering manager(s)."""

    director = "director"
    manager = "manager"


class LeadershipScope(StrEnum):
    """What a leadership note hangs off of (polymorphic, like OutcomeScope)."""

    initiative = "initiative"
    project = "project"


class LeadershipNoteKind(StrEnum):
    """Why leadership left the note: something to watch, a priority call, or feedback."""

    watch = "watch"
    priority = "priority"
    feedback = "feedback"


class LeadershipTargetKind(StrEnum):
    """An optional finer target inside the scope a note points at."""

    decision = "decision"
    risk = "risk"
    outcome = "outcome"
    milestone = "milestone"


class LeadershipNoteStatus(StrEnum):
    open = "open"
    acknowledged = "acknowledged"
    resolved = "resolved"
