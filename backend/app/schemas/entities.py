from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, computed_field

from app.models.base import (
    ActivityKind,
    ADRCommentKind,
    ADRStatus,
    BlockerCategory,
    BlockerSeverity,
    CriterionStatus,
    DecisionRule,
    DependencyType,
    DocKind,
    DocLinkHealth,
    DocScope,
    DocSource,
    OutcomeScope,
    OutcomeStatus,
    ProjectHealth,
    Provider,
    ReadStrategy,
    RetrospectiveKind,
    Reversibility,
    RiskCategory,
    RiskGrade,
    RiskScope,
    RiskStatus,
    SpecStatus,
    TaskType,
    WriteStrategy,
)
from app.schemas.auth import UserRead
from app.services import metadata
from app.services import outcomes as outcomes_service

_read = ConfigDict(from_attributes=True)


# --- Project ---
class ProjectCreate(BaseModel):
    key: str
    name: str
    description: str | None = None
    initiative_id: int | None = None
    start_date: date | None = None
    target_date: date | None = None
    tags: list[str] = []


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    initiative_id: int | None = None
    start_date: date | None = None
    target_date: date | None = None
    archived: bool | None = None
    skip_weekends: bool | None = None
    decision_rule: DecisionRule | None = None
    decision_sla_hours: int | None = None
    tags: list[str] | None = None
    health: ProjectHealth | None = None
    status_note: str | None = None


class ProjectRead(BaseModel):
    model_config = _read
    id: int
    key: str
    name: str
    description: str | None
    initiative_id: int | None
    start_date: date | None
    target_date: date | None
    archived: bool
    skip_weekends: bool
    decision_rule: DecisionRule
    decision_sla_hours: int
    tags: list[str] = []
    health: ProjectHealth | None = None
    status_note: str | None = None
    status_updated_at: datetime | None = None


class HolidayCreate(BaseModel):
    day: date
    name: str | None = None


class HolidayRead(BaseModel):
    model_config = _read
    id: int
    project_id: int
    day: date
    name: str | None


# --- Milestone ---
class MilestoneCreate(BaseModel):
    project_id: int
    name: str
    description: str | None = None
    target_date: date | None = None
    status: str = "planned"


class MilestoneRead(BaseModel):
    model_config = _read
    id: int
    project_id: int
    name: str
    description: str | None
    target_date: date | None
    status: str


# --- Task ---
class TaskCreate(BaseModel):
    project_id: int
    name: str
    description: str | None = None
    type: TaskType = TaskType.task
    parent_id: int | None = None
    start: date | None = None
    end: date | None = None
    duration: int = 1
    percent_complete: float = 0.0
    status: str | None = None
    deadline: date | None = None
    assignee_engineer_id: int | None = None
    spec_id: int | None = None
    tags: list[str] = []
    estimate_optimistic: int | None = None
    estimate_likely: int | None = None
    estimate_pessimistic: int | None = None


class TaskUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    type: TaskType | None = None
    parent_id: int | None = None
    start: date | None = None
    end: date | None = None
    duration: int | None = None
    percent_complete: float | None = None
    status: str | None = None
    deadline: date | None = None
    assignee_engineer_id: int | None = None
    spec_id: int | None = None
    tags: list[str] | None = None
    estimate_optimistic: int | None = None
    estimate_likely: int | None = None
    estimate_pessimistic: int | None = None


