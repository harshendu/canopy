from datetime import date

from sqlalchemy import JSON, Column, Text
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
    # Jira account id of this person, so synced issue assignees map onto the same Engineer
    # (matched by id first, then by exact unclaimed display name, else auto-created on sync).
    # Unique so two Engineers can never claim one Jira account (NULLs are exempt).
    jira_account_id: str | None = Field(default=None, index=True, unique=True)
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


class EngineerAvailability(TimestampMixin, table=True):
    """A date range during which an engineer is partially/fully unavailable (PTO, leave,
    ramp-up). `capacity_factor` is the FRACTION of normal capacity available in the range:
    0.0 = fully out, 0.5 = half. It scales the over-allocation ceiling in the capacity
    views (a week's allocation demand is "over" when it exceeds 100% * factor)."""

    id: int | None = Field(default=None, primary_key=True)
    engineer_id: int = Field(foreign_key="engineer.id", index=True)
    start_date: date = Field(index=True)
    end_date: date
    capacity_factor: float = 0.0  # 0..1
    note: str | None = Field(default=None, sa_column=Column(Text))
