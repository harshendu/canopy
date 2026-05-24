from datetime import date, datetime

from sqlalchemy import Column, Text
from sqlmodel import Field

from app.models.base import (
    RiskCategory,
    RiskGrade,
    RiskScope,
    RiskStatus,
    TimestampMixin,
)


class RiskItem(TimestampMixin, table=True):
    """A human-tracked risk in the register (a RAID-style risk).

    Distinct from the *computed* risk concepts elsewhere in the codebase: `RiskSnapshot`
    and `RiskMitigation` (in models/project.py) belong to the automatic risk **score**
    in services/risk.py. A `RiskItem` is a qualitative risk an architect/PM records by
    hand — probability x impact, an owner, a mitigation plan and a contingency. It is
    kept **separate** from the computed score (it does not feed it); its exposure is
    computed from probability x impact at read time so it can never drift.

    Scope is polymorphic (`scope_level` + `scope_id`) so one register serves tasks,
    projects and initiatives — there is no FK, so routes validate the target exists.
    """

    id: int | None = Field(default=None, primary_key=True)
    scope_level: RiskScope = Field(index=True)
    scope_id: int = Field(index=True)  # task_id | project_id | initiative_id
    title: str
    description: str | None = Field(default=None, sa_column=Column(Text))
    category: RiskCategory = Field(default=RiskCategory.technical)
    probability: RiskGrade = Field(default=RiskGrade.medium)
    impact: RiskGrade = Field(default=RiskGrade.medium)
    status: RiskStatus = Field(default=RiskStatus.open)
    owner_engineer_id: int | None = Field(default=None, foreign_key="engineer.id")
    # the plan to lower probability before it occurs
    mitigation: str | None = Field(default=None, sa_column=Column(Text))
    # the plan if it occurs anyway
    contingency: str | None = Field(default=None, sa_column=Column(Text))
    target_resolution_date: date | None = None
    resolved_at: datetime | None = None  # stamped when status becomes terminal
