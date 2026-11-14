"""Schema for the public instance-metadata endpoint (GET /api/v1/meta)."""

from typing import Any

from pydantic import BaseModel


class SetupMeta(BaseModel):
    """Deployment-facing, non-secret values that drive the Agent Setup snippets."""

    project_name: str
    plugin_marketplace_ref: str  # `/plugin marketplace add <ref>`
    plugin_repo_url: str  # MCP-only clone URL
    plugin_mcp_server_path: str  # server path within the clone


class TrackerCapabilitiesRead(BaseModel):
    direct_read: bool
    hierarchy: bool
    status_categories: bool
    status_history: bool
    iterations: bool
    webhooks: bool
    create_items: bool
    update_items: bool
    estimates: bool
    oauth: bool


class TrackerMeta(BaseModel):
    """A work tracker canopy can mirror (registered in code; `enabled` per TRACKERS_ENABLED)."""

    provider: str
    label: str
    enabled: bool
    capabilities: TrackerCapabilitiesRead
    # JSON Schemas the UI renders the connection form and a binding's scope form from.
    config_schema: dict[str, Any]
    scope_schema: dict[str, Any]
    # The webhook URL path (when the tracker pushes) and the secret that verifies it.
    webhook_path: str | None = None
    webhook_secret_setting: str | None = None


class TrackersMeta(BaseModel):
    trackers: list[TrackerMeta]
    # The tracking mode a new project starts in (native | mirrored), see TRACKING_DEFAULT_MODE.
    default_tracking_mode: str = "native"
