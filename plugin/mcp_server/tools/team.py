"""Team & capacity tools."""

from __future__ import annotations


def register(mcp, client) -> None:
    @mcp.tool
    async def list_engineers() -> list[dict]:
        """List engineers on the team (id, name, title, role)."""
        return await client.get("/team/engineers")

    @mcp.tool
    async def add_engineer(
        name: str,
        title: str | None = None,
        skill_tags: list[str] | None = None,
        github_login: str | None = None,
        timezone: str | None = None,
        committed_hours_per_week: float | None = None,
        user_id: int | None = None,
    ) -> dict:
        """Add an engineer to the team.

        `skill_tags` feed skill-fit signals; `user_id` links this engineer to a login so
        their /me workspace shows their assigned tasks and decisions.
        """
        return await client.post(
            "/team/engineers",
            {
                "name": name,
                "title": title,
                "skill_tags": skill_tags or [],
                "github_login": github_login,
                "timezone": timezone,
                "committed_hours_per_week": committed_hours_per_week,
                "user_id": user_id,
            },
        )

    @mcp.tool
    async def get_capacity(project_id: int | None = None) -> dict:
        """Get the weekly capacity grid (engineer × week allocation %).

        Pass a `project_id` for one project, or omit it for an **org-wide** grid that sums each
        engineer's allocation across all projects — the only way to see cross-project
        over-allocation (someone at 50% on three projects = 150%). Cells over 100% are
        over-allocated; each row lists the project keys contributing to it.
        """
        params = {"project_id": project_id} if project_id is not None else None
        return await client.get("/team/capacity", params=params)

    @mcp.tool
    async def allocate_engineer(
        engineer_id: int,
        project_id: int | None = None,
        percent_allocation: float = 100.0,
        capacity_hours_per_week: float = 40.0,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict:
        """Allocate an engineer's capacity to a project over a date range.

        `percent_allocation` is their share of a week (overlapping allocations sum, so >100%
        across allocations is over-allocation). `start_date`/`end_date` are YYYY-MM-DD; omit
        for an open-ended allocation. Feeds the capacity grid (`get_capacity`).
        """
        return await client.post(
            "/team/allocations",
            {
                "engineer_id": engineer_id,
                "project_id": project_id,
                "percent_allocation": percent_allocation,
                "capacity_hours_per_week": capacity_hours_per_week,
                "start_date": start_date,
                "end_date": end_date,
            },
        )

    @mcp.tool
    async def my_workspace() -> dict:
        """Get the current user's workspace: their linked engineer profile, assigned open
        tasks (most-critical first), and the decisions they own or must review."""
        return await client.get("/me/workspace")
