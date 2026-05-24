"""Importing this package registers every table on SQLModel.metadata."""

from app.models.activity import ActivityEvent
from app.models.architecture import (
    ADRComment,
    ADRComponentLink,
    ADRFitnessFunction,
    ADRStakeholder,
    ArchitectureComponent,
    ArchitectureDecision,
    ComponentCodeBinding,
    ComponentLink,
    DriftEvent,
    DriftScan,
    DriftSuppression,
)
from app.models.draft import DraftPlan, DraftTask
from app.models.integration import (
    Connection,
    ExternalRef,
    JiraLink,
    PullRequest,
)
from app.models.project import (
    Baseline,
    Blocker,
    Dependency,
    Holiday,
    Initiative,
    Milestone,
    Project,
    RiskMitigation,
    RiskSnapshot,
    Task,
    TaskStatusHistory,
)
from app.models.retro import Retrospective, RetrospectiveComment
from app.models.risk_register import RiskItem
from app.models.scenario import (
    Scenario,
    ScenarioAllocation,
    ScenarioAvailability,
    ScenarioDependency,
    ScenarioMilestone,
    ScenarioProject,
    ScenarioTask,
)
from app.models.team import Allocation, Engineer, EngineerAvailability, Role
from app.models.user import User

__all__ = [
    "ADRComment",
    "ADRComponentLink",
    "ADRFitnessFunction",
    "ADRStakeholder",
    "ActivityEvent",
    "Allocation",
    "ArchitectureComponent",
    "ArchitectureDecision",
    "Baseline",
    "Blocker",
    "ComponentCodeBinding",
    "ComponentLink",
    "Connection",
    "Dependency",
    "DraftPlan",
    "DraftTask",
    "DriftEvent",
    "DriftScan",
    "DriftSuppression",
    "Engineer",
    "EngineerAvailability",
    "ExternalRef",
    "Holiday",
    "Initiative",
    "JiraLink",
    "Milestone",
    "Project",
    "PullRequest",
    "Retrospective",
    "RetrospectiveComment",
    "RiskItem",
    "RiskMitigation",
    "RiskSnapshot",
    "Role",
    "Scenario",
    "ScenarioAllocation",
    "ScenarioAvailability",
    "ScenarioDependency",
    "ScenarioMilestone",
    "ScenarioProject",
    "ScenarioTask",
    "Task",
    "TaskStatusHistory",
    "User",
]
