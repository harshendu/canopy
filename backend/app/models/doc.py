from datetime import datetime

from sqlalchemy import Column, Text
from sqlmodel import Field

from app.models.base import (
    DocKind,
    DocLinkHealth,
    DocScope,
    DocSource,
    TimestampMixin,
)


class DocReference(TimestampMixin, table=True):
    """A typed *link* to a document that lives elsewhere — a Jira epic, Google Drive,
    Figma, Confluence, or a repo file.

    Canopy is a document **graph**, not a document store: a DocReference points at the
    canonical location and never copies the bytes. Scope is polymorphic
    (`scope_level` + `scope_id`, mirroring `RiskItem`) so one table serves projects,
    initiatives, and tasks (an epic mapped as a summary task). Harvested references are
    deduplicated per (scope, url) in the service layer — there is no DB unique constraint
    on `url` because a UNIQUE index over a TEXT column is not portable to MySQL.
    """

    id: int | None = Field(default=None, primary_key=True)
    scope_level: DocScope = Field(index=True)
    scope_id: int = Field(index=True)  # project_id | initiative_id | task_id
    kind: DocKind = Field(default=DocKind.other, index=True)
    title: str | None = None
    url: str = Field(sa_column=Column(Text, nullable=False))
    source: DocSource = Field(default=DocSource.manual)
    owner_engineer_id: int | None = Field(default=None, foreign_key="engineer.id")
    # provenance of a harvested link
    connection_id: int | None = Field(default=None, foreign_key="connection.id")
    external_field: str | None = None  # the Jira field id it came from (e.g. customfield_10042)
    # link-health (the missing/stale signal); checking is a follow-up, default unchecked
    link_health: DocLinkHealth = Field(default=DocLinkHealth.unchecked)
    last_checked_at: datetime | None = None
