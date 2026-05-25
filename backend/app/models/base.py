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
