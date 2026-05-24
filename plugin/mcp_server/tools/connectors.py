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
    async def link_jira_ticket(
        jira_key: str,
        target_type: str,
        target_id: int,
        connection_id: int,
    ) -> dict:
        """Link a Jira ticket (initiative/epic/story) to a canopy project or initiative, then
        map the ticket plus its full descendant subtree into canopy (idempotently).

        target_type is "project" or "initiative". For a project target every issue becomes a
        Task; for an initiative target each child epic becomes a Project under the initiative
        and its stories become tasks. Re-linking the same ticket is an idempotent update.
        Jira stays the source of truth for status (never written back).
        """
        return await client.post(
            "/jira-links",
            {
                "connection_id": connection_id,
                "jira_key": jira_key,
                "target_type": target_type,
                "target_id": target_id,
            },
        )

    @mcp.tool
    async def list_jira_links(target_type: str, target_id: int) -> list[dict]:
        """List the Jira tickets linked to a canopy target. target_type: project | initiative."""
        return await client.get(
            "/jira-links", params={"target_type": target_type, "target_id": target_id}
        )

    @mcp.tool
    async def resync_jira_link(link_id: int) -> dict:
        """Re-pull a Jira link's subtree and re-map it into canopy (idempotent update)."""
        return await client.post(f"/jira-links/{link_id}/resync")

    @mcp.tool
    async def unlink_jira_ticket(link_id: int) -> dict:
        """Remove a Jira link. Entities already mapped into canopy are kept (canopy-owned now)."""
        return await client.delete(f"/jira-links/{link_id}")

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
