"""API shapes for outbound webhooks and their deliveries (USER_FLOWS §AE9)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Event = Literal["work.ready", "gate.opened", "gate.reminder", "gate.escalated", "gate.decided"]


class WebhookCreate(BaseModel):
    scope_level: Literal["workspace", "team", "project"]
    scope_id: int = 0  # 0 for the workspace
    name: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=8, max_length=2000)
    format: Literal["json", "slack"] = "json"
    events: list[Event] = Field(min_length=1)
    # The HMAC signing secret for `json` destinations (stored encrypted, never returned).
    secret: str | None = Field(default=None, max_length=500)
    enabled: bool = True


class WebhookUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    url: str | None = Field(default=None, min_length=8, max_length=2000)
    format: Literal["json", "slack"] | None = None
    events: list[Event] | None = Field(default=None, min_length=1)
    secret: str | None = Field(default=None, max_length=500)  # "" removes it
    enabled: bool | None = None


class WebhookRead(BaseModel):
    id: int
    scope_level: str
    scope_id: int
    scope_name: str | None = None
    name: str
    # The full URL only for people who may edit the hook (a Slack URL is itself a credential);
    # everyone else sees scheme and host.
    url: str
    format: str
    events: list[str]
    has_secret: bool
    enabled: bool
    last_delivery_at: datetime | None = None
    last_status: str | None = None
    consecutive_failures: int = 0
    can_edit: bool = False
    created_at: datetime


class WebhookCatalog(BaseModel):
    events: list[str]
    formats: list[str]
    email_enabled: bool
    signature_header: str


class DeliveryRead(BaseModel):
    id: int
    event: str
    channel: str
    status: str
    attempts: int
    task_id: int | None = None
    response_status: int | None = None
    last_error: str | None = None
    created_at: datetime
    sent_at: datetime | None = None
    next_attempt_at: datetime


class TestDeliveryRead(BaseModel):
    delivered: bool
    status: str
    response_status: int | None = None
    error: str | None = None
