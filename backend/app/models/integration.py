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
    token_expires_at: datetime | None = None  # for OAuth refresh timing
    # Provider-specific config: base_url, cloud_id, repo, scopes, auth_type, etc.
    config: dict = Field(default_factory=dict, sa_column=Column(JSON))
    watermark: str | None = None  # last successful incremental-sync cursor/timestamp
    active: bool = True

    @property
    def authorized(self) -> bool:
        """True once a token (API token or OAuth access token) has been stored."""
        return self.encrypted_token is not None


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


class JiraLink(TimestampMixin, table=True):
    """An architect-created link from a Jira ticket (the *root*) into a canopy target —
    either a Project or an Initiative.

    Syncing a link pulls the root ticket plus its full descendant subtree from Jira and
    maps it onto canopy entities idempotently (via ExternalRef):
      - target_type="project":    every issue in the subtree becomes a Task in that project
        (epics → summary tasks, everything else → leaf tasks), parented within the project.
      - target_type="initiative": each epic in the subtree becomes a Project under the
        initiative and its stories become tasks in that project (Jira initiative→epic→story
        mirrored onto canopy initiative→project→task).

    Status stays Jira-owned and is never written back (same boundary as the rest of sync).
    """

    __table_args__ = (UniqueConstraint("connection_id", "jira_issue_id", name="uq_jira_link"),)

    id: int | None = Field(default=None, primary_key=True)
    connection_id: int = Field(foreign_key="connection.id", index=True)
    jira_issue_id: str = Field(index=True)  # Jira numeric issue id (opaque)
    jira_key: str  # human key, e.g. "PROJ-123"
    jira_issue_type: str | None = None  # issue-type name at link time (Epic/Story/Initiative…)
    target_type: str = Field(index=True)  # "project" | "initiative"
    target_id: int = Field(index=True)  # Project.id or Initiative.id (polymorphic, no FK)
    last_synced_at: datetime | None = None


class PullRequest(TimestampMixin, table=True):
    """Lightweight cache of GitHub pull requests, kept fresh by webhooks."""

    __table_args__ = (UniqueConstraint("repo", "number", name="uq_pull_request"),)

    id: int | None = Field(default=None, primary_key=True)
    repo: str = Field(index=True)  # "owner/name"
    number: int
    title: str
    state: str  # open | closed
    url: str | None = None
    author: str | None = None
    remote_updated: str | None = None
