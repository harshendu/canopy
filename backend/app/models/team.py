from datetime import date

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
