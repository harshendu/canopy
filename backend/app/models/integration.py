from datetime import datetime

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field

from app.models.base import Provider, TimestampMixin


class Connection(TimestampMixin, table=True):
    """A configured connector instance (per provider). Tokens are encrypted at rest."""

    id: int | None = Field(default=None, primary_key=True)
    provider: Provider = Field(index=True)
    name: str
    encrypted_token: str | None = None  # Fernet-encrypted access token / API token
    encrypted_refresh_token: str | None = None
    # Provider-specific config: base_url, cloud_id, repo, scopes, etc.
    config: dict = Field(default_factory=dict, sa_column=Column(JSON))
    watermark: str | None = None  # last successful incremental-sync cursor/timestamp
    active: bool = True


class ExternalRef(TimestampMixin, table=True):
    """Maps an external object (Jira issue, GitHub PR, Drive file) to a canopy entity.

    Upsert on (provider, external_id, entity_type) makes inbound sync idempotent.
    """

    __table_args__ = (
        UniqueConstraint("provider", "external_id", "entity_type", name="uq_external_ref"),
    )

    id: int | None = Field(default=None, primary_key=True)
    provider: Provider = Field(index=True)
    external_id: str = Field(index=True)  # Jira issue id, GH node id, Drive file id
    external_key: str | None = None  # human key, e.g. "PROJ-123"
    entity_type: str  # task | milestone | component | adr | project
    entity_id: int
    remote_updated: str | None = None  # upstream `updated` watermark for staleness checks
    last_synced_at: datetime | None = None
