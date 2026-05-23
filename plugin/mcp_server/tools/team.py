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
    async def get_capacity(project_id: int) -> dict:
        """Get the weekly capacity grid (engineer × week allocation %) for a project."""
        return await client.get("/team/capacity", params={"project_id": project_id})

    @mcp.tool
    async def my_workspace() -> dict:
        """Get the current user's workspace: their linked engineer profile, assigned open
        tasks (most-critical first), and the decisions they own or must review."""
        return await client.get("/me/workspace")
