"""Request/response shapes for change proposals (the agent→human review queue)."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.base import ProposalAction, ProposalEntity, ProposalScope, ProposalStatus

_read = ConfigDict(from_attributes=True)


class ProposalItemIn(BaseModel):
    entity_type: ProposalEntity
    action: ProposalAction
    payload: dict[str, Any] = Field(default_factory=dict)
    entity_id: int | None = None  # required for update/resolve
    ref: str | None = None  # handle later items can point at (creates only)
    reason: str | None = None
    source_kind: str | None = None  # slack | email | calendar | meeting | jira | github | ...
    source_label: str | None = None
    source_url: str | None = None


class ProposalCreate(BaseModel):
    scope_level: ProposalScope
    scope_id: int
    title: str
    summary: str | None = None
    origin: str | None = None  # authoring surface, e.g. "claude-session (product persona)"
    items: list[ProposalItemIn] = Field(min_length=1)


class ProposalItemRead(BaseModel):
    model_config = _read
    id: int
    sort_order: int
    entity_type: ProposalEntity
    action: ProposalAction
    entity_id: int | None
    ref: str | None
    payload: dict[str, Any]
    before: dict[str, Any] | None
    reason: str | None
    source_kind: str | None
    source_label: str | None
    source_url: str | None
    excluded: bool
    applied_entity_id: int | None
    error: str | None


class ProposalItemDetail(ProposalItemRead):
    """Item plus the live values recomputed at read time — `stale` flags targets that
    moved since the before-snapshot was taken (or vanished entirely)."""

    current: dict[str, Any] | None = None
    stale: bool = False


class ProposalRead(BaseModel):
    model_config = _read
    id: int
    scope_level: ProposalScope
    scope_id: int
    title: str
    summary: str | None
    origin: str | None
    status: ProposalStatus
    created_by_user_id: int | None
    reviewed_by_user_id: int | None
    reviewed_at: datetime | None
    review_note: str | None
    applied_count: int
    created_at: datetime
    item_count: int = 0
    excluded_count: int = 0
    scope_label: str | None = None  # resolved project/initiative key+name for display


class ProposalDetail(ProposalRead):
    items: list[ProposalItemDetail] = Field(default_factory=list)


class ProposalItemPatch(BaseModel):
    excluded: bool


class ProposalRejectRequest(BaseModel):
    note: str | None = None


class ProposalApplyResult(BaseModel):
    proposal: ProposalRead
    applied: int
    skipped: int
    replanned_projects: list[int]
