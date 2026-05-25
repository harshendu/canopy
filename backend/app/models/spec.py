from sqlalchemy import Column, Text
from sqlmodel import Field

from app.models.base import CriterionStatus, SpecStatus, TimestampMixin


class Spec(TimestampMixin, table=True):
    """A specification — *intent as the source of truth* for a slice of work.

    Spec-driven development: the architect/PM states the problem and explicit, checkable
    **acceptance criteria** before work begins; tasks implement it (`Task.spec_id`), and an
    agent self-audits each criterion against the implementation. Source docs (PRD / design)
    live in the document graph (§V) or link via `source_url`; the governing decision links via
    `adr_id`. This is the intent end of the spine in `docs/AI_NATIVE_EXECUTION.md`.
    """

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    title: str
    problem: str = Field(sa_column=Column(Text, nullable=False))  # the problem / intent
    context: str | None = Field(default=None, sa_column=Column(Text))
    out_of_scope: str | None = Field(default=None, sa_column=Column(Text))
    status: SpecStatus = Field(default=SpecStatus.draft, index=True)
    owner_engineer_id: int | None = Field(default=None, foreign_key="engineer.id")
    adr_id: int | None = Field(default=None, foreign_key="architecturedecision.id")
    source_url: str | None = Field(default=None, sa_column=Column(Text))  # PRD / design link


class SpecCriterion(TimestampMixin, table=True):
    """One acceptance criterion of a `Spec` — the checkable unit the agent self-audits."""

    id: int | None = Field(default=None, primary_key=True)
    spec_id: int = Field(foreign_key="spec.id", index=True)
    text: str = Field(sa_column=Column(Text, nullable=False))
    status: CriterionStatus = Field(default=CriterionStatus.open)
    verification: str | None = Field(default=None, sa_column=Column(Text))  # how it was checked
    sort_order: int = 0
