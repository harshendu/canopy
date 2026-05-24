"""Scenario-simulation tools: branch an initiative's plan, edit team/availability/scope/
milestones, compare every view against live, then apply.

A scenario is a durable, named what-if over a whole initiative. Creating one snapshots the
initiative's live planning data; edits stay in the scenario until `apply_scenario`, which writes
the changes back to canopy's planning layer and replans — it never writes to Jira. Use
`compare_scenario` to see the schedule/critical-path/scope deltas before applying.
"""

from __future__ import annotations


def register(mcp, client) -> None:
    @mcp.tool
    async def list_scenarios(initiative_id: int) -> list[dict]:
        """List the what-if scenarios saved for an initiative."""
        return await client.get(f"/initiatives/{initiative_id}/scenarios")

    @mcp.tool
    async def create_scenario(
        initiative_id: int, title: str, description: str | None = None
    ) -> dict:
        """Create a scenario, snapshotting the initiative's tasks, dependencies, milestones,
        allocations, and availability into an editable sandbox."""
        return await client.post(
            f"/initiatives/{initiative_id}/scenarios",
            {"title": title, "description": description},
        )

    @mcp.tool
    async def get_scenario(scenario_id: int) -> dict:
        """A scenario with its status and the counts of each entity it carries."""
        return await client.get(f"/scenarios/{scenario_id}")

    @mcp.tool
    async def add_scenario_task(
        scenario_id: int,
        project_id: int,
        name: str,
        task_type: str = "task",
        duration: int = 1,
        parent_id: int | None = None,
        deadline: str | None = None,
        assignee_engineer_id: int | None = None,
    ) -> dict:
        """Add a task to the scenario (does not touch live data). `project_id` is a live project
        in the initiative; `parent_id` is a scenario-task id (for WBS nesting)."""
        return await client.post(
            f"/scenarios/{scenario_id}/tasks",
            {
                "project_id": project_id,
                "name": name,
                "type": task_type,
                "duration": duration,
                "parent_id": parent_id,
                "deadline": deadline,
                "assignee_engineer_id": assignee_engineer_id,
            },
        )

    @mcp.tool
    async def update_scenario_task(
        scenario_task_id: int,
        name: str | None = None,
        duration: int | None = None,
        deadline: str | None = None,
        percent_complete: float | None = None,
        parent_id: int | None = None,
        assignee_engineer_id: int | None = None,
    ) -> dict:
        """Update a scenario task's planning fields (only the args you pass are changed)."""
        body: dict = {}
        for field, value in (
            ("name", name),
            ("duration", duration),
            ("deadline", deadline),
            ("percent_complete", percent_complete),
            ("parent_id", parent_id),
            ("assignee_engineer_id", assignee_engineer_id),
        ):
            if value is not None:
                body[field] = value
        return await client.patch(f"/scenario-tasks/{scenario_task_id}", body)

    @mcp.tool
    async def remove_scenario_task(scenario_task_id: int) -> dict:
        """Remove a task from the scenario (applying the scenario then deletes the live task)."""
        await client.delete(f"/scenario-tasks/{scenario_task_id}")
        return {"removed": scenario_task_id}

    @mcp.tool
    async def add_scenario_dependency(
        scenario_id: int,
        predecessor_id: int,
        successor_id: int,
        type: str = "FS",
        lag: int = 0,
    ) -> dict:
        """Add a dependency between two scenario tasks (type: FS | SS | FF | SF)."""
        return await client.post(
            f"/scenarios/{scenario_id}/dependencies",
            {"predecessor_id": predecessor_id, "successor_id": successor_id,
             "type": type, "lag": lag},
        )

    @mcp.tool
    async def set_scenario_availability(
        scenario_id: int,
        engineer_id: int,
        start_date: str,
        end_date: str,
        capacity_factor: float = 0.0,
        note: str | None = None,
    ) -> dict:
        """Add an availability window for an engineer in the scenario (PTO/ramp-up).
        capacity_factor 0..1 (0 = fully out); it scales the over-allocation ceiling."""
        return await client.post(
            f"/scenarios/{scenario_id}/availability",
            {"engineer_id": engineer_id, "start_date": start_date, "end_date": end_date,
             "capacity_factor": capacity_factor, "note": note},
        )

    @mcp.tool
    async def set_scenario_allocation(
        scenario_id: int,
        engineer_id: int,
        project_id: int | None = None,
        percent_allocation: float = 100.0,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict:
        """Add a capacity allocation for an engineer in the scenario (team-composition change)."""
        return await client.post(
            f"/scenarios/{scenario_id}/allocations",
            {"engineer_id": engineer_id, "project_id": project_id,
             "percent_allocation": percent_allocation,
             "start_date": start_date, "end_date": end_date},
        )

    @mcp.tool
    async def scenario_critical_path(scenario_id: int) -> dict:
        """The scenario's cross-project critical path + hand-offs (structural working days)."""
        return await client.get(f"/scenarios/{scenario_id}/critical-path")

    @mcp.tool
    async def scenario_capacity(scenario_id: int, project_id: int | None = None) -> dict:
        """The scenario's capacity heatmap (allocation demand vs availability per engineer-week)."""
        params = {"project_id": project_id} if project_id is not None else None
        return await client.get(f"/scenarios/{scenario_id}/capacity", params=params)

    @mcp.tool
    async def compare_scenario(scenario_id: int) -> dict:
        """The scenario-vs-live diff: counts changed, project-end and critical-path deltas, and
        any staleness conflicts. The highest-value read before deciding to apply."""
        return await client.get(f"/scenarios/{scenario_id}/compare")

    @mcp.tool
    async def apply_scenario(scenario_id: int, force: bool = False) -> dict:
        """Apply the scenario to canopy's live planning layer and replan the affected projects.

        Writes canopy tasks/dependencies/milestones/allocations/availability only — never Jira.
        If live data changed since the snapshot, the apply is rejected unless force=True.
        """
        return await client.post(f"/scenarios/{scenario_id}/apply", {"force": force})
