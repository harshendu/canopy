"""Sprints: a team's time boxes (USER_FLOWS §C11).

A sprint belongs to a team (optionally one pod of it) and spans every project the team runs.
It is canopy-owned (planned and run here) or mirrored from a tracker's sprints/cycles (`owner`
is then the provider key, and its name/dates/state are read-only). `TaskSprintHistory` records
every change of a task's sprint membership — commitment, scope change and carry-over are
computed from it.
"""

from datetime import date, datetime

from sqlalchemy import Column, Text
from sqlmodel import Field

from app.models.base import CANOPY_OWNER, SprintState, StatusSource, TimestampMixin


class Sprint(TimestampMixin, table=True):
    id: int | None = Field(default=None, primary_key=True)
    team_id: int = Field(foreign_key="team.id", index=True)
    pod_id: int | None = Field(default=None, foreign_key="pod.id", index=True)
    name: str
    goal: str | None = Field(default=None, sa_column=Column(Text))
    # Nullable only for a mirrored sprint whose tracker has not sent dates yet.
    start_date: date | None = None
    end_date: date | None = None
    state: str = SprintState.planned.value
    owner: str = CANOPY_OWNER
    # Captured at start / completion, in the team's estimate unit (`estimate_unit` records it).
    estimate_unit: str | None = None
    committed: float | None = None
    completed: float | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class TaskSprintHistory(TimestampMixin, table=True):
    """One change of a task's sprint membership (into, out of, or between sprints)."""

    id: int | None = Field(default=None, primary_key=True)
    task_id: int = Field(foreign_key="task.id", index=True)
    from_sprint_id: int | None = Field(default=None, foreign_key="sprint.id")
    to_sprint_id: int | None = Field(default=None, foreign_key="sprint.id")
    changed_at: datetime = Field(index=True)
    author: str | None = None
    source: str = StatusSource.canopy.value
