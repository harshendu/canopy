from datetime import datetime, timezone
from enum import Enum

from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin(SQLModel):
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class TaskType(str, Enum):
    task = "task"
    milestone = "milestone"
    summary = "summary"  # a summary task acts as a phase / workstream in the WBS


class DependencyType(str, Enum):
    FS = "FS"  # finish-to-start (default)
    SS = "SS"  # start-to-start
    FF = "FF"  # finish-to-finish
    SF = "SF"  # start-to-finish


class ADRStatus(str, Enum):
    proposed = "proposed"
    accepted = "accepted"
    superseded = "superseded"
    deprecated = "deprecated"


class Provider(str, Enum):
    jira = "jira"
    github = "github"
    gdrive = "gdrive"


class UserRole(str, Enum):
    admin = "admin"
    member = "member"
