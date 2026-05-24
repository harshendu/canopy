from sqlalchemy import JSON, Column, Text
from sqlmodel import Field

from app.models.base import RetrospectiveKind, TimestampMixin


class Retrospective(TimestampMixin, table=True):
    """A project retrospective or an incident postmortem. The body is seeded from project
    state for retros (see app/services/retro.py) and edited; both gather a comment thread
    and can mint follow-up tasks / propose ADRs."""

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    kind: RetrospectiveKind = Field(default=RetrospectiveKind.project_retro)
    title: str
    body: str | None = Field(default=None, sa_column=Column(Text))  # markdown
    status: str = "open"  # open | closed
    affected_component_ids: list[int] = Field(default_factory=list, sa_column=Column(JSON))


class RetrospectiveComment(TimestampMixin, table=True):
    id: int | None = Field(default=None, primary_key=True)
    retrospective_id: int = Field(foreign_key="retrospective.id", index=True)
    engineer_id: int | None = Field(default=None, foreign_key="engineer.id")
    author_name: str | None = None
    body: str = Field(sa_column=Column(Text, nullable=False))
