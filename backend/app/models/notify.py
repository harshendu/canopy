"""Outbound notifications — docs/AGENT_EXECUTION.md §15 (push starts), §17 (the plan on the
ticket) and Phase 3's gate notifications.

* `OutboundWebhook` — a destination a team points at its runner, a scheduled task's API
  trigger, or Slack: which events it hears (`work.ready`, `gate.opened`, `gate.reminder`,
  `gate.escalated`, `gate.decided`), at which scope (workspace, a team, a project), and in which
  format (`json`, signed with HMAC-SHA256 when it has a secret; `slack`, an incoming-webhook
  message). The signing secret is Fernet-encrypted at rest, like connector tokens.
* `OutboxMessage` — one delivery waiting to go out (a webhook call, a comment on a mirrored
  ticket, an email), written in the same transaction as the change it reports and drained by
  the worker (`deliver_outbox`) with retries and backoff — a transactional outbox, so nothing is
  lost when the network or Redis is down and nothing is sent for a change that rolled back.
  The id columns are plain integers (audit metadata): the log never blocks a delete.
"""

from datetime import datetime

from sqlalchemy import JSON, Column, Text
from sqlmodel import Field

from app.models.base import TimestampMixin, utcnow


class OutboundWebhook(TimestampMixin, table=True):
    id: int | None = Field(default=None, primary_key=True)
    scope_level: str = "workspace"  # workspace | team | project
    scope_id: int = Field(default=0, index=True)  # 0 for the workspace
    name: str
    url: str = Field(sa_column=Column(Text, nullable=False))
    format: str = "json"  # json | slack
    events: list = Field(default_factory=list, sa_column=Column(JSON))
    secret_encrypted: str | None = Field(default=None, sa_column=Column(Text))
    enabled: bool = True
    created_by_user_id: int | None = None
    last_delivery_at: datetime | None = None
    last_status: str | None = None  # "200", or why the last delivery failed (short)
    consecutive_failures: int = 0


class OutboxMessage(TimestampMixin, table=True):
    id: int | None = Field(default=None, primary_key=True)
    channel: str = Field(index=True)  # webhook | tracker_comment | email
    event: str  # work.ready | gate.* | plan.approved
    webhook_id: int | None = Field(default=None, index=True)
    connection_id: int | None = None
    project_id: int | None = Field(default=None, index=True)
    task_id: int | None = Field(default=None, index=True)
    recipient: str | None = None  # an email address (the email channel)
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON))
    # Sends at most once per key: a ready task is announced once per readiness, a gate once per
    # event and level.
    dedupe_key: str | None = Field(default=None, index=True)
    status: str = Field(default="pending", index=True)  # pending | sent | failed
    attempts: int = 0
    next_attempt_at: datetime = Field(default_factory=utcnow, index=True)
    sent_at: datetime | None = None
    response_status: int | None = None
    last_error: str | None = Field(default=None, sa_column=Column(Text))
