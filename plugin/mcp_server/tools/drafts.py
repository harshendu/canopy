"""Draft-plan tools: stage a reviewable plan, then create/update Jira tickets from it.

canopy never owns Jira tickets. Pushing a plan writes ticket *content* (summary,
description, story points) and the epic→story parent link — never status. After a push,
run a Jira sync (`trigger_jira_sync`) to pull the new issues back in as canopy tasks.
"""

from __future__ import annotations


def register(mcp, client) -> None:
    @mcp.tool
    async def list_draft_plans(project_id: int) -> list[dict]:
        """List a project's draft plans (the staging area for proposed work)."""
        return await client.get(f"/projects/{project_id}/draft-plans")

    @mcp.tool
    async def create_draft_plan(
        project_id: int, title: str, description: str | None = None, source: str | None = None
    ) -> dict:
        """Create a draft plan the architect reviews before any Jira tickets are made.

        `source` is a free-text note on where the plan came from (e.g. a design-doc or PRD url).
        """
        return await client.post(
            f"/projects/{project_id}/draft-plans",
            {"title": title, "description": description, "source": source},
        )

    @mcp.tool
    async def get_draft_plan(plan_id: int) -> dict:
        """A draft plan with its proposed tasks (estimates, story points, Jira keys once pushed)."""
        return await client.get(f"/draft-plans/{plan_id}")

    @mcp.tool
    async def add_draft_task(
        plan_id: int,
        name: str,
        task_type: str = "task",
        estimate_days: int = 1,
        story_points: float | None = None,
        parent_id: int | None = None,
        description: str | None = None,
    ) -> dict:
        """Add a proposed task to a draft plan.

        task_type: task | summary (epic/phase) | milestone. Set parent_id to a summary
        draft-task id to nest it (epic → story). story_points are pushed to Jira's
        story-point field; estimate_days is the canopy duration (working days).
        """
        return await client.post(
            f"/draft-plans/{plan_id}/tasks",
            {
                "name": name,
                "type": task_type,
                "estimate_days": estimate_days,
                "story_points": story_points,
                "parent_id": parent_id,
                "description": description,
            },
        )

    @mcp.tool
    async def update_draft_task(
        task_id: int,
        name: str | None = None,
        estimate_days: int | None = None,
        story_points: float | None = None,
        parent_id: int | None = None,
        description: str | None = None,
    ) -> dict:
        """Update a draft task's planning fields (only args you pass are changed)."""
        body: dict = {}
        for field, value in (
            ("name", name),
            ("estimate_days", estimate_days),
            ("story_points", story_points),
            ("parent_id", parent_id),
            ("description", description),
        ):
            if value is not None:
                body[field] = value
        return await client.patch(f"/draft-tasks/{task_id}", body)

    @mcp.tool
    async def delete_draft_task(task_id: int) -> dict:
        """Remove a proposed task from its draft plan."""
        return await client.delete(f"/draft-tasks/{task_id}")

    @mcp.tool
    async def push_draft_to_jira(plan_id: int, connection_id: int | None = None) -> dict:
        """Create/update Jira tickets from a reviewed draft plan (content only — never status).

        Auto-detects the project's Jira connection when connection_id is omitted. Epics are
        created before their stories so the parent link resolves; a re-push updates the
        already-created tickets instead of duplicating. Afterwards, run `trigger_jira_sync`
        to pull the new issues back in as canopy tasks.
        """
        return await client.post(
            f"/draft-plans/{plan_id}/push-to-jira", {"connection_id": connection_id}
        )

    @mcp.tool
    async def record_draft_push(plan_id: int, results: list[dict]) -> dict:
        """Record Jira tickets you created **yourself** for a draft plan (use when the Jira
        connection's writes are MCP-managed, so `push_draft_to_jira` is disabled).

        After you create the tickets via your own Jira tools, call this to stamp each draft task
        with its new Jira id/key and flip the plan to `synced`. `results` is a list of dicts:
        {"draft_task_id": 12, "jira_issue_id": "<jira id>", "jira_key": "PROJ-123"}. Idempotent —
        re-recording the same ids won't create duplicates, so a re-push stays safe.
        """
        return await client.post(
            f"/draft-plans/{plan_id}/record-push", {"results": results}
        )
