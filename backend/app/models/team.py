from datetime import date

from sqlalchemy import JSON, Column
from sqlmodel import Field

from app.models.base import TimestampMixin


class Role(TimestampMixin, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True)


class Engineer(TimestampMixin, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    email: str | None = Field(default=None, index=True)
    title: str | None = None
    role_id: int | None = Field(default=None, foreign_key="role.id")
    active: bool = True
    # Links this team member to a login (for the /me workspace + PR attribution).
    user_id: int | None = Field(default=None, foreign_key="app_user.id")
    skill_tags: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    github_login: str | None = None
    timezone: str | None = None
    committed_hours_per_week: float | None = None


class Allocation(TimestampMixin, table=True):
    """Capacity is modelled separately from assignment, like Advanced Roadmaps / MS Project."""

    id: int | None = Field(default=None, primary_key=True)
    engineer_id: int = Field(foreign_key="engineer.id", index=True)
    project_id: int | None = Field(default=None, foreign_key="project.id", index=True)
    task_id: int | None = Field(default=None, foreign_key="task.id", index=True)
    percent_allocation: float = 100.0
    capacity_hours_per_week: float = 40.0
    start_date: date | None = None
    end_date: date | None = None