class TaskRead(BaseModel):
    model_config = _read
    id: int
    project_id: int
    parent_id: int | None
    name: str
    description: str | None
    type: TaskType
    start: date | None
    end: date | None
    duration: int
    percent_complete: float
    baseline_start: date | None
    baseline_end: date | None
    is_critical: bool
    total_float: int
    status: str | None
    sprint: str | None
    deadline: date | None
    assignee_engineer_id: int | None
    spec_id: int | None = None
    tags: list[str] = []
    estimate_optimistic: int | None = None
    estimate_likely: int | None = None
    estimate_pessimistic: int | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def pert_mean(self) -> float | None:
        """The PERT expected duration, when a full 3-point estimate is set."""
        if (
            self.estimate_optimistic is None
            or self.estimate_likely is None
            or self.estimate_pessimistic is None
        ):
            return None
        return round(
            metadata.pert_mean(
                self.estimate_optimistic, self.estimate_likely, self.estimate_pessimistic
            ),
            1,
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def estimate_spread(self) -> int | None:
        """The optimistic→pessimistic uncertainty band, when both ends are set."""
        if self.estimate_optimistic is None or self.estimate_pessimistic is None:
            return None
        return metadata.estimate_spread(self.estimate_optimistic, self.estimate_pessimistic)


class TaskStatusHistoryRead(BaseModel):
    model_config = _read
    id: int
    task_id: int
    from_status: str | None
    to_status: str | None
    changed_at: datetime
    author: str | None


# --- Dependency ---
class DependencyCreate(BaseModel):
    predecessor_id: int
    successor_id: int
    type: DependencyType = DependencyType.FS
    lag: int = 0


class DependencyRead(BaseModel):
    model_config = _read
    id: int
    predecessor_id: int
    successor_id: int
    type: DependencyType
    lag: int


# --- Team ---
class RoleCreate(BaseModel):
    name: str


class RoleRead(BaseModel):
    model_config = _read
    id: int
    name: str


class EngineerCreate(BaseModel):
    name: str
    email: str | None = None
    title: str | None = None
    role_id: int | None = None
    user_id: int | None = None
    skill_tags: list[str] = []
    github_login: str | None = None
    timezone: str | None = None
    committed_hours_per_week: float | None = None


class EngineerUpdate(BaseModel):
    name: str | None = None
    email: str | None = None
    title: str | None = None
    role_id: int | None = None
    active: bool | None = None
    user_id: int | None = None
    skill_tags: list[str] | None = None
    github_login: str | None = None
    timezone: str | None = None
    committed_hours_per_week: float | None = None


class EngineerRead(BaseModel):
    model_config = _read
    id: int
    name: str
    email: str | None
    title: str | None
    role_id: int | None
    active: bool
    user_id: int | None = None
    skill_tags: list[str] = []
    github_login: str | None = None
    timezone: str | None = None
    committed_hours_per_week: float | None = None


class AllocationCreate(BaseModel):
    engineer_id: int
    project_id: int | None = None
    task_id: int | None = None
    percent_allocation: float = 100.0
    capacity_hours_per_week: float = 40.0
    start_date: date | None = None
    end_date: date | None = None


class AllocationRead(BaseModel):
    model_config = _read
    id: int
    engineer_id: int
    project_id: int | None
    task_id: int | None
    percent_allocation: float
    capacity_hours_per_week: float
    start_date: date | None
    end_date: date | None


class AvailabilityCreate(BaseModel):
    engineer_id: int
    start_date: date
    end_date: date
    capacity_factor: float = 0.0  # 0..1
    note: str | None = None


class AvailabilityUpdate(BaseModel):
    start_date: date | None = None
    end_date: date | None = None
    capacity_factor: float | None = None
    note: str | None = None


class AvailabilityRead(BaseModel):
    model_config = _read
    id: int
    engineer_id: int
    start_date: date
    end_date: date
    capacity_factor: float
    note: str | None = None


# --- Architecture ---
class ComponentCreate(BaseModel):
    project_id: int
    name: str
    kind: str = "service"
    description: str | None = None
    repo_url: str | None = None
    owner_engineer_id: int | None = None
    criticality: str | None = None
    tier: str | None = None
    observability_url: str | None = None


class ComponentRead(BaseModel):
    model_config = _read
    id: int
    project_id: int
    name: str
    kind: str
    description: str | None
    repo_url: str | None
    owner_engineer_id: int | None = None
    criticality: str | None = None
    tier: str | None = None
    observability_url: str | None = None


class ADRCreate(BaseModel):
    project_id: int
    title: str
    status: ADRStatus = ADRStatus.proposed
    context: str | None = None
    decision: str | None = None
    consequences: str | None = None
    alternatives: list[str] = []
    reversibility: Reversibility | None = None
    decision_owner_id: int | None = None
    proposed_by_id: int | None = None
    decide_by: date | None = None
    rfc_url: str | None = None
    supersedes_id: int | None = None
    pr_links: list[str] = []
    component_ids: list[int] = []
    stakeholder_ids: list[int] = []


class ADRUpdate(BaseModel):
    title: str | None = None
    status: ADRStatus | None = None
    context: str | None = None
    decision: str | None = None
    consequences: str | None = None
    alternatives: list[str] | None = None
    reversibility: Reversibility | None = None
    decision_owner_id: int | None = None
    proposed_by_id: int | None = None
    decide_by: date | None = None
    rfc_url: str | None = None
    supersedes_id: int | None = None
    pr_links: list[str] | None = None
    component_ids: list[int] | None = None
    stakeholder_ids: list[int] | None = None


class ADRRead(BaseModel):
    model_config = _read
    id: int
    project_id: int
    number: int
    title: str
    status: ADRStatus
    context: str | None
    decision: str | None
    consequences: str | None
    alternatives: list[str] = []
    reversibility: Reversibility | None = None
    decision_owner_id: int | None = None
    proposed_by_id: int | None = None
    decide_by: date | None = None
    rfc_url: str | None = None
    supersedes_id: int | None
    pr_links: list[str]
    component_ids: list[int] = []
    stakeholder_ids: list[int] = []


class ADRCommentCreate(BaseModel):
    body: str
    kind: ADRCommentKind = ADRCommentKind.comment
    engineer_id: int | None = None
    author_name: str | None = None


class ADRCommentRead(BaseModel):
    model_config = _read
    id: int
    adr_id: int
    engineer_id: int | None
    author_name: str | None
    body: str
    kind: ADRCommentKind
    created_at: datetime


class ReviewSummaryRead(BaseModel):
    required: int
    approved: int
    changes_requested: int
    rejected: int
    pending: int
    can_accept: bool


class FitnessFunctionCreate(BaseModel):
    kind: str = "forbid"  # forbid | require
    source_component_id: int
    target_component_id: int
    description: str | None = None


class FitnessFunctionRead(BaseModel):
    model_config = _read
    id: int
    adr_id: int
    kind: str
    source_component_id: int
    target_component_id: int
    description: str | None


class ADRDetail(ADRRead):
    comments: list[ADRCommentRead] = []
    review: ReviewSummaryRead
    fitness_functions: list[FitnessFunctionRead] = []


class DecisionQueueItem(BaseModel):
    id: int
    project_id: int
    number: int
    title: str
    status: ADRStatus
    bucket: str  # needs_triage | stuck | discussing | deferred_soon
    reason: str
    overdue: bool
    decide_by: date | None
    age_hours: float


class DecisionQueueResponse(BaseModel):
    items: list[DecisionQueueItem]


class ADRImportRequest(BaseModel):
    project_id: int
    provider: Provider  # github | gdrive
    connection_id: int
    ref: str  # GitHub file path or Google Drive file id


class ImpactResponse(BaseModel):
    adr_id: int
    direct_component_ids: list[int]
    downstream_component_ids: list[int]


class ComponentLinkCreate(BaseModel):
    source_id: int
    target_id: int
    kind: str = "depends_on"


class ComponentLinkRead(BaseModel):
    model_config = _read
    id: int
    source_id: int
    target_id: int
    kind: str


# --- Connectors ---
class ConnectionCreate(BaseModel):
    provider: Provider
    name: str
    token: str | None = None  # plaintext; encrypted before storage
    refresh_token: str | None = None
    config: dict = {}


class ConnectionRead(BaseModel):
    model_config = _read
    id: int
    provider: Provider
    name: str
    config: dict
    watermark: str | None
    active: bool
    authorized: bool
    # Per-user SSO (Phase 2): whether this provider permits per-user connect (admin policy),
    # and whether the current caller has connected their own account to this connection.
    allow_user_connect: bool = False
    user_connected: bool = False
    # Integration policy (Phase 1/3): so the UI can show when reads/writes are MCP-managed.
    read_strategy: ReadStrategy = ReadStrategy.direct
    write_strategy: WriteStrategy = WriteStrategy.direct


class PullRequestRead(BaseModel):
    model_config = _read
    id: int
    repo: str
    number: int
    title: str
    state: str
    url: str | None
    author: str | None
    task_id: int | None = None


# --- Jira ticket linking (link a Jira ticket → canopy project/initiative) ---
class JiraLinkCreate(BaseModel):
    connection_id: int  # the Jira connection to read the ticket(s) through
    jira_key: str  # the root Jira ticket to link, e.g. "PROJ-123"
    target_type: Literal["project", "initiative"]
    target_id: int


class JiraLinkRead(BaseModel):
    model_config = _read
    id: int
    connection_id: int
    jira_issue_id: str
    jira_key: str
    jira_issue_type: str | None
    target_type: str
    target_id: int
    last_synced_at: datetime | None
    created_at: datetime


class JiraLinkSyncResult(BaseModel):
    """What a link create / resync mapped into canopy (idempotent via ExternalRef)."""

    link: JiraLinkRead
    projects_created: int = 0
    projects_linked: int = 0
    tasks_created: int = 0
    tasks_updated: int = 0
    skipped: int = 0
    created_project_ids: list[int] = []
    notes: list[str] = []


# --- Gantt / scheduling ---
class GanttTask(BaseModel):
    id: int
    text: str
    start_date: date | None
    end_date: date | None
    baseline_start: date | None
    baseline_end: date | None
    deadline: date | None
    duration: int
    progress: float
    parent: int
    type: TaskType
    is_critical: bool
    total_float: int


class GanttLink(BaseModel):
    id: int
    source: int
    target: int
    type: DependencyType
    lag: int


class GanttResponse(BaseModel):
    project_id: int
    tasks: list[GanttTask]
    links: list[GanttLink]


class ReplanResult(BaseModel):
    project_id: int
    scheduled_tasks: int
    critical_path: list[int]
    project_end: date | None
    deadline_violations: list[int] = []


class WhatIfRequest(BaseModel):
    # task_id -> hypothetical duration (working days); applied without persisting.
    duration_overrides: dict[int, int] = {}


# --- Flow board (Kanban + WIP + aging) ---
class BoardTaskRead(BaseModel):
    id: int
    name: str
    status: str
    assignee_engineer_id: int | None
    is_done: bool
    age_days: int
    aging: bool


class BoardLaneRead(BaseModel):
    status: str
    is_done: bool
    wip: int
    tasks: list[BoardTaskRead]


class BoardResponse(BaseModel):
    project_id: int
    lanes: list[BoardLaneRead]
    cycle_time_p85_days: int | None
    aging_count: int


# --- Blockers (flagged impediments) ---
class BlockerCreate(BaseModel):
    reason: str
    raised_by_engineer_id: int | None = None  # defaults to the caller's engineer
    blocking_task_id: int | None = None
    category: BlockerCategory | None = None
    severity: BlockerSeverity | None = None
    owner_engineer_id: int | None = None
    needed_by: date | None = None


class BlockerUpdate(BaseModel):
    reason: str | None = None
    resolved: bool | None = None  # True -> set resolved_at=now; False -> reopen
    category: BlockerCategory | None = None
    severity: BlockerSeverity | None = None
    owner_engineer_id: int | None = None
    needed_by: date | None = None


class BlockerRead(BaseModel):
    model_config = _read
    id: int
    task_id: int
    reason: str
    raised_by_engineer_id: int | None
    blocking_task_id: int | None
    resolved_at: datetime | None
    created_at: datetime
    category: BlockerCategory | None = None
    severity: BlockerSeverity | None = None
    owner_engineer_id: int | None = None
    needed_by: date | None = None


# --- Probabilistic forecast (Monte-Carlo throughput) ---
class ForecastResponse(BaseModel):
    scope: str  # "project" | "initiative"
    id: int
    sufficient: bool
    reason: str | None = None
    remaining_items: int
    history_weeks: int
    trials: int
    p50_weeks: int | None = None
    p85_weeks: int | None = None
    p50_date: date | None = None
    p85_date: date | None = None


# --- Baseline (logged re-baseline events) ---
class BaselineRequest(BaseModel):
    note: str | None = None  # why the baseline is being (re)set


class BaselineRead(BaseModel):
    model_config = _read
    id: int
    project_id: int
    note: str | None
    task_count: int
    project_end: date | None
    created_at: datetime


# --- Capacity heatmap ---
class CapacityRow(BaseModel):
    engineer_id: int
    engineer_name: str
    cells: dict[str, float]  # week-start ISO date -> summed allocation %
    projects: list[str] = []  # contributing project keys (org-wide view)
    # week-start ISO date -> availability factor (0..1); only weeks below full capacity.
    availability: dict[str, float] = {}


class CapacityResponse(BaseModel):
    project_id: int | None  # None = org-wide (summed across all projects)
    weeks: list[str]  # week-start ISO dates
    rows: list[CapacityRow]


# --- Portfolio ---
class ProjectSummary(BaseModel):
    id: int
    key: str
    name: str
    total_tasks: int
    completed_tasks: int
    avg_percent_complete: float
    critical_tasks: int
    project_end: date | None
    target_date: date | None
    risk_score: int
    risk_level: str
    drift_score: int
    drift_level: str
    tags: list[str] = []
    health: ProjectHealth | None = None
    status_note: str | None = None
    open_risks: int = 0  # open/mitigating register risks (separate from the risk score)


class PortfolioResponse(BaseModel):
    projects: list[ProjectSummary]


# --- Initiatives (program layer above projects) ---
class InitiativeCreate(BaseModel):
    key: str
    name: str
    outcome_statement: str | None = None
    start_date: date | None = None
    target_date: date | None = None
    owner_engineer_id: int | None = None
    tags: list[str] = []


class InitiativeUpdate(BaseModel):
    name: str | None = None
    outcome_statement: str | None = None
    start_date: date | None = None
    target_date: date | None = None
    owner_engineer_id: int | None = None
    archived: bool | None = None
    tags: list[str] | None = None
    health: ProjectHealth | None = None
    status_note: str | None = None


class InitiativeRead(BaseModel):
    model_config = _read
    id: int
    key: str
    name: str
    outcome_statement: str | None
    start_date: date | None
    target_date: date | None
    owner_engineer_id: int | None
    archived: bool
    tags: list[str] = []
    health: ProjectHealth | None = None
    status_note: str | None = None
    status_updated_at: datetime | None = None


class CriticalPathNode(BaseModel):
    task_id: int
    name: str
    project_id: int
    project_key: str
    es: int  # earliest-start offset (working days from the chain's origin)
    ef: int  # earliest-finish offset
    duration: int


class CriticalPathHandoff(BaseModel):
    predecessor_id: int
    successor_id: int
    from_project_key: str
    to_project_key: str


class InitiativeCriticalPath(BaseModel):
    """The critical path across an initiative's sub-projects (structural, in working days)."""

    initiative_id: int
    total_working_days: int
    spans_projects: bool
    tasks: list[CriticalPathNode]  # the critical chain, earliest-first
    handoffs: list[CriticalPathHandoff]  # cross-project edges on the critical path


class InitiativeDigest(BaseModel):
    """A manage-by-exception weekly health roll-up for an initiative (leads with what needs
    attention). Delivery (Slack/email) is a hook over this — see §I."""

    initiative_id: int
    name: str
    generated_on: date
    headline: str
    on_track: bool | None
    risk_level: str
    drift_level: str
    p85_date: date | None
    open_blockers: int
    open_decisions: int
    attention: list[str]  # the exception list
    outcomes: list[str]  # "statement (status)"
    markdown: str


class InitiativeRollup(BaseModel):
    """Health rolled up across an initiative's sub-projects."""

    initiative: InitiativeRead
    projects: list[ProjectSummary]
    total_tasks: int
    completed_tasks: int
    avg_percent_complete: float
    project_end: date | None  # latest end across sub-projects
    risk_score: int  # the riskiest sub-project drives initiative risk
    risk_level: str
    drift_score: int  # worst drift across sub-projects
    drift_level: str
    open_decisions: int  # ADRs proposed / under discussion across the initiative
    on_track: bool | None  # latest end <= target_date (None if no target)


# --- Alerts / digest ---
class AlertRead(BaseModel):
    kind: str
    severity: str
    message: str
    entity_type: str | None = None
    entity_id: int | None = None


class AlertsResponse(BaseModel):
    project_id: int
    alerts: list[AlertRead]


# --- Burndown ---
class BurndownPoint(BaseModel):
    week: date
    total: int
    completed: int
    remaining: int


class BurndownResponse(BaseModel):
    project_id: int
    points: list[BurndownPoint]


# --- Risk dashboard ---
class RiskIndicatorRead(BaseModel):
    key: str
    label: str
    score: int
    summary: str
    details: list[str]


class RiskFamilyRead(BaseModel):
    key: str
    label: str
    available: bool
    score: int
    weight: float
    indicators: list[RiskIndicatorRead]


class RiskMitigationCreate(BaseModel):
    indicator_key: str
    note: str
    owner_engineer_id: int | None = None
    check_in: date | None = None


class RiskMitigationUpdate(BaseModel):
    note: str | None = None
    owner_engineer_id: int | None = None
    check_in: date | None = None
    resolved: bool | None = None


class RiskMitigationRead(BaseModel):
    model_config = _read
    id: int
    project_id: int
    indicator_key: str
    note: str
    owner_engineer_id: int | None
    check_in: date | None
    resolved: bool


class RiskSnapshotRead(BaseModel):
    model_config = _read
    id: int
    project_id: int
    score: int
    level: str
    created_at: datetime


class RiskResponse(BaseModel):
    project_id: int
    score: int
    level: str
    confidence: str  # high | low — how much of the picture has data
    confidence_note: str
    families: list[RiskFamilyRead]
    mitigations: list[RiskMitigationRead]


# --- Risk register (human-tracked RAID risks; separate from the computed score above) ---
class RiskItemCreate(BaseModel):
    scope_level: RiskScope
    scope_id: int
    title: str
    description: str | None = None
    category: RiskCategory = RiskCategory.technical
    probability: RiskGrade = RiskGrade.medium
    impact: RiskGrade = RiskGrade.medium
    status: RiskStatus = RiskStatus.open
    owner_engineer_id: int | None = None
    mitigation: str | None = None
    contingency: str | None = None
    target_resolution_date: date | None = None


class RiskItemUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    category: RiskCategory | None = None
    probability: RiskGrade | None = None
    impact: RiskGrade | None = None
    status: RiskStatus | None = None
    owner_engineer_id: int | None = None
    mitigation: str | None = None
    contingency: str | None = None
    target_resolution_date: date | None = None


class RiskItemClose(BaseModel):
    status: RiskStatus = RiskStatus.resolved  # resolved | accepted | occurred
    note: str | None = None  # appended to the mitigation log


class RiskItemRead(BaseModel):
    model_config = _read
    id: int
    scope_level: RiskScope
    scope_id: int
    title: str
    description: str | None
    category: RiskCategory
    probability: RiskGrade
    impact: RiskGrade
    status: RiskStatus
    owner_engineer_id: int | None
    mitigation: str | None
    contingency: str | None
    target_resolution_date: date | None
    resolved_at: datetime | None
    created_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def probability_value(self) -> int:
        return metadata.risk_grade_value(self.probability)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def impact_value(self) -> int:
        return metadata.risk_grade_value(self.impact)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def exposure(self) -> int:
        return metadata.risk_exposure(self.probability, self.impact)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def exposure_level(self) -> str:
        return metadata.exposure_level(metadata.risk_exposure(self.probability, self.impact))


# --- Architecture drift ---
class CodeBindingCreate(BaseModel):
    component_id: int
    path_glob: str
    connection_id: int | None = None
    repo: str | None = None
    module_prefix: str | None = None


class CodeBindingRead(BaseModel):
    model_config = _read
    id: int
    component_id: int
    connection_id: int | None
    repo: str | None
    path_glob: str
    module_prefix: str | None


class ImplicitSignalIn(BaseModel):
    kind: str  # new_package | new_dependency | new_service | new_datastore
    summary: str
    suspected_cause: str | None = None
    component_id: int | None = None


class DriftScanRequest(BaseModel):
    """Observations supplied by the Drift Sentinel (or a crawler). Declared edges and
    accepted ADRs are loaded server-side; these are what the *code* actually shows."""

    actual_edges: list[tuple[int, int]] = []
    inactive_component_ids: list[int] = []
    implicit_signals: list[ImplicitSignalIn] = []


class DriftEventRead(BaseModel):
    model_config = _read
    id: int
    project_id: int
    kind: str
    rule_key: str
    summary: str
    detail: str | None
    suspected_cause: str | None
    affected_component_ids: list[int]
    status: str


class DriftResponse(BaseModel):
    project_id: int
    score: int
    level: str
    events: list[DriftEventRead]
    last_scanned_at: datetime | None = None  # when drift was last assessed (any scan)
    scan_due: bool = False  # code bindings exist and the last scan is missing or stale


class DriftReconcileRequest(BaseModel):
    action: str  # accepted | rejected | false_positive


class DriftReconcileResponse(BaseModel):
    event: DriftEventRead
    created_adr_id: int | None = None
    created_task_id: int | None = None


# --- Activity / observability events ---
class ActivityEventCreate(BaseModel):
    kind: ActivityKind
    summary: str
    component_id: int | None = None
    source: str = "ci"
    reference: str | None = None


class ActivityEventRead(BaseModel):
    model_config = _read
    id: int
    project_id: int
    kind: str
    summary: str
    component_id: int | None
    source: str
    reference: str | None
    created_at: datetime


# --- Retrospectives & postmortems ---
class RetrospectiveCreate(BaseModel):
    kind: RetrospectiveKind = RetrospectiveKind.project_retro
    title: str | None = None  # defaults from the project/kind when omitted
    body: str | None = None  # for postmortems; project retros auto-seed if omitted
    affected_component_ids: list[int] = []


class RetrospectiveUpdate(BaseModel):
    title: str | None = None
    body: str | None = None
    status: str | None = None
    affected_component_ids: list[int] | None = None


class RetrospectiveCommentCreate(BaseModel):
    body: str
    engineer_id: int | None = None
    author_name: str | None = None


class RetrospectiveCommentRead(BaseModel):
    model_config = _read
    id: int
    retrospective_id: int
    engineer_id: int | None
    author_name: str | None
    body: str
    created_at: datetime


class RetrospectiveRead(BaseModel):
    model_config = _read
    id: int
    project_id: int
    kind: RetrospectiveKind
    title: str
    body: str | None
    status: str
    affected_component_ids: list[int]


class RetrospectiveDetail(RetrospectiveRead):
    comments: list[RetrospectiveCommentRead] = []


class RetroFollowUpRequest(BaseModel):
    action: str  # task | adr
    title: str


class RetroFollowUpResponse(BaseModel):
    created_task_id: int | None = None
    created_adr_id: int | None = None


# --- Draft plans (review → create Jira tickets) ---
class DraftPlanCreate(BaseModel):
    title: str
    description: str | None = None
    source: str | None = None  # where the plan came from (a design doc / PRD / url)


class DraftPlanUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    status: str | None = None  # draft | synced | archived
    source: str | None = None


class DraftPlanRead(BaseModel):
    model_config = _read
    id: int
    project_id: int
    title: str
    description: str | None
    status: str
    source: str | None
    synced_at: datetime | None
    created_at: datetime


class DraftTaskCreate(BaseModel):
    name: str
    description: str | None = None
    type: TaskType = TaskType.task
    parent_id: int | None = None  # a summary draft-task id, to nest (epic → story)
    estimate_days: int = 1
    story_points: float | None = None
    sort_order: int = 0


class DraftTaskUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    type: TaskType | None = None
    parent_id: int | None = None
    estimate_days: int | None = None
    story_points: float | None = None
    sort_order: int | None = None


class DraftTaskRead(BaseModel):
    model_config = _read
    id: int
    plan_id: int
    parent_id: int | None
    name: str
    description: str | None
    type: TaskType
    estimate_days: int
    story_points: float | None
    sort_order: int
    jira_issue_id: str | None
    jira_key: str | None


class DraftPlanDetail(DraftPlanRead):
    tasks: list[DraftTaskRead] = []


class DraftPushRequest(BaseModel):
    # The Jira connection to push to. Omit to auto-resolve the project's Jira connection.
    connection_id: int | None = None


class DraftPushTaskResult(BaseModel):
    draft_task_id: int
    name: str
    action: str  # created | updated | failed
    jira_key: str | None = None
    error: str | None = None


class DraftPushResult(BaseModel):
    plan_id: int
    connection_id: int
    created: int
    updated: int
    failed: int
    results: list[DraftPushTaskResult]


# --- MCP-orchestrated ingest (Claude pushes external data into canopy idempotently) ---
class IngestIssue(BaseModel):
    """A normalized external issue (e.g. a Jira issue Claude read with its own connector)."""

    external_id: str  # provider issue id (opaque, stable) — the ExternalRef key
    external_key: str | None = None  # human key, e.g. "PROJ-123"
    summary: str
    status: str | None = None  # mirrored read-only (Jira stays status owner)
    issue_type: str | None = None  # epic types become summary tasks
    parent_external_id: str | None = None
    updated: str | None = None  # remote "updated" timestamp, for staleness checks


class IngestIssuesRequest(BaseModel):
    issues: list[IngestIssue]


class IngestPullRequest(BaseModel):
    """A normalized external pull request for the PR cache."""

    number: int
    title: str
    state: str  # open | closed
    url: str | None = None
    author: str | None = None
    updated: str | None = None


class IngestPullRequestsRequest(BaseModel):
    pull_requests: list[IngestPullRequest]


class IngestResult(BaseModel):
    provider: str
    created: int
    updated: int
    skipped: int


class FileIngestResult(IngestResult):
    """Ingest result for a dropped/uploaded file — adds how many rows parsed and per-row errors
    (invalid rows are skipped, not fatal)."""

    parsed: int
    errors: list[str] = []


# --- Draft push write-back (write_strategy=mcp: Claude creates tickets, records ids here) ---
class DraftPushRecord(BaseModel):
    draft_task_id: int
    jira_issue_id: str
    jira_key: str | None = None


class DraftRecordPushRequest(BaseModel):
    results: list[DraftPushRecord]


class DraftRecordPushResult(BaseModel):
    plan_id: int
    recorded: int
    status: str  # the draft plan's resulting status (e.g. "synced")


# --- Exports (snapshots viewable outside canopy) ---
class ExportToDriveRequest(BaseModel):
    connection_id: int  # a Google Drive connection to upload into
    fmt: str = "pdf"  # pdf | csv


class ExportToDriveResult(BaseModel):
    file_id: str
    name: str
    link: str | None = None  # Drive webViewLink, when returned


# --- Engineer workspace (/me) ---
class MyTodayResponse(BaseModel):
    user: UserRead
    focus_tasks: list[TaskRead]  # assigned, open, critical or due soon
    decisions_to_push: list[ADRRead]  # owned proposed/under_discussion


class MyWorkspaceResponse(BaseModel):
    user: UserRead
    engineer: EngineerRead | None
    assigned_tasks: list[TaskRead]
    owned_decisions: list[ADRRead]
    stakeholder_decisions: list[ADRRead]
    blockers: list[BlockerRead] = []  # open blockers on my tasks or raised by me


# --- Document graph (link, don't store) ---
class DocReferenceCreate(BaseModel):
    scope_level: DocScope
    scope_id: int
    url: str
    kind: DocKind = DocKind.other
    title: str | None = None
    owner_engineer_id: int | None = None


class DocReferenceUpdate(BaseModel):
    kind: DocKind | None = None
    title: str | None = None
    url: str | None = None
    owner_engineer_id: int | None = None
    link_health: DocLinkHealth | None = None


class DocReferenceRead(BaseModel):
    model_config = _read
    id: int
    scope_level: DocScope
    scope_id: int
    kind: DocKind
    title: str | None
    url: str
    source: DocSource
    owner_engineer_id: int | None
    connection_id: int | None
    external_field: str | None
    link_health: DocLinkHealth
    last_checked_at: datetime | None
    created_at: datetime


class DocCoverageRead(BaseModel):
    scope_level: DocScope
    scope_id: int
    total_references: int
    present: list[DocKind]
    missing: list[DocKind]  # expected kinds with no reference — a coverage gap
    by_kind: dict[str, int]


# --- A task's external resource links (Jira issue + GitHub PRs + design docs) ---
class JiraIssueLink(BaseModel):
    key: str  # human key, e.g. "HELIX-101"
    url: str | None  # browse URL, when the connection exposes a site (None for OAuth API bases)


class TaskExternalLinksRead(BaseModel):
    """Everything that links a task out to the systems that own the work: its Jira issue,
    the GitHub PRs implementing it, and the design docs (GitHub/Drive) scoped to it."""

    jira: JiraIssueLink | None
    pull_requests: list[PullRequestRead]
    docs: list[DocReferenceRead]


# --- Jira epic → doc field mapping (the AI-driven setup) ---
class DocFieldMappingEntry(BaseModel):
    jira_field: str  # the Jira field id, e.g. "customfield_10042" or "description"
    field_name: str | None = None  # the human label, for display
    doc_kind: DocKind


class DocFieldMapping(BaseModel):
    mappings: list[DocFieldMappingEntry] = []
    parse_description_links: bool = False  # sweep links in the epic description as `other`
    parse_remote_links: bool = True  # harvest Jira remote links (Confluence/web) as `other`


class FieldUrlCandidate(BaseModel):
    field_id: str
    field_name: str | None = None
    urls: list[str]


class EpicDocSample(BaseModel):
    key: str | None
    summary: str | None
    field_candidates: list[FieldUrlCandidate]
    description_urls: list[str]
    remote_links: list[dict] = []


class EpicDocSampleResponse(BaseModel):
    """Sample of epics' URL-bearing fields so an agent can propose a field→kind mapping."""

    epics: list[EpicDocSample]
    distinct_fields: list[FieldUrlCandidate]  # union of candidate fields across the sample


class HarvestDocsResult(BaseModel):
    references_created: int
    references_updated: int
    skipped: int
    epics_scanned: int
    notes: list[str] = []


# --- Specs (spec-driven development) ---
class SpecCriterionCreate(BaseModel):
    text: str
    verification: str | None = None
    sort_order: int = 0


class SpecCriterionUpdate(BaseModel):
    text: str | None = None
    status: CriterionStatus | None = None
    verification: str | None = None
    sort_order: int | None = None


class SpecCriterionRead(BaseModel):
    model_config = _read
    id: int
    spec_id: int
    text: str
    status: CriterionStatus
    verification: str | None
    sort_order: int
    created_at: datetime


class SpecCreate(BaseModel):
    project_id: int
    title: str
    problem: str
    context: str | None = None
    out_of_scope: str | None = None
    status: SpecStatus = SpecStatus.draft
    owner_engineer_id: int | None = None
    adr_id: int | None = None
    source_url: str | None = None


class SpecUpdate(BaseModel):
    title: str | None = None
    problem: str | None = None
    context: str | None = None
    out_of_scope: str | None = None
    status: SpecStatus | None = None
    owner_engineer_id: int | None = None
    adr_id: int | None = None
    source_url: str | None = None


class SpecRead(BaseModel):
    model_config = _read
    id: int
    project_id: int
    title: str
    problem: str
    context: str | None
    out_of_scope: str | None
    status: SpecStatus
    owner_engineer_id: int | None
    adr_id: int | None
    source_url: str | None
    created_at: datetime


class SpecLinkedTask(BaseModel):
    model_config = _read
    id: int
    name: str
    status: str | None
    percent_complete: float
    is_critical: bool


class SpecDetail(SpecRead):
    """The self-audit bundle: the spec, its acceptance criteria, the tasks implementing it,
    and the computed readiness (met / effective criteria)."""

    criteria: list[SpecCriterionRead] = []
    linked_tasks: list[SpecLinkedTask] = []
    criteria_total: int = 0  # excludes waived
    criteria_met: int = 0
    acceptance_ratio: float = 0.0  # met / effective total


# --- Delivery metrics (DORA + flow; team-level only) ---
class DoraMetricsRead(BaseModel):
    model_config = _read
    window_weeks: float
    deploys: int
    deploy_frequency_per_week: float
    failures: int
    change_fail_rate: float | None
    recovered_incidents: int
    mean_recovery_hours: float | None
    median_recovery_hours: float | None


class FlowMetricsRead(BaseModel):
    model_config = _read
    completed_items: int
    throughput_per_week: float | None
    cycle_time_median_days: float | None
    cycle_time_p85_days: int | None
    wip: int
    aging_wip: int
    sufficient: bool
    reason: str | None = None


class DeliveryMetricsRead(BaseModel):
    scope_level: Literal["project", "initiative"]
    scope_id: int
    window_weeks: int
    dora: DoraMetricsRead
    flow: FlowMetricsRead
    notes: list[str] = []


# --- Outcomes (outcomes over output) ---
class OutcomeCreate(BaseModel):
    scope_level: OutcomeScope
    scope_id: int
    statement: str
    metric: str | None = None
    unit: str | None = None
    baseline_value: float | None = None
    target_value: float | None = None
    current_value: float | None = None
    status: OutcomeStatus = OutcomeStatus.pending
    target_date: date | None = None
    owner_engineer_id: int | None = None


class OutcomeUpdate(BaseModel):
    statement: str | None = None
    metric: str | None = None
    unit: str | None = None
    baseline_value: float | None = None
    target_value: float | None = None
    current_value: float | None = None
    status: OutcomeStatus | None = None
    target_date: date | None = None
    owner_engineer_id: int | None = None


class OutcomeRead(BaseModel):
    model_config = _read
    id: int
    scope_level: OutcomeScope
    scope_id: int
    statement: str
    metric: str | None
    unit: str | None
    baseline_value: float | None
    target_value: float | None
    current_value: float | None
    status: OutcomeStatus
    target_date: date | None
    owner_engineer_id: int | None
    created_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def progress_ratio(self) -> float | None:
        """How far current sits on the baseline→target scale (None until measurable)."""
        return outcomes_service.progress(
            self.baseline_value, self.target_value, self.current_value
        )
