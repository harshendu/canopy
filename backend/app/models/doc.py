from datetime import datetime

from sqlalchemy import Column, Text, UniqueConstraint
from sqlmodel import Field

from app.models.base import (
    DocFormat,
    DocLinkHealth,
    DocProvider,
    DocRelation,
    DocScope,
    DocSource,
    DocStage,
    DocVisibility,
    TimestampMixin,
)


class DocReference(TimestampMixin, table=True):
    """A typed *link* to a document that lives elsewhere — a Claude Doc or artifact, a Jira
    epic, Google Drive, Figma, Confluence, or a repo file.

    Canopy is a document **graph**, not a document store: a DocReference points at the
    canonical location and never copies the bytes. One row is one *document*: it is
    registered once (deduplicated on `provider` + `external_id`, or the normalized URL) and
    linked to every entity it serves through `DocLink`. The polymorphic scope
    (`scope_level` + `scope_id`, mirroring `RiskItem`) is the doc's **home** — where it
    appears in a cockpit and whose planning rights govern it; a personal doc may have none.
    There is no DB unique constraint on `url` because a UNIQUE index over a TEXT column is not
    portable to MySQL.

    A row is **personal** when `private_to_user_id` is set: only that person sees it. Shared
    Claude docs must be shared in Claude (`visibility` users | org | public) — the sharing
    rule in `app/services/design_docs.py`. `review_status` NULL means an untracked plain link
    (every pre-design-doc row); otherwise the doc runs the review lifecycle.
    """

    id: int | None = Field(default=None, primary_key=True)
    # Home scope. NULL only for a personal doc that is not filed under a project/initiative.
    scope_level: DocScope | None = Field(default=None, index=True)
    scope_id: int | None = Field(default=None, index=True)  # project_id | initiative_id | task_id
    # An open slug backed by the kind catalog (`DocKindDef`) — any kind is allowed.
    kind: str = Field(default="other", max_length=48, index=True)
    title: str | None = None
    url: str = Field(sa_column=Column(Text, nullable=False))
    source: str = Field(default=DocSource.manual.value, max_length=32)
    owner_engineer_id: int | None = Field(default=None, foreign_key="engineer.id")
    # provenance of a harvested link
    connection_id: int | None = Field(default=None, foreign_key="connection.id")
    external_field: str | None = None  # the Jira field id it came from (e.g. customfield_10042)
    # the result of the last check (a session opened it, or the org sync saw it)
    link_health: DocLinkHealth = Field(default=DocLinkHealth.unchecked)
    last_checked_at: datetime | None = None

    # --- identity + medium ---
    provider: str = Field(default=DocProvider.web.value, max_length=32, index=True)
    # The provider's id for the document (a claude.ai artifact id, a Drive file id, …), parsed
    # from the URL. Registration dedupes on provider + external_id.
    external_id: str | None = Field(default=None, max_length=128, index=True)
    format: str = Field(default=DocFormat.other.value, max_length=32)  # open slug

    # --- personal vs shared ---
    private_to_user_id: int | None = Field(default=None, foreign_key="app_user.id", index=True)
    visibility: str = Field(default=DocVisibility.unknown.value, max_length=16)

    # --- review lifecycle + versions ---
    review_status: str | None = Field(default=None, max_length=32, index=True)
    review_version: str | None = Field(default=None, max_length=64)  # the version under review
    current_version: str | None = Field(default=None, max_length=64)
    approved_version: str | None = Field(default=None, max_length=64)
    approved_by_user_id: int | None = Field(default=None, foreign_key="app_user.id")
    approved_at: datetime | None = None

    summary: str | None = Field(default=None, sa_column=Column(Text))  # short agent abstract
    supersedes_id: int | None = Field(default=None, foreign_key="docreference.id")
    created_by_user_id: int | None = Field(default=None, foreign_key="app_user.id")


class DocLink(TimestampMixin, table=True):
    """A link from one design doc to a canopy entity it serves (many-to-many).

    `relation` says what the link means: **basis** (the entity was derived from or decided
    on the doc — pins `pinned_version`, and a newer version raises an alert), **gate** (the
    entity should not complete until the doc is approved — advisory), **reference** (context).
    `entity_type` + `entity_id` are polymorphic (no FK), validated in the service and cleaned
    up by `app/services/cascade.py`.
    """

    __table_args__ = (
        UniqueConstraint("doc_id", "entity_type", "entity_id", name="uq_doclink_target"),
    )

    id: int | None = Field(default=None, primary_key=True)
    doc_id: int = Field(foreign_key="docreference.id", index=True)
    entity_type: str = Field(max_length=32, index=True)
    entity_id: int = Field(index=True)
    relation: str = Field(default=DocRelation.reference.value, max_length=16)
    pinned_version: str | None = Field(default=None, max_length=64)
    pinned_at: datetime | None = None
    created_by_user_id: int | None = Field(default=None, foreign_key="app_user.id")


class DocRevision(TimestampMixin, table=True):
    """An observed version of a design doc — the append-only version log.

    A session (or the org sync) records each version it sees with an optional SHA-256 of the
    exported content (computed outside the backend — canopy never receives the content) and a
    one-line change summary. `snapshot_url` points at a frozen copy (a repo file or a Drive
    file) when the version was frozen at a decision.
    """

    __table_args__ = (UniqueConstraint("doc_id", "version", name="uq_docrevision_version"),)

    id: int | None = Field(default=None, primary_key=True)
    doc_id: int = Field(foreign_key="docreference.id", index=True)
    version: str = Field(max_length=64)
    content_hash: str | None = Field(default=None, max_length=64)
    change_summary: str | None = Field(default=None, sa_column=Column(Text))
    snapshot_url: str | None = Field(default=None, sa_column=Column(Text))
    recorded_by_user_id: int | None = Field(default=None, foreign_key="app_user.id")
    source: str = Field(default="session", max_length=16)  # session | ui | register | sync


class DocKindDef(TimestampMixin, table=True):
    """One entry of the workspace's document-kind catalog.

    Kinds are data, not schema: an unknown kind is added on first use under stage `other`,
    and a planner sets its label and stage. `expected` kinds are the ones whose absence the
    coverage report flags. `builtin` rows are the seeded starting set (they can be relabelled
    and re-staged but not deleted).
    """

    id: int | None = Field(default=None, primary_key=True)
    key: str = Field(max_length=48, unique=True, index=True)
    label: str
    stage: str = Field(default=DocStage.other.value, max_length=16)
    expected: bool = False
    builtin: bool = False
    sort_order: int = 0
