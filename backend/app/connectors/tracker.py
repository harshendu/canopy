"""The work-tracker interface: what a tracker (Jira, Linear, an MCP/file-fed generic one…)
implements so canopy can mirror its work items.

Three layers (USER_FLOWS §J0):

1. `Connector` (`base.py`) — credentials, HTTP client, token refresh, the demo mock.
2. `WorkTracker` (here) — the capability interface. It only **fetches and normalizes** into
   `app/services/tracker_types.py` dataclasses, and writes item **content** (never status:
   there is deliberately no transition method, so canopy cannot write status back by accident).
3. The sync engine (`app/services/tracker_sync.py`) — the only caller. It owns upsert, parent
   wiring, watermarks, status history, sprint mirroring, epic→project mapping and auto-replan,
   written once for every tracker.

A new tracker is one module: subclass `WorkTracker`, declare `capabilities`, the connection
`config_schema` and binding `scope_schema`, implement what it supports, and decorate it with
`@register_tracker(Provider.x)`. No migration, no engine or UI change.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Callable, Mapping
from typing import Any, ClassVar

from pydantic import BaseModel

from app.connectors.base import Connector, SyncResult, register
from app.core.config import settings
from app.models.base import Provider
from app.services.tracker_types import (
    ItemDraft,
    ItemPage,
    ItemPatch,
    ItemRef,
    Iteration,
    Scope,
    StatusChange,
    StatusDef,
    TrackerCapabilities,
    WebhookEvent,
    WorkItem,
)


class EmptyConfig(BaseModel):
    """A tracker with nothing to configure at this level."""


class WorkTracker(Connector):
    """Base class for work trackers. Unsupported operations raise `NotImplementedError`; the
    engine checks `capabilities` first, so a tracker only implements what it declares."""

    label: ClassVar[str] = ""
    capabilities: ClassVar[TrackerCapabilities] = TrackerCapabilities()
    # JSON-Schema'd settings: the connection (site, auth) and a binding's scope (project key…).
    config_schema: ClassVar[type[BaseModel]] = EmptyConfig
    scope_schema: ClassVar[type[BaseModel]] = EmptyConfig
    # Header carrying an HMAC-SHA256 hex signature (`sha256=<hex>` or bare hex) of the body.
    webhook_signature_header: ClassVar[str | None] = None
    # The scope keys that select *which items* a binding mirrors (e.g. Jira's project key or
    # JQL; not a board, which only adds sprints). Two projects may not bind the same selection.
    # Empty = the whole scope.
    scope_selector_keys: ClassVar[tuple[str, ...]] = ()

    @classmethod
    def scope_selection(cls, scope: Mapping[str, Any]) -> dict[str, Any]:
        keys = cls.scope_selector_keys or tuple(scope)
        return {k: scope.get(k) for k in keys if scope.get(k) not in (None, "")}

    # --- read ---
    async def fetch_items(self, scope: Scope, since: str | None) -> ItemPage:
        """Items in scope updated since the watermark (None = everything)."""
        raise NotImplementedError

    async def fetch_item(self, scope: Scope, key: str) -> WorkItem | None:
        raise NotImplementedError

    async def fetch_subtree(self, scope: Scope, root_key: str) -> list[WorkItem]:
        """An item and every descendant (a subtree binding / link)."""
        raise NotImplementedError

    async def list_statuses(self, scope: Scope) -> list[StatusDef]:
        """The tracker's statuses for this scope, with category and order (the mirrored
        project's board columns). Empty when unknown."""
        return []

    async def fetch_status_changes(self, scope: Scope, ref: ItemRef) -> list[StatusChange]:
        """An item's status transitions from the tracker's changelog (exact times)."""
        return []

    async def fetch_iterations(self, scope: Scope) -> list[Iteration]:
        """Sprints/cycles in scope (planned, active and recently completed), with members."""
        return []

    # --- write: item content only (never status) ---
    async def create_item(self, scope: Scope, draft: ItemDraft) -> ItemRef:
        raise NotImplementedError

    async def update_item(self, scope: Scope, ref: ItemRef, patch: ItemPatch) -> None:
        raise NotImplementedError

    # --- webhooks ---
    @classmethod
    def verify_webhook(cls, headers: Mapping[str, str], body: bytes, secret: str) -> bool:
        """Constant-time HMAC-SHA256 check of the raw body, run before anything parses it.
        Fails closed: no secret, no header or a mismatch all reject."""
        header = cls.webhook_signature_header
        if not secret or not header:
            return False
        given = headers.get(header) or headers.get(header.lower())
        if not given:
            return False
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        candidate = given.split("=", 1)[1] if given.startswith("sha256=") else given
        return hmac.compare_digest(expected, candidate)

    @classmethod
    def webhook_scope_hint(cls, payload: dict[str, Any]) -> dict[str, Any]:
        """Which binding scope a (verified) payload belongs to, e.g. `{"project_key": "SHOP"}`
        — matched against bindings to pick the connections to enqueue. Empty = every one."""
        return {}

    def parse_webhook(self, payload: dict[str, Any]) -> WebhookEvent | None:
        return None

    # --- links ---
    @classmethod
    def browse_url(cls, config: Mapping[str, Any], key: str) -> str | None:
        """A browsable URL for an item from the connection's config — None when the tracker
        exposes no site to link to (the UI then shows the key without a link)."""
        return None

    def item_url(self, key: str) -> str | None:
        return self.browse_url(self.config, key)

    # --- Connector entry points: everything goes through the engine ---
    async def full_sync(self) -> SyncResult:
        from app.services.tracker_sync import sync_connection

        return await sync_connection(self, full=True)

    async def incremental_sync(self, since: str | None = None) -> SyncResult:
        from app.services.tracker_sync import sync_connection

        return await sync_connection(self, full=False, since=since)

    async def handle_webhook(self, payload: dict[str, Any]) -> SyncResult:
        from app.services.tracker_sync import apply_webhook

        return await apply_webhook(self, payload)


_TRACKERS: dict[Provider, type[WorkTracker]] = {}


def register_tracker(provider: Provider) -> Callable[[type[WorkTracker]], type[WorkTracker]]:
    """Register a work tracker (also as a plain connector for credentials/OAuth/reads)."""

    def deco(cls: type[WorkTracker]) -> type[WorkTracker]:
        register(provider)(cls)
        _TRACKERS[provider] = cls
        return cls

    return deco


def tracker_class(provider: Provider | str) -> type[WorkTracker] | None:
    try:
        return _TRACKERS.get(Provider(str(provider)))
    except ValueError:
        return None


def is_tracker(provider: Provider | str) -> bool:
    return tracker_class(provider) is not None


def enabled_tracker_keys() -> list[str]:
    """Providers listed in `TRACKERS_ENABLED` that are registered trackers (empty = native
    only: no tracker can be bound)."""
    wanted = [k.strip().lower() for k in settings.TRACKERS_ENABLED.split(",") if k.strip()]
    return [k for k in wanted if is_tracker(k)]


def tracker_enabled(provider: Provider | str) -> bool:
    return str(provider) in enabled_tracker_keys()


def registered_trackers() -> dict[Provider, type[WorkTracker]]:
    return dict(_TRACKERS)
