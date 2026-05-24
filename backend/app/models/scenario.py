"""Scenario simulation: a durable, named, initiative-scoped "what-if" workspace.

Creating a scenario **snapshots** the initiative's planning data (tasks, dependencies,
milestones, allocations, availability + per-project knobs) into the scenario tables below,
which the architect then edits freely. The analysis views are recomputed over the snapshot
(see `app/services/scenario_engine.py`) and compared to live (`scenario_diff.py`); only an
explicit **apply** writes the changes back to canopy's planning layer (`scenario_apply.py`).

Projects are NOT cloned (they own keys/connectors/ADRs/history) — scenario rows reference the
**live** `project_id`. Every editable row carries provenance: `live_*_id` (the row it was cloned
from; None means added in the scenario) plus a `removed` tombstone. At apply time that maps to
update / delete / create. A scenario is a deliberately *frozen* branch (like a draft plan before
push); `base_captured_at` is the staleness watermark used to detect live edits made afterwards.
"""

from datetime import date, datetime

from sqlalchemy import Column, Text
from sqlmodel import Field

from app.models.base import DependencyType, TaskType, TimestampMixin, utcnow

# Scenario lifecycle (canopy-local, not a Jira status).
SCENARIO_STATUSES = ("draft", "ready", "applied", "archived")


class Scenario(TimestampMixin, table=True):
    """A reviewable, not-yet-applied what-if branch of an initiative."""

    id: int | None = Field(default=None, primary_key=True)
    initiative_id: int = Field(foreign_key="initiative.id", index=True)
    title: str
    description: str | None = Field(default=None, sa_column=Column(Text))
    status: str = "draft"  # draft | ready | applied | archived
    base_captured_at: datetime = Field(default_factory=utcnow)  # staleness watermark
    applied_at: datetime | None = None


class ScenarioProject(TimestampMixin, table=True):
    """Per live project the scenario spans — varies project-level scheduling knobs without
    mutating the live `Project`."""

    id: int | None = Field(default=None, primary_key=True)
    scenario_id: int = Field(foreign_key="scenario.id", index=True)
    project_id: int = Field(foreign_key="project.id", index=True)  # the LIVE project
    start_date: date | None = None
    target_date: date | None = None
    skip_weekends: bool = False


class ScenarioTask(TimestampMixin, table=True):
    """A task inside a scenario. Its `id` is the stable key scenario dependencies reference.
    `start/end/is_critical/total_float` are NOT stored — they are recomputed on every read."""

    id: int | None = Field(default=None, primary_key=True)
    scenario_id: int = Field(foreign_key="scenario.id", index=True)
    project_id: int = Field(foreign_key="project.id", index=True)  # the LIVE project
    live_task_id: int | None = Field(default=None, foreign_key="task.id", index=True)
    parent_id: int | None = Field(default=None, foreign_key="scenariotask.id", index=True)
    name: str
    description: str | None = Field(default=None, sa_column=Column(Text))
    type: TaskType = Field(default=TaskType.task)
    duration: int = 1
    deadline: date | None = None
    percent_complete: float = 0.0
    assignee_engineer_id: int | None = Field(default=None, foreign_key="engineer.id")
    removed: bool = False


class ScenarioDependency(TimestampMixin, table=True):
    id: int | None = Field(default=None, primary_key=True)
    scenario_id: int = Field(foreign_key="scenario.id", index=True)
    predecessor_id: int = Field(foreign_key="scenariotask.id", index=True)
    successor_id: int = Field(foreign_key="scenariotask.id", index=True)
    type: DependencyType = Field(default=DependencyType.FS)
    lag: int = 0
    live_dep_id: int | None = Field(default=None, foreign_key="dependency.id", index=True)
    removed: bool = False


class ScenarioMilestone(TimestampMixin, table=True):
    id: int | None = Field(default=None, primary_key=True)
    scenario_id: int = Field(foreign_key="scenario.id", index=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    live_milestone_id: int | None = Field(default=None, foreign_key="milestone.id", index=True)
    name: str
    description: str | None = Field(default=None, sa_column=Column(Text))
    target_date: date | None = None
    status: str = "planned"
    removed: bool = False


class ScenarioAllocation(TimestampMixin, table=True):
    id: int | None = Field(default=None, primary_key=True)
    scenario_id: int = Field(foreign_key="scenario.id", index=True)
    live_allocation_id: int | None = Field(default=None, foreign_key="allocation.id", index=True)
    engineer_id: int = Field(foreign_key="engineer.id", index=True)
    project_id: int | None = Field(default=None, foreign_key="project.id", index=True)
    task_id: int | None = Field(default=None, foreign_key="scenariotask.id")  # scenario-local
    percent_allocation: float = 100.0
    capacity_hours_per_week: float = 40.0
    start_date: date | None = None
    end_date: date | None = None
    removed: bool = False


class ScenarioAvailability(TimestampMixin, table=True):
    """Scenario override/addition of engineer availability (cf. live `EngineerAvailability`)."""

    id: int | None = Field(default=None, primary_key=True)
    scenario_id: int = Field(foreign_key="scenario.id", index=True)
    live_availability_id: int | None = Field(
        default=None, foreign_key="engineeravailability.id", index=True
    )
    engineer_id: int = Field(foreign_key="engineer.id", index=True)
    start_date: date
    end_date: date
    capacity_factor: float = 0.0  # 0..1
    note: str | None = Field(default=None, sa_column=Column(Text))
    removed: bool = False
