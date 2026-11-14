"""A project's tracking (USER_FLOWS §C12): native (canopy owns every status) or mirrored from a
bound tracker — read it, adjust the binding, sync it, and switch with a previewed plan."""

from __future__ import annotations


def register(mcp, client) -> None:
    @mcp.tool
    async def get_project_tracking(project_id: int) -> dict:
        """How a project is tracked: `mode` (native | mirrored), the active tracker
        `binding` (connection, provider, scope, mapping, the tracker's statuses), the trackers
        it used before (`history`), what the bound tracker supports, and how many tasks canopy
        vs the tracker owns. Read this before moving cards or proposing statuses: a mirrored
        task's status belongs to its tracker."""
        return await client.get(f"/projects/{project_id}/tracking")

    @mcp.tool
    async def set_project_tracking(
        project_id: int,
        scope: dict | None = None,
        mapping: dict | None = None,
        sync_iterations: bool | None = None,
    ) -> dict:
        """Adjust the project's active binding in place (same tracker connection): its `scope`
        (e.g. Jira {"project_key": "SHOP", "board_id": 7}), the type/field `mapping`
        ({"epic_types": ["Epic"], "estimate_field": "customfield_10016"}) or sprint mirroring.
        A new scope resets the watermark, so the next sync is a full one. To bind another
        tracker or go native, use `switch_project_tracking`."""
        body: dict = {}
        if scope is not None:
            body["scope"] = scope
        if mapping is not None:
            body["mapping"] = mapping
        if sync_iterations is not None:
            body["sync_iterations"] = sync_iterations
        return await client.put(f"/projects/{project_id}/tracking", body)

    @mcp.tool
    async def switch_project_tracking(
        project_id: int,
        to_mode: str,
        connection_id: int | None = None,
        scope: dict | None = None,
        mapping: dict | None = None,
        strategy: str = "keep_separate",
        sync_iterations: bool = False,
        dry_run: bool = True,
    ) -> dict:
        """Preview (default) or apply switching a project between native and mirrored tracking,
        or to another tracker. to_mode: native | mirrored (mirrored needs `connection_id` + the
        tracker `scope`). strategy, for the work the project already has: keep_separate (stays
        canopy-only work) | match (tasks whose key/title match a tracker item are adopted by
        it) | publish (open tasks are created in the tracker — content only — and handed over).

        The preview lists what happens to every task (keep | adopt | publish | release |
        remap) with counts and warnings; show it to the human. Applying (`dry_run=False`)
        does exactly that plan and is human-only — an agent token gets 403, so ask the human
        to apply it in canopy."""
        body: dict = {
            "to_mode": to_mode,
            "strategy": strategy,
            "sync_iterations": sync_iterations,
            "dry_run": dry_run,
        }
        if connection_id is not None:
            body["connection_id"] = connection_id
        if scope is not None:
            body["scope"] = scope
        if mapping is not None:
            body["mapping"] = mapping
        return await client.post(f"/projects/{project_id}/tracking/switch", body)

    @mcp.tool
    async def sync_project_tracking(project_id: int, full: bool = False) -> dict:
        """Pull this project's tracker binding now (incremental; `full=True` re-reads
        everything and refreshes the tracker's statuses). 409 when the project has no
        binding, or when canopy doesn't read that tracker directly (ingest instead)."""
        suffix = "?full=true" if full else ""
        return await client.post(f"/projects/{project_id}/tracking/sync{suffix}")

    @mcp.tool
    async def publish_project_tasks(project_id: int) -> dict:
        """Create a mirrored project's open canopy-owned tasks as items in its tracker (content
        only — never status) and hand their status to it. Idempotent; human-only (an agent
        token gets 403)."""
        return await client.post(f"/projects/{project_id}/tracking/publish")
