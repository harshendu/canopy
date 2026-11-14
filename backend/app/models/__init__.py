"""Importing this package registers every table on SQLModel.metadata."""

from app.models import _dialects  # noqa: F401  (registers cross-dialect DDL compiler hooks)
from app.models.activity import ActivityEvent
from app.models.agent_token import AgentTokenRecord
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
from app.models.feature import FeatureFlag
from app.models.integration import (
    Connection,
    EngineerIdentity,
    ExternalRef,
    IntegrationSetting,
    JiraLink,
    PullRequest,
    TrackerBinding,
    UserConnection,
)
from app.models.leadership import InitiativeLead, LeadershipNote
from app.models.org import Pod, Team, TeamMember
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
from app.models.proposal import Proposal, ProposalItem
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
from app.models.sprint import Sprint, TaskSprintHistory
from app.models.team import Allocation, Engineer, EngineerAvailability, Role
from app.models.user import User
from app.models.workflow import Workflow, WorkflowStatus

__all__ = [
    "ADRComment",
    "ADRComponentLink",
    "ADRFitnessFunction",
    "ADRStakeholder",
    "ActivityEvent",
    "AgentTokenRecord",
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
    "EngineerIdentity",
    "ExternalRef",
    "FeatureFlag",
    "Holiday",
    "Initiative",
    "InitiativeLead",
    "IntegrationSetting",
    "JiraLink",
    "LeadershipNote",
    "Milestone",
    "Outcome",
    "Pod",
    "Project",
    "Proposal",
    "ProposalItem",
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
    "Sprint",
    "Task",
    "TaskSprintHistory",
    "TaskStatusHistory",
    "Team",
    "TeamMember",
    "TrackerBinding",
    "User",
    "UserConnection",
    "Workflow",
    "WorkflowStatus",
]
