"""Importing this package registers every table on SQLModel.metadata."""

from app.models import _dialects  # noqa: F401  (registers cross-dialect DDL compiler hooks)
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
from app.models.doc import DocReference
from app.models.draft import DraftPlan, DraftTask
from app.models.integration import (
    Connection,
    ExternalRef,
    IntegrationSetting,
    JiraLink,
    PullRequest,
)
from app.models.outcome import Outcome
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
from app.models.spec import Spec, SpecCriterion
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
    "DocReference",
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
    "IntegrationSetting",
    "JiraLink",
    "Milestone",
    "Outcome",
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
    "Spec",
    "SpecCriterion",
    "Task",
    "TaskStatusHistory",
    "User",
]
