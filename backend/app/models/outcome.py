from datetime import date

from sqlalchemy import Column, Text
from sqlmodel import Field

from app.models.base import OutcomeScope, OutcomeStatus, TimestampMixin


class Outcome(TimestampMixin, table=True):
    """An outcome a project/initiative is a *bet* toward — the hypothesis plus a measurable
    success metric, tracked baseline→target→current with a verdict.

    Outcomes over output: this is the *why*, and the thing a retro evaluates (did the bet pay
    off?). Scope is polymorphic (`scope_level` + `scope_id`, like the risk register / doc graph)
    so one table serves projects and initiatives; an entity can carry several (key results).
    The observed `current_value` is recorded by hand — canopy has no product-KPI pipeline — so
    it's an honest, manual signal (like the weekly health note). See `docs/AI_NATIVE_EXECUTION.md`.
    """

    id: int | None = Field(default=None, primary_key=True)
    scope_level: OutcomeScope = Field(index=True)
    scope_id: int = Field(index=True)  # project_id | initiative_id
    statement: str = Field(sa_column=Column(Text, nullable=False))  # "we believe X will yield Y"
    metric: str | None = Field(default=None, sa_column=Column(Text))  # how we'll know
    unit: str | None = None  # %, ms, $, count…
    baseline_value: float | None = None
    target_value: float | None = None
    current_value: float | None = None
    status: OutcomeStatus = Field(default=OutcomeStatus.pending)
    target_date: date | None = None
    owner_engineer_id: int | None = Field(default=None, foreign_key="engineer.id")
