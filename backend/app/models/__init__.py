"""Importing this package registers every table on SQLModel.metadata."""

from app.models.activity import ActivityEvent
from app.models.architecture import (
    ADRComment,
    ADRComponentLink,
    ADRStakeholder,
    ArchitectureComponent,
    ArchitectureDecision,
    ComponentCodeBinding,
    ComponentLink,
    DriftEvent,
    DriftSuppression,
)
from app.models.integration import (
    Connection,
    ExternalRef,
    PullRequest,
)
from app.models.project import (
    Dependency,
    Holiday,
    Milestone,
    Project,
    RiskMitigation,
    Task,
    TaskStatusHistory,
)
from app.models.retro import Retrospective, RetrospectiveComment
from app.models.team import Allocation, Engineer, Role
from app.models.user import User

__all__ = [
    "ADRComment",
    "ADRComponentLink",
    "ADRStakeholder",
    "ActivityEvent",
    "Allocation",
    "ArchitectureComponent",
    "ArchitectureDecision",
    "ComponentCodeBinding",
    "ComponentLink",
    "Connection",
    "Dependency",
    "DriftEvent",
    "DriftSuppression",
    "Engineer",
    "ExternalRef",
    "Holiday",
    "Milestone",
    "Project",
    "PullRequest",
    "Retrospective",
    "RetrospectiveComment",
    "RiskMitigation",
    "Role",
    "Task",
    "TaskStatusHistory",
    "User",
]
