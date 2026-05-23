from datetime import UTC, datetime
from enum import StrEnum

from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(UTC)


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


class Provider(StrEnum):
    jira = "jira"
    github = "github"
    gdrive = "gdrive"


class UserRole(StrEnum):
    admin = "admin"
    member = "member"
