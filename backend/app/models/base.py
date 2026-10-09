from datetime import UTC, datetime
from enum import StrEnum

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
