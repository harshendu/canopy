from datetime import datetime

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field

from app.models.base import Provider, ProviderType, ReadStrategy, TimestampMixin, WriteStrategy


class IntegrationSetting(TimestampMixin, table=True):
    """Admin-chosen integration policy for one provider: how reads and writes flow.

    One row per provider. The **absence** of a row means the default — direct reads + direct
    writes (canopy uses its own credentials) — which preserves the pre-policy behavior so
    existing installs are unaffected until an admin opts in.
    """

    __table_args__ = (
        UniqueConstraint("provider", name="uq_integration_setting_provider"),
    )

    id: int | None = Field(default=None, primary_key=True)
    provider: Provider = Field(sa_type=ProviderType, index=True)
    read_strategy: ReadStrategy = Field(default=ReadStrategy.direct)
    write_strategy: WriteStrategy = Field(default=WriteStrategy.direct)
    # Phase-2 hook: whether non-admin users may connect their own (per-user OAuth) account.
    allow_user_connect: bool = False


class Connection(TimestampMixin, table=True):
    """A configured connector instance (per provider): a site and a credential. Which canopy
    project/initiative it feeds, and from where in the tracker, is a `TrackerBinding` (many per
    connection). Tokens are encrypted at rest."""

    id: int | None = Field(default=None, primary_key=True)
    provider: Provider = Field(sa_type=ProviderType, index=True)
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


class UserConnection(TimestampMixin, table=True):
    """A user's personal OAuth credential attached to a shared `Connection` (the integration
    definition). canopy acts **as the user** with this token; the target config (Jira site/
    project, repo, Drive) comes from the parent `Connection`. Each user has at most one
    credential per connection, with **its own watermark** so a narrow-access pull can't disturb
    the service connection's incremental cursor or remove what the service token populated.
    """

    __table_args__ = (
        UniqueConstraint("connection_id", "user_id", name="uq_user_connection"),
    )

    id: int | None = Field(default=None, primary_key=True)
    connection_id: int = Field(foreign_key="connection.id", index=True)
    user_id: int = Field(foreign_key="app_user.id", index=True)
    encrypted_token: str | None = None
    encrypted_refresh_token: str | None = None
    token_expires_at: datetime | None = None
    watermark: str | None = None
    active: bool = True

    @property
    def authorized(self) -> bool:
        return self.encrypted_token is not None


class ExternalRef(TimestampMixin, table=True):
    """Maps an external object (Jira issue, GitHub PR, Drive file) to a canopy entity.

    Upsert on (provider, external_id, entity_type) makes inbound sync idempotent.
    """

    __table_args__ = (
        UniqueConstraint(
            "provider", "external_id", "entity_type", "connection_id", name="uq_external_ref"
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    provider: Provider = Field(sa_type=ProviderType, index=True)
    external_id: str = Field(index=True)  # Jira issue id, GH node id, Drive file id
    external_key: str | None = None  # human key, e.g. "PROJ-123"
    entity_type: str  # task | milestone | component | adr | project | sprint
    entity_id: int
    remote_updated: str | None = None  # upstream `updated` watermark for staleness checks
    last_synced_at: datetime | None = None
    # Which site the external id belongs to (two sites of one provider can share numeric ids).
    # NULL on legacy rows whose connection couldn't be derived — matched by `mapping.get_ref`.
    connection_id: int | None = Field(default=None, foreign_key="connection.id")
    # Set when the project stopped mirroring this tracker (a switch): the link is kept so the
    # task still shows "formerly SHOP-101", and re-attaching re-activates it.
    detached_at: datetime | None = None


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
    # The task this PR implements, when known (matched on ingest by the issue key in its title
    # or branch — any tracker's key, or a native canopy key). Lets the UI surface a task's code
    # changes alongside its tracker item and design docs.
    task_id: int | None = Field(default=None, foreign_key="task.id", index=True)
    # Review and check state at the PR's current head (docs/AGENT_EXECUTION.md §11.3), kept fresh
    # by the `pull_request`, `pull_request_review`, `check_suite` / `check_run` and `status`
    # webhooks and by MCP / file ingest. Stage checks and gates read these; a webhook never moves a
    # status by itself. Interpreting them is `app/services/pr_signals.py` (pure).
    draft: bool = False
    merged: bool = False
    merged_at: datetime | None = None
    merged_by: str | None = None
    head_branch: str | None = None
    head_sha: str | None = None
    # approved | changes_requested | review_required — None while no review has been seen.
    review_decision: str | None = None
    # The latest review per reviewer: [{login, state, commit_id, submitted_at, body}].
    reviews: list = Field(default_factory=list, sa_column=Column(JSON))
    # Logins whose latest review approves the current head (a stale approval does not count).
    approved_by: list = Field(default_factory=list, sa_column=Column(JSON))
    # Each check seen at the current head, e.g. {"suite:github-actions": "success"}; reset when
    # the head moves. `checks_state` is their roll-up: pending | passing | failing (None = none).
    checks: dict = Field(default_factory=dict, sa_column=Column(JSON))
    checks_state: str | None = None
    additions: int | None = None
    deletions: int | None = None
    changed_files: int | None = None


class TrackerBinding(TimestampMixin, table=True):
    """Attaches a canopy project (or initiative) to a scope inside a tracker connection: a whole
    tracker project/team (`scope_kind=project`), an item and its descendants (`subtree` — a
    "tracker link"), or a saved query. Owns everything per-target: the sync watermark, the
    type/field mapping and the tracker's status map (the mirrored board's columns). A project has
    at most one active binding; detached rows are kept as the record of every tracker it used."""

    id: int | None = Field(default=None, primary_key=True)
    connection_id: int = Field(foreign_key="connection.id", index=True)
    provider: Provider = Field(sa_type=ProviderType, index=True)
    target_type: str = Field(index=True)  # project | initiative
    target_id: int = Field(index=True)
    scope_kind: str = "project"  # project | subtree | query
    scope: dict = Field(default_factory=dict, sa_column=Column(JSON))
    mapping: dict = Field(default_factory=dict, sa_column=Column(JSON))
    # [{name, category, position}] — the tracker's statuses, refreshed on each full sync.
    status_map: list = Field(default_factory=list, sa_column=Column(JSON))
    sync_iterations: bool = False  # mirror the tracker's sprints/cycles for this target
    watermark: str | None = None
    # The highest task `ExternalRef.id` the nightly changelog backfill has reached.
    backfill_cursor: int | None = None
    active: bool = True
    last_synced_at: datetime | None = None
    detached_at: datetime | None = None


class EngineerIdentity(TimestampMixin, table=True):
    """An engineer's account in one tracker, so synced assignees from any tracker land on the
    same person (recorded by sync: matched by account id, then email, then exact name)."""

    __table_args__ = (
        UniqueConstraint("provider", "external_account_id", name="uq_engineer_identity"),
    )

    id: int | None = Field(default=None, primary_key=True)
    engineer_id: int = Field(foreign_key="engineer.id", index=True)
    provider: Provider = Field(sa_type=ProviderType)
    external_account_id: str
    display_name: str | None = None
