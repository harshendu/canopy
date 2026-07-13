"""Schema for the public instance-metadata endpoint (GET /api/v1/meta)."""

from pydantic import BaseModel


class SetupMeta(BaseModel):
    """Deployment-facing, non-secret values that drive the Agent Setup snippets."""

    project_name: str
    plugin_marketplace_ref: str  # `/plugin marketplace add <ref>`
    plugin_repo_url: str  # MCP-only clone URL
    plugin_mcp_server_path: str  # server path within the clone
