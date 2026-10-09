"""Request/response shapes for initiative lead teams, ownership, and leadership notes."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.base import (
    LeadershipNoteKind,
    LeadershipNoteStatus,
    LeadershipScope,
    LeadershipTargetKind,
    LeadRole,
    ProjectHealth,
)

_read = ConfigDict(from_attributes=True)


# --- lead teams / ownership -----------------------------------------------------------------
class InitiativeLeadIn(BaseModel):
    engineer_id: int
    lead_role: LeadRole = LeadRole.technical


class InitiativeLeadRead(BaseModel):
    initiative_id: int
    engineer_id: int
    engineer_name: str
    lead_role: LeadRole
    user_id: int | None = None


class InitiativeAccess(BaseModel):
    """What the current user may edit, plus every initiative's lead team (one call)."""

    led_initiative_ids: list[int]
    leads: list[InitiativeLeadRead]


class ProjectAccess(BaseModel):
    """Ownership context for one project: editable by the current user, and who leads it."""

    project_id: int
    initiative_id: int | None
    initiative_name: str | None
    can_edit: bool
    leads: list[InitiativeLeadRead] = []


# --- leadership notes ------------------------------------------------------------------------
class LeadershipNoteCreate(BaseModel):
    scope_level: LeadershipScope
    scope_id: int
    kind: LeadershipNoteKind = LeadershipNoteKind.feedback
    priority: int | None = Field(default=None, ge=1, le=3)
    body: str = Field(min_length=1)
    target_kind: LeadershipTargetKind | None = None
    target_id: int | None = None


class LeadershipNoteUpdate(BaseModel):
    status: LeadershipNoteStatus | None = None
    response: str | None = None
    body: str | None = None
    priority: int | None = Field(default=None, ge=1, le=3)


class LeadershipNoteRead(BaseModel):
    model_config = _read
    id: int
    scope_level: LeadershipScope
    scope_id: int
    target_kind: LeadershipTargetKind | None
    target_id: int | None
    target_label: str | None
    kind: LeadershipNoteKind
    priority: int | None
    body: str
    author_user_id: int
    author_name: str | None = None
    status: LeadershipNoteStatus
    response: str | None
    responded_by_user_id: int | None
    responded_by_name: str | None = None
    responded_at: datetime | None
    created_at: datetime


# --- business review (MBR) -------------------------------------------------------------------
class ReviewOutcome(BaseModel):
    id: int
    statement: str
    status: str
    current_value: float | None
    target_value: float | None
    unit: str | None


class ReviewInitiative(BaseModel):
    id: int
    key: str
    name: str
    outcome_statement: str | None
    target_date: date | None
    health: ProjectHealth | None
    status_note: str | None
    leads: list[InitiativeLeadRead]
    project_count: int
    avg_percent_complete: float
    project_end: date | None
    on_track: bool | None
    risk_score: int
    risk_level: str
    drift_score: int
    drift_level: str
    open_decisions: int
    open_blockers: int
    outcomes: list[ReviewOutcome]
    open_notes: list[LeadershipNoteRead]


class BusinessReview(BaseModel):
    """The monthly-business-review roll-up: every initiative, its lead team, headline health,
    outcomes, and the leadership notes still open — one page for the executive meeting."""

    generated_on: date
    initiatives: list[ReviewInitiative]
    open_note_count: int
    attention: list[str]
