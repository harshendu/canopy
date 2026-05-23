"""Project / milestone / task creation tools."""

from __future__ import annotations


def register(mcp, client) -> None:
    @mcp.tool
    async def list_projects() -> list[dict]:
        """List all canopy projects (id, key, name, target date)."""
        return await client.get("/projects")

    @mcp.tool
    async def get_project(project_id: int) -> dict:
        """Get a single canopy project by its numeric id."""
        return await client.get(f"/projects/{project_id}")

    @mcp.tool
    async def create_project(
        key: str,
        name: str,
        description: str | None = None,
        start_date: str | None = None,
        target_date: str | None = None,
    ) -> dict:
        """Create a canopy project.

        `key` is a unique slug (e.g. "PLATFORM"); duplicates are rejected. `start_date` /
        `target_date` are YYYY-MM-DD and feed the schedule window. Returns the new project.
        """
        return await client.post(
            "/projects",
            {
                "key": key,
                "name": name,
                "description": description,
                "start_date": start_date,
                "target_date": target_date,
            },
        )

    @mcp.tool
    async def create_milestone(
        project_id: int, name: str, target_date: str | None = None
    ) -> dict:
        """Create a named milestone on a project. target_date is YYYY-MM-DD or null."""
        return await client.post(
            "/milestones",
            {"project_id": project_id, "name": name, "target_date": target_date},
        )

    @mcp.tool
    async def create_task(
        project_id: int,
        name: str,
        duration: int = 1,
        task_type: str = "task",
        parent_id: int | None = None,
    ) -> dict:
        """Create a task in a project's plan.

        task_type is one of "task", "milestone", or "summary" (a summary task acts
        as a phase/workstream parent in the work-breakdown structure).
        """
        return await client.post(
            "/tasks",
            {
                "project_id": project_id,
                "name": name,
                "duration": duration,
                "type": task_type,
                "parent_id": parent_id,
            },
        )
