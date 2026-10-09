from datetime import date, datetime

from sqlalchemy import JSON, Column, Text
from sqlmodel import Field

from app.models.base import (
    BlockerCategory,
    BlockerSeverity,
    DecisionRule,
    DependencyType,
    ProjectHealth,
    TaskType,
    TimestampMixin,
)


class Initiative(TimestampMixin, table=True):
    """A program/initiative spanning multiple projects — the architect's unit of work above
    a single Project. Sub-projects are how teams execute it concurrently and decentrally;
    the initiative carries the outcome and rolls up health across them."""

    id: int | None = Field(default=None, primary_key=True)
    key: str = Field(index=True, unique=True)  # short slug, e.g. "Q3-PLATFORM"
    name: str
    # the outcome + how we'll know it worked
    outcome_statement: str | None = Field(default=None, sa_column=Column(Text))
    start_date: date | None = None
    target_date: date | None = None
    owner_engineer_id: int | None = Field(default=None, foreign_key="engineer.id")
    # The team (product/platform group) this initiative belongs to; its directors may edit it.
    team_id: int | None = Field(default=None, foreign_key="team.id", index=True)
    archived: bool = False
    # Free-form labels (theme/workstream/etc.); see Engineer.skill_tags for the precedent.
    tags: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    # Architect's manual status; None = use the computed on-track signal.
    health: ProjectHealth | None = None
    # the weekly status headline
    status_note: str | None = Field(default=None, sa_column=Column(Text))
    status_updated_at: datetime | None = None


class Project(TimestampMixin, table=True):
    id: int | None = Field(default=None, primary_key=True)
    key: str = Field(index=True, unique=True)  # short slug, e.g. "PLATFORM"
    name: str
    description: str | None = Field(default=None, sa_column=Column(Text))
    initiative_id: int | None = Field(default=None, foreign_key="initiative.id", index=True)
    # The pod that runs this project (an initiative spans the pods of its projects), and the
    # project's single accountable owner, who may plan it (USER_FLOWS §R6).
    pod_id: int | None = Field(default=None, foreign_key="pod.id", index=True)
    owner_engineer_id: int | None = Field(default=None, foreign_key="engineer.id")
    start_date: date | None = None
    target_date: date | None = None
    archived: bool = False
    skip_weekends: bool = False  # schedule on a 5-day working week (+ holidays)
    # How an ADR reaches `accepted` once its stakeholders have weighed in, and how long
    # a freshly `proposed` ADR may sit before its owner must triage it.
    decision_rule: DecisionRule = Field(default=DecisionRule.owner_decides)
    decision_sla_hours: int = 72
    # Free-form labels (theme/workstream/etc.); see Engineer.skill_tags for the precedent.
    tags: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    # Architect's manual status; None = use the computed on-track signal.
    health: ProjectHealth | None = None
    # the weekly status headline
    status_note: str | None = Field(default=None, sa_column=Column(Text))
    status_updated_at: datetime | None = None


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
    description: str | None = Field(default=None, sa_column=Column(Text))
    target_date: date | None = None
    status: str = "planned"  # planned | at_risk | hit | missed


class Task(TimestampMixin, table=True):
    """The Gantt unit. A `summary` task acts as a phase/workstream (WBS via parent_id)."""

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    parent_id: int | None = Field(default=None, foreign_key="task.id", index=True)
    name: str
    description: str | None = Field(default=None, sa_column=Column(Text))
    type: TaskType = Field(default=TaskType.task)

    # CPM *output* (computed by the scheduler each replan) — do not treat as a constraint.
    start: date | None = None
    end: date | None = None
    duration: int = 1  # working/calendar days — the authoritative CPM scheduling input
    percent_complete: float = 0.0

    # CPM *input*: a user "start-no-earlier-than" (SNET) constraint, e.g. "can't begin before the
    # vendor delivers on Mar 1". Kept SEPARATE from the computed `start` so a replan doesn't reuse
    # last run's output as this run's pin (which made the schedule ratchet forward-only and left
    # what-if inert — removing a dependency or cutting a duration couldn't pull successors earlier).
    constraint_start: date | None = None

    # Free-form labels (area/workstream/risk-domain); see Engineer.skill_tags for the precedent.
    tags: list[str] = Field(default_factory=list, sa_column=Column(JSON))

    # Advisory 3-point (PERT) estimate, working days. Never auto-moves `duration`; the
    # optimistic↔pessimistic spread is surfaced as a schedule-risk uncertainty signal.
    estimate_optimistic: int | None = None  # aggressive
    estimate_likely: int | None = None  # practical / most-likely
    estimate_pessimistic: int | None = None  # buffered

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
    # The spec this task implements (intent → work traceability; spec-driven development).
    spec_id: int | None = Field(default=None, foreign_key="spec.id", index=True)


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


class RiskMitigation(TimestampMixin, table=True):
    """An acknowledgement of a risk indicator: a note, an owner, and a check-in date.
    The system follows up — an open mitigation past its check-in is itself a nudge."""

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    indicator_key: str  # which risk indicator this addresses (see services/risk.py)
    note: str = Field(sa_column=Column(Text, nullable=False))
    owner_engineer_id: int | None = Field(default=None, foreign_key="engineer.id")
    check_in: date | None = None
    resolved: bool = False


class RiskSnapshot(TimestampMixin, table=True):
    """A point-in-time capture of a project's risk score, for the risk timeline (§Q2).
    Captured on demand / nightly; the trend matters more than any single value."""

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    score: int
    level: str


class Baseline(TimestampMixin, table=True):
    """A logged re-baseline event: the moment the current schedule was snapshotted into
    each task's baseline_* as the new plan-of-record, plus the reason it was reset.

    The Gantt overlays current-vs-baseline as **schedule variance** — re-planning is a
    feature, not a failure, so resetting the baseline is a deliberate, reasoned act we keep
    a history of. (The word "drift" is reserved for *architecture* drift, §N.)"""

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    note: str | None = Field(default=None, sa_column=Column(Text))  # why the baseline was (re)set
    task_count: int = 0  # tasks snapshotted at this baseline
    project_end: date | None = None  # the planned end captured at baseline time


class Blocker(TimestampMixin, table=True):
    """A flagged impediment on a task — the leading signal that work has stalled. `created_at`
    is when it was opened; `resolved_at` is set when cleared (None = still open). Optionally
    points at the `blocking_task_id` that must finish first."""

    id: int | None = Field(default=None, primary_key=True)
    task_id: int = Field(foreign_key="task.id", index=True)
    reason: str = Field(sa_column=Column(Text, nullable=False))
    raised_by_engineer_id: int | None = Field(default=None, foreign_key="engineer.id")
    blocking_task_id: int | None = Field(default=None, foreign_key="task.id")
    resolved_at: datetime | None = None
    # PM enrichment: what kind of impediment, how bad, who owns clearing it, and by when.
    category: BlockerCategory | None = None
    severity: BlockerSeverity | None = None
    owner_engineer_id: int | None = Field(default=None, foreign_key="engineer.id")
    needed_by: date | None = None
