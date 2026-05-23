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
