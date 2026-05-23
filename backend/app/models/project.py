from datetime import date

from sqlmodel import Field

from app.models.base import DependencyType, TaskType, TimestampMixin


class Project(TimestampMixin, table=True):
    id: int | None = Field(default=None, primary_key=True)
    key: str = Field(index=True, unique=True)  # short slug, e.g. "PLATFORM"
    name: str
    description: str | None = None
    start_date: date | None = None
    target_date: date | None = None
    archived: bool = False


class Milestone(TimestampMixin, table=True):
    """A named, architect-defined milestone (zero-duration marker on the timeline)."""

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    name: str
    description: str | None = None
    target_date: date | None = None
    status: str = "planned"  # planned | at_risk | hit | missed


class Task(TimestampMixin, table=True):
    """The Gantt unit. A `summary` task acts as a phase/workstream (WBS via parent_id)."""

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    parent_id: int | None = Field(default=None, foreign_key="task.id", index=True)
    name: str
    description: str | None = None
    type: TaskType = Field(default=TaskType.task)

    start: date | None = None
    end: date | None = None
    duration: int = 1  # working/calendar days
    percent_complete: float = 0.0

    # Baseline (set when a plan is committed) — drives drift visualisation.
    baseline_start: date | None = None
    baseline_end: date | None = None

    # Computed by the CPM scheduler.
    is_critical: bool = False
    total_float: int = 0

    # Mirror of the upstream (Jira) status; canopy never writes this back.
    status: str | None = None
    assignee_engineer_id: int | None = Field(default=None, foreign_key="engineer.id")


class Dependency(TimestampMixin, table=True):
    id: int | None = Field(default=None, primary_key=True)
    predecessor_id: int = Field(foreign_key="task.id", index=True)
    successor_id: int = Field(foreign_key="task.id", index=True)
    type: DependencyType = Field(default=DependencyType.FS)
    lag: int = 0  # days
