"""API shapes for design docs (USER_FLOWS §V5-§V8): register, link, promote, the kind catalog."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.base import (
    DocLinkEntity,
    DocRelation,
    DocScope,
    DocStage,
    DocVisibility,
)
from app.schemas.entities import DocReferenceRead
from app.services.doc_kinds import FORMAT_MAX, normalize_slug

_read = ConfigDict(from_attributes=True)


class DocLinkSpecIn(BaseModel):
    entity_type: DocLinkEntity
    entity_id: int
    relation: DocRelation = DocRelation.reference


class DocRegisterIn(BaseModel):
    """What a session (or a person) sends to track a document. Never the content."""

    url: str = Field(min_length=8, max_length=4000)
    title: str | None = Field(default=None, max_length=500)
    kind: str | None = Field(default=None, max_length=120)  # any kind; normalized to a slug
    format: str | None = Field(default=None, max_length=60)  # document | page | prototype | …
    summary: str | None = Field(default=None, max_length=2000)  # a short abstract, plain text
    version: str | None = Field(default=None, max_length=64)  # the source's version label
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
    visibility: DocVisibility = DocVisibility.unknown
    personal: bool = False  # track it for yourself only; no sharing needed
    scope_level: DocScope | None = None  # the doc's home (required unless personal)
    scope_id: int | None = None
    owner_engineer_id: int | None = None
    track: bool = True  # start the review lifecycle at `draft` (false = a plain link)
    supersedes_id: int | None = None
    links: list[DocLinkSpecIn] = Field(default_factory=list, max_length=50)

    @field_validator("kind")
    @classmethod
    def _kind(cls, value: str | None) -> str | None:
        return None if value is None else normalize_slug(value)

    @field_validator("format")
    @classmethod
    def _format(cls, value: str | None) -> str | None:
        return None if value is None else normalize_slug(value, max_length=FORMAT_MAX)


class DocLinkIn(BaseModel):
    entity_type: DocLinkEntity
    entity_id: int
    relation: DocRelation = DocRelation.reference
    pinned_version: str | None = Field(default=None, max_length=64)


class DocLinkUpdateIn(BaseModel):
    relation: DocRelation | None = None
    pinned_version: str | None = Field(default=None, max_length=64)


class DocLinkRead(BaseModel):
    model_config = _read
    id: int
    doc_id: int
    entity_type: str
    entity_id: int
    relation: str
    pinned_version: str | None
    pinned_at: datetime | None
    created_by_user_id: int | None
    created_at: datetime
    label: str | None = None  # the target's display name


class DocHealthFlagRead(BaseModel):
    """One reason a doc needs a look (computed, never stored — USER_FLOWS §V8)."""

    flag: str  # unverified | check_due | changed_since_approval | behind_pin | gate_open |
    #            restricted | broken
    severity: str  # info | warning | error
    message: str
    entity_type: str | None = None
    entity_id: int | None = None


class DocRevisionRead(BaseModel):
    model_config = _read
    id: int
    doc_id: int
    version: str
    content_hash: str | None
    change_summary: str | None
    snapshot_url: str | None
    recorded_by_user_id: int | None
    source: str
    created_at: datetime


class DesignDocRead(DocReferenceRead):
    """A doc with what the views need around it: its catalog entry, its links and its health."""

    kind_label: str
    stage: str
    personal: bool
    links: list[DocLinkRead] = Field(default_factory=list)
    health: list[DocHealthFlagRead] = Field(default_factory=list)


class DesignDocDetail(DesignDocRead):
    """One doc with its version log, newest first."""

    revisions: list[DocRevisionRead] = Field(default_factory=list)


class DocRevisionIn(BaseModel):
    """What a check saw. `reachable=false` records a failed open (the link health turns
    `broken`); a version label is appended to the log when it is new."""

    version: str | None = Field(default=None, max_length=64)
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
    change_summary: str | None = Field(default=None, max_length=2000)
    reachable: bool = True
    visibility: DocVisibility | None = None
    snapshot_url: str | None = Field(default=None, max_length=4000)


class DocRevisionOut(BaseModel):
    doc: DesignDocRead
    new_version: bool
    revision: DocRevisionRead | None = None


class DocReviewIn(BaseModel):
    version: str | None = Field(default=None, max_length=64)


class DocWorklistRead(BaseModel):
    """Docs a session should open and re-check (the sentinel's worklist)."""

    total: int
    docs: list[DesignDocRead]


class DocRegisterOut(BaseModel):
    doc: DesignDocRead
    created: bool  # false = the document was already tracked; you got its record


class EntityDocRead(BaseModel):
    """A doc linked to one entity, with that link (relation + pinned version)."""

    link: DocLinkRead
    doc: DesignDocRead


class DocPromoteIn(BaseModel):
    scope_level: DocScope
    scope_id: int
    visibility: DocVisibility | None = None  # report the new sharing level in the same call


class DocKindRead(BaseModel):
    key: str
    label: str
    stage: str
    expected: bool
    builtin: bool
    sort_order: int
    doc_count: int = 0


class DocKindUpdateIn(BaseModel):
    label: str | None = Field(default=None, max_length=120)
    stage: DocStage | None = None
    expected: bool | None = None
    sort_order: int | None = None


class DocKindMergeIn(BaseModel):
    into: str = Field(min_length=1, max_length=120)


class DocKindMergeOut(BaseModel):
    merged: int
    into: str
