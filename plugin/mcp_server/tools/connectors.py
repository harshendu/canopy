"""Connector tools: Jira sync + GitHub/Drive reads."""

from __future__ import annotations


def register(mcp, client) -> None:
    @mcp.tool
    async def list_connections() -> list[dict]:
        """List configured connectors (Jira / GitHub / Google Drive) with their ids."""
        return await client.get("/connectors/connections")

    @mcp.tool
    async def trigger_jira_sync(connection_id: int, incremental: bool = True) -> dict:
        """Sync issues from Jira into canopy for a given connection.

        Set incremental=False to force a full re-sync. Jira remains the source of
        truth for ticket status; canopy never writes status back.
        """
        suffix = "/sync/incremental" if incremental else "/sync"
        return await client.post(f"/connectors/connections/{connection_id}{suffix}")

    @mcp.tool
    async def list_open_prs(connection_id: int) -> list[dict]:
        """List open pull requests for a GitHub connection."""
        return await client.get(f"/connectors/github/{connection_id}/pulls")

    @mcp.tool
    async def read_design_doc(connection_id: int, file_id: str) -> dict:
        """Export a Google Drive design doc to markdown text by its Drive file id."""
        return await client.get(f"/connectors/gdrive/{connection_id}/docs/{file_id}")

    @mcp.tool
    async def read_repo_file(connection_id: int, path: str) -> dict:
        """Read a file (e.g. an architecture markdown doc) from a GitHub repo connection."""
        return await client.get(
            f"/connectors/github/{connection_id}/file", params={"path": path}
        )

    @mcp.tool
    async def get_activity(project_id: int) -> list[dict]:
        """The project's activity feed: deploys, build failures, and incidents."""
        return await client.get(f"/projects/{project_id}/activity")

    @mcp.tool
    async def record_activity(
        project_id: int,
        kind: str,
        summary: str,
        component_id: int | None = None,
        reference: str | None = None,
    ) -> dict:
        """Record a CI/observability event. kind: deploy | build_failure | incident_open |
        incident_close. An incident_open auto-opens a postmortem; build failures and open
        incidents feed the quality-risk family."""
        return await client.post(
            f"/projects/{project_id}/activity",
            {
                "kind": kind,
                "summary": summary,
                "component_id": component_id,
                "reference": reference,
                "source": "agent",
            },
        )
