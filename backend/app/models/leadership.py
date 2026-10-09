"""Initiative lead teams + leadership notes.

* `InitiativeLead` — a seat on an initiative's **core team**: the technical / product / design
  leads who jointly own it. Ownership scopes *planning writes*: a planner-role user edits the
  initiatives they lead and reads every other one (`app/services/access.py`). An initiative with
  no leads keeps the plain role-based rules (back-compat for installs that never set leads).
* `LeadershipNote` — feedback from the executive layer on a specific view: something to
  **watch**, a **priority** call, or free-form **feedback**, optionally pinned to a decision /
  risk / outcome / milestone inside the scope. Leads acknowledge / resolve with a response, so
  the loop closes where the work is — and the business-review page rolls the open ones up.
"""

from datetime import datetime

from sqlalchemy import Column, Text
from sqlmodel import Field

from app.models.base import (
    LeadershipNoteKind,
    LeadershipNoteStatus,
    LeadershipScope,
    LeadershipTargetKind,
    LeadRole,
    TimestampMixin,
)


class InitiativeLead(TimestampMixin, table=True):
    id: int | None = Field(default=None, primary_key=True)
    initiative_id: int = Field(foreign_key="initiative.id", index=True)
    engineer_id: int = Field(foreign_key="engineer.id", index=True)
    lead_role: LeadRole = Field(default=LeadRole.technical)


class LeadershipNote(TimestampMixin, table=True):
    id: int | None = Field(default=None, primary_key=True)
    scope_level: LeadershipScope = Field(index=True)
    scope_id: int = Field(index=True)  # initiative_id | project_id
    # Optional finer target inside the scope (a decision, risk, outcome or milestone). The label
    # is captured at write time so the note still reads if the target is renamed or removed.
    target_kind: LeadershipTargetKind | None = None
    target_id: int | None = None
    target_label: str | None = None
    kind: LeadershipNoteKind = Field(default=LeadershipNoteKind.feedback)
    priority: int | None = None  # 1 (highest) .. 3, only meaningful for kind=priority
    body: str = Field(sa_column=Column(Text, nullable=False))
    author_user_id: int = Field(foreign_key="app_user.id", index=True)
    status: LeadershipNoteStatus = Field(default=LeadershipNoteStatus.open, index=True)
    response: str | None = Field(default=None, sa_column=Column(Text))
    responded_by_user_id: int | None = Field(default=None, foreign_key="app_user.id")
    responded_at: datetime | None = None
