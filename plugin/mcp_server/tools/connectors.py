"""Connector tools: work-tracker sync, links and ingest (Jira, Linear, a generic tracker…) +
GitHub/Drive reads."""

from __future__ import annotations


def register(mcp, client) -> None:
    @mcp.tool
    async def list_connections() -> list[dict]:
        """List configured connectors (work trackers such as Jira, plus GitHub / Google Drive)
        with their ids."""
        return await client.get("/connectors/connections")

    @mcp.tool
    async def list_trackers() -> dict:
        """The work trackers this canopy knows: per tracker its label, whether it's enabled,
        what it supports (`capabilities`: direct_read, create_items, webhooks, iterations…),
        the JSON Schemas of its connection and binding-scope settings, and the default
        tracking mode for new projects. Check capabilities before promising an action."""
        return await client.get("/meta/trackers")

    @mcp.tool
    async def sync_tracker(connection_id: int, incremental: bool = True) -> dict:
        """Pull a tracker connection's items into canopy — every project/initiative it is
        bound to (idempotent; epics → summary tasks, items → tasks, parents wired, a replan
        when tasks were created). `incremental=False` forces a full re-sync, which also
        refreshes the tracker's statuses (a mirrored board's columns). The tracker stays the
        owner of its items' status; canopy never writes status back. For one project use
        `sync_project_tracking`."""
        suffix = "/sync/incremental" if incremental else "/sync"
        return await client.post(f"/connectors/connections/{connection_id}{suffix}")

    @mcp.tool
    async def link_tracker_item(
        root_key: str,
        target_type: str,
        target_id: int,
        connection_id: int,
    ) -> dict:
        """Link one tracker item (an initiative/epic/story, e.g. "SHOP-12" or "ENG-42") to a
        canopy project or initiative, then map it plus its full descendant subtree into canopy
        (idempotently).

        target_type is "project" or "initiative". For a project every item becomes a task
        (epics → summary tasks); for an initiative each descendant epic becomes a project under
        it and its items become tasks. Re-linking the same item is an update. The tracker stays
        the source of truth for status. Needs a tracker canopy reads directly with a hierarchy
        (see `list_trackers`)."""
        return await client.post(
            "/tracker-links",
            {
                "connection_id": connection_id,
                "root_key": root_key,
                "target_type": target_type,
                "target_id": target_id,
            },
        )

    @mcp.tool
    async def list_tracker_links(target_type: str, target_id: int) -> list[dict]:
        """The tracker items linked to a canopy target (target_type: project | initiative),
        each with its provider, root key/type and browse URL."""
        return await client.get(
            "/tracker-links", params={"target_type": target_type, "target_id": target_id}
        )

    @mcp.tool
    async def resync_tracker_link(link_id: int) -> dict:
        """Re-pull a tracker link's subtree and re-map it into canopy (idempotent update)."""
        return await client.post(f"/tracker-links/{link_id}/resync")

    @mcp.tool
    async def unlink_tracker_item(link_id: int) -> dict:
        """Remove a tracker link. What it mapped stays in canopy (tasks keep their history)."""
        return await client.delete(f"/tracker-links/{link_id}")

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

    @mcp.tool
    async def ingest_work_items(
        connection_id: int, items: list[dict], project_id: int | None = None
    ) -> dict:
        """Push work items you've read yourself (with your own Jira / Linear / … tools, or from
        an export) into canopy as tasks, idempotently — the MCP twin of `sync_tracker`, and how
        a tracker canopy can't read directly is kept in sync.

        Each item: {"external_id": "<the tracker's stable id>", "external_key": "PROJ-123",
        "summary": "...", "status": "In Progress", "status_category": "in_progress" (todo |
        in_progress | done | cancelled — send it when the tracker says), "kind": "epic" | "item"
        | "subitem" (or "issue_type": "Epic"), "parent_external_id": "<parent id or null>",
        "updated": "<the tracker's updated timestamp>", "assignee_name"/"assignee_email"/
        "assignee_account_id", "estimate": 3}. Epics become summary tasks; re-ingesting updates
        (never duplicates); status is mirrored read-only. Items land in the connection's bound
        project — pass `project_id` when it feeds several. New tasks trigger a replan."""
        body: dict = {"issues": items}
        if project_id is not None:
            body["project_id"] = project_id
        return await client.post(f"/connectors/connections/{connection_id}/ingest/issues", body)

    @mcp.tool
    async def ingest_github_pull_requests(connection_id: int, pull_requests: list[dict]) -> dict:
        """Push GitHub pull requests you've read yourself into canopy's PR cache, idempotently
        (the MCP twin of the GitHub PR webhook, for when the connection's reads are MCP-managed).

        Each PR is a dict: {"number": 42, "title": "...", "state": "open", "url": "https://...",
        "author": "octocat", "updated": "<updated timestamp>", "branch": "feat/SHOP-12-x"}.
        Keyed on (repo, number); the repo comes from the connection config. Re-ingesting the
        same PR updates it. A PR is tied to the task whose key (a tracker key or a native
        canopy key) appears in its title or branch.

        Include what you know of its review / check / merge state — stage checks and gates read
        it: "head_sha", "draft", "merged", "merged_at", "merged_by", "additions", "deletions",
        "changed_files", "review_decision" (approved | changes_requested | review_required),
        "approved_by" (logins whose approval covers the current head) and "checks_state"
        (pending | passing | failing). Leave out what you don't know; the cached value is kept.
        """
        return await client.post(
            f"/connectors/connections/{connection_id}/ingest/pull-requests",
            {"pull_requests": pull_requests},
        )
