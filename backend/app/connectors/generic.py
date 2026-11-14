"""A generic work tracker (USER_FLOWS §J0): any tracker canopy has no connector for — Shortcut,
Asana, an in-house tool, a spreadsheet. canopy never calls it (`direct_read` is off); its items
arrive normalized through MCP ingest (`ingest_work_items`), a JSON/CSV file drop, or a signed
webhook carrying one item. Everything else — tasks, parents, statuses with their categories,
history, bindings, switching — works as for any tracker.

Webhook (`POST /webhooks/generic`, `GENERIC_WEBHOOK_SECRET`): the raw body signed as
`X-Canopy-Signature: sha256=<hex HMAC-SHA256>`, carrying
`{"item": {<an ingest item: external_id, external_key, summary, status, status_category, kind,
parent_external_id, updated, assignee_*, estimate, url>}, "scope": {"project_key": "…"},
"action": "upsert" | "remove"}`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

import httpx
from pydantic import BaseModel, ValidationError

from app.connectors.tracker import WorkTracker, register_tracker
from app.models.base import Provider
from app.services.tracker_types import TrackerCapabilities, WebhookEvent


class GenericConnectionConfig(BaseModel):
    """What canopy needs to show this tracker's items (nothing to authenticate)."""

    tracker_name: str | None = None  # how people call it, e.g. "Shortcut"
    # A browse link per item, e.g. "https://app.example.com/story/{key}".
    item_url_template: str | None = None


class GenericScope(BaseModel):
    """Which of the tracker's items a binding mirrors (free text — matched against the
    `scope` a webhook sends)."""

    project_key: str | None = None


@register_tracker(Provider.generic)
class GenericTracker(WorkTracker):
    label: ClassVar[str] = "Generic tracker"
    capabilities: ClassVar[TrackerCapabilities] = TrackerCapabilities(
        direct_read=False,
        hierarchy=True,
        status_categories=False,
        webhooks=True,
    )
    config_schema: ClassVar[type[BaseModel]] = GenericConnectionConfig
    scope_schema: ClassVar[type[BaseModel]] = GenericScope
    webhook_signature_header: ClassVar[str | None] = "X-Canopy-Signature"
    scope_selector_keys: ClassVar[tuple[str, ...]] = ("project_key",)

    def _client(self) -> httpx.AsyncClient:  # pragma: no cover - never called (no direct read)
        raise NotImplementedError("canopy does not call a generic tracker")

    @classmethod
    def browse_url(cls, config: Mapping[str, Any], key: str) -> str | None:
        template = config.get("item_url_template")
        if not template or "{key}" not in str(template):
            return None
        return str(template).replace("{key}", key)

    @classmethod
    def webhook_scope_hint(cls, payload: dict[str, Any]) -> dict[str, Any]:
        scope = payload.get("scope")
        return dict(scope) if isinstance(scope, dict) else {}

    def parse_webhook(self, payload: dict[str, Any]) -> WebhookEvent | None:
        from app.schemas.entities import IngestIssue
        from app.services.ingest import epic_type_names, item_from_ingest

        raw = payload.get("item")
        if not isinstance(raw, dict):
            return None
        try:
            issue = IngestIssue.model_validate(raw)
        except ValidationError:
            return None
        hint = self.webhook_scope_hint(payload)
        if payload.get("action") == "remove":
            return WebhookEvent(item=None, scope_hint=hint, deleted=True)
        return WebhookEvent(
            item=item_from_ingest(issue, epic_type_names(self.config)), scope_hint=hint
        )
