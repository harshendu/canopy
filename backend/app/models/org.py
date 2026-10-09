"""The org structure around initiatives: teams, the pods inside them, and team-level seats.

A **team** owns a product or a platform and holds several **pods**; pods take on focused
initiatives, and an initiative spans the pods of its projects (`Project.pod_id`). Above the pods
sit the team's **directors** and **managers** (`TeamMember`). Directors may plan anything in their
team's initiatives; managers, like pod leads, own the initiatives they are seated on
(`InitiativeLead`). See `app/services/access.py` and USER_FLOWS §R6.
"""

from sqlalchemy import Column, Text
from sqlmodel import Field

from app.models.base import TeamRole, TimestampMixin


class Team(TimestampMixin, table=True):
    id: int | None = Field(default=None, primary_key=True)
    key: str = Field(index=True, unique=True)
    name: str
    description: str | None = Field(default=None, sa_column=Column(Text))


class Pod(TimestampMixin, table=True):
    id: int | None = Field(default=None, primary_key=True)
    team_id: int = Field(foreign_key="team.id", index=True)
    name: str


class TeamMember(TimestampMixin, table=True):
    id: int | None = Field(default=None, primary_key=True)
    team_id: int = Field(foreign_key="team.id", index=True)
    engineer_id: int = Field(foreign_key="engineer.id", index=True)
    role: TeamRole = Field(default=TeamRole.manager)
