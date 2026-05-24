"""Draft plans: a staging area for a proposed project plan the architect reviews before
any real work or Jira tickets exist.

Drafts are kept deliberately separate from live `Task`s so the Gantt/CPM/board never see
unreviewed work. Finalising a plan **creates Jira tickets** (content only — canopy never
owns ticket status); the next Jira sync then pulls those issues back as canopy `Task`s.
That keeps Jira the source of truth for tickets while letting the architect author and
review the plan here first.
"""

from datetime import datetime

from sqlmodel import Field

from app.models.base import TaskType, TimestampMixin

# DraftPlan lifecycle: a plan under review, one whose tickets have been pushed, or one
# the architect has set aside. Status is canopy-local (it is not a Jira status).
DRAFT_PLAN_STATUSES = ("draft", "synced", "archived")


class DraftPlan(TimestampMixin, table=True):
    """A reviewable, not-yet-committed plan for a project."""

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    title: str
    description: str | None = None
    status: str = "draft"  # draft | synced | archived
    source: str | None = None  # free-text note on where the plan came from (doc/PRD/url)
    synced_at: datetime | None = None  # when its tickets were last pushed to Jira


class DraftTask(TimestampMixin, table=True):
    """A proposed work item inside a DraftPlan. Mirrors a Task's planning shape but is freely
    editable during review and never scheduled. `jira_*` are set once the item is pushed."""

    id: int | None = Field(default=None, primary_key=True)
    plan_id: int = Field(foreign_key="draftplan.id", index=True)
    parent_id: int | None = Field(default=None, foreign_key="drafttask.id", index=True)
    name: str
    description: str | None = None
    type: TaskType = Field(default=TaskType.task)  # task | summary (epic/phase) | milestone
    estimate_days: int = 1  # canopy duration sense (working days)
    story_points: float | None = None  # pushed to the Jira story-point custom field
    sort_order: int = 0

    # Set after a successful push to Jira; their presence makes a re-push an update.
    jira_issue_id: str | None = None
    jira_key: str | None = None  # human key, e.g. "PROJ-123"
