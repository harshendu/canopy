"""Request/response shapes for the scenario simulation API (see app/api/v1/scenarios.py).

View-generation endpoints reuse the live schemas in `entities.py` (GanttResponse,
CapacityResponse, BoardResponse, BurndownResponse, ForecastResponse, AlertsResponse,
InitiativeCriticalPath); only the scenario-specific shapes live here."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.models.base import DependencyType, TaskType

_read = ConfigDict(from_attributes=True)


# --- Scenario lifecycle ---
class ScenarioCreate(BaseModel):
    title: str
    description: str | None = None


class ScenarioUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    status: str | None = None  # draft | ready | archived (apply flips to "applied")


class ScenarioRead(BaseModel):
    model_config = _read
    id: int
    initiative_id: int
    title: str
    description: str | None
    status: str
    base_captured_at: datetime
    applied_at: datetime | None


class ScenarioCounts(BaseModel):
    tasks: int
    dependencies: int
    milestones: int
    allocations: int
    availability: int
    projects: int


class ScenarioDetail(ScenarioRead):
    counts: ScenarioCounts


# --- Per-project knobs ---
class ScenarioProjectUpdate(BaseModel):
    start_date: date | None = None
    target_date: date | None = None
    skip_weekends: bool | None = None


class ScenarioProjectRead(BaseModel):
    model_config = _read
    id: int
    scenario_id: int
    project_id: int
    start_date: date | None
    target_date: date | None
    skip_weekends: bool


# --- Tasks ---
class ScenarioTaskCreate(BaseModel):
    project_id: int
    name: str
    description: str | None = None
    type: TaskType = TaskType.task
    duration: int = 1
    deadline: date | None = None
    percent_complete: float = 0.0
    parent_id: int | None = None
    assignee_engineer_id: int | None = None


class ScenarioTaskUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    type: TaskType | None = None
    duration: int | None = None
    deadline: date | None = None
    percent_complete: float | None = None
    parent_id: int | None = None
    assignee_engineer_id: int | None = None


class ScenarioTaskRead(BaseModel):
    model_config = _read
    id: int
    scenario_id: int
    project_id: int
    live_task_id: int | None
    parent_id: int | None
    name: str
    description: str | None
    type: TaskType
    duration: int
    deadline: date | None
    percent_complete: float
    assignee_engineer_id: int | None
    removed: bool


# --- Dependencies ---
class ScenarioDependencyCreate(BaseModel):
    predecessor_id: int
    successor_id: int
    type: DependencyType = DependencyType.FS
    lag: int = 0


class ScenarioDependencyRead(BaseModel):
    model_config = _read
    id: int
    scenario_id: int
    predecessor_id: int
    successor_id: int
    type: DependencyType
    lag: int
    live_dep_id: int | None
    removed: bool


# --- Milestones ---
class ScenarioMilestoneCreate(BaseModel):
    project_id: int
    name: str
    description: str | None = None
    target_date: date | None = None
    status: str = "planned"


class ScenarioMilestoneUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    target_date: date | None = None
    status: str | None = None


class ScenarioMilestoneRead(BaseModel):
    model_config = _read
    id: int
    scenario_id: int
    project_id: int
    live_milestone_id: int | None
    name: str
    description: str | None
    target_date: date | None
    status: str
    removed: bool


# --- Allocations ---
class ScenarioAllocationCreate(BaseModel):
    engineer_id: int
    project_id: int | None = None
    task_id: int | None = None
    percent_allocation: float = 100.0
    capacity_hours_per_week: float = 40.0
    start_date: date | None = None
    end_date: date | None = None


class ScenarioAllocationUpdate(BaseModel):
    engineer_id: int | None = None
    project_id: int | None = None
    task_id: int | None = None
    percent_allocation: float | None = None
    capacity_hours_per_week: float | None = None
    start_date: date | None = None
    end_date: date | None = None


class ScenarioAllocationRead(BaseModel):
    model_config = _read
    id: int
    scenario_id: int
    live_allocation_id: int | None
    engineer_id: int
    project_id: int | None
    task_id: int | None
    percent_allocation: float
    capacity_hours_per_week: float
    start_date: date | None
    end_date: date | None
    removed: bool


# --- Availability ---
class ScenarioAvailabilityCreate(BaseModel):
    engineer_id: int
    start_date: date
    end_date: date
    capacity_factor: float = 0.0
    note: str | None = None


class ScenarioAvailabilityUpdate(BaseModel):
    start_date: date | None = None
    end_date: date | None = None
    capacity_factor: float | None = None
    note: str | None = None


class ScenarioAvailabilityRead(BaseModel):
    model_config = _read
    id: int
    scenario_id: int
    live_availability_id: int | None
    engineer_id: int
    start_date: date
    end_date: date
    capacity_factor: float
    note: str | None
    removed: bool


# --- Compare (scenario vs live) ---
class ScenarioProjectDelta(BaseModel):
    project_id: int
    project_key: str
    live_end: date | None
    scenario_end: date | None
    end_delta_days: int | None


class ScenarioDiffRead(BaseModel):
    tasks_added: int
    tasks_removed: int
    tasks_changed: int
    deps_added: int
    deps_removed: int
    milestones_changed: int
    allocations_changed: int
    availability_changed: int
    live_project_end: date | None
    scenario_project_end: date | None
    end_delta_days: int | None
    live_cp_working_days: int
    scenario_cp_working_days: int
    cp_delta_days: int
    per_project: list[ScenarioProjectDelta]


class ScenarioConflict(BaseModel):
    entity_type: str  # task | dependency | milestone | allocation | availability
    entity_id: int | None  # the live row id, when known
    reason: str


class ScenarioCompareResponse(BaseModel):
    scenario_id: int
    diff: ScenarioDiffRead
    conflicts: list[ScenarioConflict]


# --- Apply ---
class ScenarioApplyRequest(BaseModel):
    force: bool = False  # apply even if live changed since the snapshot


class ScenarioApplyResult(BaseModel):
    scenario_id: int
    status: str
    created: int
    updated: int
    deleted: int
    replanned_projects: list[int]
    conflicts: list[ScenarioConflict]
