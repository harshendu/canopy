"""Board workflows: the ordered status columns a team (or a team-less project) works through,
with a category per column and optional WIP limits (USER_FLOWS §C9).

Resolution order for a project's board (`app/services/workflow.py:resolve_workflow`): the
project's own override → its team's workflow → the workspace template (`team_id` and
`project_id` both null) → the built-in default. A missing row is never written on read, so
the template and the default apply live until someone edits a workflow.
"""

from sqlalchemy import UniqueConstraint
from sqlmodel import Field

from app.models.base import StatusCategory, TimestampMixin, WipEnforcement


class Workflow(TimestampMixin, table=True):
    id: int | None = Field(default=None, primary_key=True)
    # At most one of these is set; both null = the workspace template.
    team_id: int | None = Field(default=None, foreign_key="team.id", index=True)
    project_id: int | None = Field(default=None, foreign_key="project.id", index=True)
    name: str
    wip_enforcement: str = WipEnforcement.warn.value


class WorkflowStatus(TimestampMixin, table=True):
    """One board column: a status name, what it means, where it sits, and its WIP limit."""

    __table_args__ = (UniqueConstraint("workflow_id", "name", name="uq_workflowstatus_name"),)

    id: int | None = Field(default=None, primary_key=True)
    workflow_id: int = Field(foreign_key="workflow.id", index=True)
    name: str
    category: str = StatusCategory.todo.value
    position: int = 0
    wip_limit: int | None = None
