from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.models.base import (
    ADRCommentKind,
    ADRStatus,
    DecisionRule,
    DependencyType,
    Provider,
    Reversibility,
    TaskType,
)

_read = ConfigDict(from_attributes=True)


# --- Project ---
class ProjectCreate(BaseModel):
    key: str
    name: str
    description: str | None = None
    start_date: date | None = None
    target_date: date | None = None


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    start_date: date | None = None
    target_date: date | None = None
    archived: bool | None = None
    skip_weekends: bool | None = None
    decision_rule: DecisionRule | None = None
    decision_sla_hours: int | None = None


class ProjectRead(BaseModel):
    model_config = _read
    id: int
    key: str
    name: str
    description: str | None
    start_date: date | None
    target_date: date | None
    archived: bool
    skip_weekends: bool
    decision_rule: DecisionRule
    decision_sla_hours: int


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


class EngineerUpdate(BaseModel):
    name: str | None = None
    email: str | None = None
    title: str | None = None
    role_id: int | None = None
    active: bool | None = None


class EngineerRead(BaseModel):
    model_config = _read
    id: int
    name: str
    email: str | None
    title: str | None
    role_id: int | None
    active: bool


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


# --- Architecture ---
class ComponentCreate(BaseModel):
    project_id: int
    name: str
    kind: str = "service"
    description: str | None = None
    repo_url: str | None = None


class ComponentRead(BaseModel):
    model_config = _read
    id: int
    project_id: int
    name: str
    kind: str
    description: str | None
    repo_url: str | None


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


class ADRDetail(ADRRead):
    comments: list[ADRCommentRead] = []
    review: ReviewSummaryRead


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


class PullRequestRead(BaseModel):
    model_config = _read
    id: int
    repo: str
    number: int
    title: str
    state: str
    url: str | None
    author: str | None


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


# --- Capacity heatmap ---
class CapacityRow(BaseModel):
    engineer_id: int
    engineer_name: str
    cells: dict[str, float]  # week-start ISO date -> summed allocation %


class CapacityResponse(BaseModel):
    project_id: int
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


class PortfolioResponse(BaseModel):
    projects: list[ProjectSummary]


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
