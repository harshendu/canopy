"""Scheduling / dependency / architecture-decision tools."""

from __future__ import annotations


def register(mcp, client) -> None:
    @mcp.tool
    async def list_tasks(project_id: int) -> list[dict]:
        """List all tasks for a project, including computed schedule and critical-path flags."""
        return await client.get("/tasks", params={"project_id": project_id})

    @mcp.tool
    async def link_dependency(
        predecessor_id: int,
        successor_id: int,
        dep_type: str = "FS",
        lag: int = 0,
    ) -> dict:
        """Create a dependency between two tasks.

        dep_type is one of FS (finish-to-start, default), SS, FF, SF. `lag` is in days.
        """
        return await client.post(
            "/dependencies",
            {
                "predecessor_id": predecessor_id,
                "successor_id": successor_id,
                "type": dep_type,
                "lag": lag,
            },
        )

    @mcp.tool
    async def replan_schedule(project_id: int) -> dict:
        """Recompute the project schedule (critical path method) and persist dates.

        Returns the number of scheduled tasks, the critical-path task ids, and the
        computed project end date. Call this after changing tasks or dependencies.
        """
        return await client.post(f"/projects/{project_id}/replan")

    @mcp.tool
    async def get_gantt(project_id: int) -> dict:
        """Get the Gantt model for a project (tasks with dates + dependency links)."""
        return await client.get(f"/projects/{project_id}/gantt")

    @mcp.tool
    async def whatif_schedule(project_id: int, duration_overrides: dict[int, int]) -> dict:
        """Project a schedule with hypothetical task durations (working days) WITHOUT persisting.

        duration_overrides maps task_id -> duration. Returns projected end date, critical path,
        and deadline violations — useful for "what if we add an engineer / cut scope" analysis.
        """
        return await client.post(
            f"/projects/{project_id}/whatif", {"duration_overrides": duration_overrides}
        )

    @mcp.tool
    async def set_baseline(project_id: int) -> dict:
        """Snapshot the current schedule as the baseline (for plan-vs-actual drift)."""
        return await client.post(f"/projects/{project_id}/baseline")

    @mcp.tool
    async def get_burndown(project_id: int) -> dict:
        """Get the weekly burndown (remaining vs completed) for a project."""
        return await client.get(f"/projects/{project_id}/burndown")

    @mcp.tool
    async def list_alerts(project_id: int) -> dict:
        """Get the project's alerts digest: deadline misses, overdue milestones, over-allocations."""
        return await client.get(f"/projects/{project_id}/alerts")

    @mcp.tool
    async def create_adr(
        project_id: int,
        title: str,
        context: str | None = None,
        decision: str | None = None,
        consequences: str | None = None,
    ) -> dict:
        """Record an Architecture Decision Record (ADR) on a project.

        The ADR number is assigned automatically. Status defaults to "proposed".
        """
        return await client.post(
            "/architecture/adrs",
            {
                "project_id": project_id,
                "title": title,
                "context": context,
                "decision": decision,
                "consequences": consequences,
            },
        )
