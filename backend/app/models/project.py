from datetime import date, datetime

from sqlmodel import Field

from app.models.base import DecisionRule, DependencyType, TaskType, TimestampMixin


class Project(TimestampMixin, table=True):
    id: int | None = Field(default=None, primary_key=True)
    key: str = Field(index=True, unique=True)  # short slug, e.g. "PLATFORM"
    name: str
    description: str | None = None
    start_date: date | None = None
    target_date: date | None = None
    archived: bool = False
    skip_weekends: bool = False  # schedule on a 5-day working week (+ holidays)
    # How an ADR reaches `accepted` once its stakeholders have weighed in, and how long
    # a freshly `proposed` ADR may sit before its owner must triage it.
    decision_rule: DecisionRule = Field(default=DecisionRule.owner_decides)
    decision_sla_hours: int = 72


class Holiday(TimestampMixin, table=True):
    """A non-working day for a project's scheduling calendar."""

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    day: date = Field(index=True)
    name: str | None = None


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
    # Active Jira sprint name (from the Agile API), when applicable.
    sprint: str | None = None
    # Hard deadline; the scheduler flags tasks whose computed end exceeds it.
    deadline: date | None = None
    assignee_engineer_id: int | None = Field(default=None, foreign_key="engineer.id")


class TaskStatusHistory(TimestampMixin, table=True):
    """Status transitions mirrored from the Jira issue changelog."""

    id: int | None = Field(default=None, primary_key=True)
    task_id: int = Field(foreign_key="task.id", index=True)
    from_status: str | None = None
    to_status: str | None = None
    changed_at: datetime = Field(index=True)
    author: str | None = None


class Dependency(TimestampMixin, table=True):
    id: int | None = Field(default=None, primary_key=True)
    predecessor_id: int = Field(foreign_key="task.id", index=True)
    successor_id: int = Field(foreign_key="task.id", index=True)
    type: DependencyType = Field(default=DependencyType.FS)
    lag: int = 0  # days
