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
        initiative_id: int | None = None,
        start_date: str | None = None,
        target_date: str | None = None,
    ) -> dict:
        """Create a canopy project.

        `key` is a unique slug (e.g. "PLATFORM"); duplicates are rejected. `initiative_id` links
        it under a program/initiative (see `list_initiatives`). `start_date` / `target_date` are
        YYYY-MM-DD and feed the schedule window. Returns the new project.
        """
        return await client.post(
            "/projects",
            {
                "key": key,
                "name": name,
                "description": description,
                "initiative_id": initiative_id,
                "start_date": start_date,
                "target_date": target_date,
            },
        )

    @mcp.tool
    async def list_initiatives() -> list[dict]:
        """List initiatives (the program layer above projects): id, key, name, outcome, dates."""
        return await client.get("/initiatives")

    @mcp.tool
    async def create_initiative(
        key: str,
        name: str,
        outcome_statement: str | None = None,
        start_date: str | None = None,
        target_date: str | None = None,
        owner_engineer_id: int | None = None,
    ) -> dict:
        """Create an initiative — a program spanning multiple projects executed concurrently.

        `key` is a unique slug; `outcome_statement` is the outcome + how you'll know it worked.
        Link projects to it with `set_project_initiative` (or `create_project(initiative_id=...)`).
        """
        return await client.post(
            "/initiatives",
            {
                "key": key,
                "name": name,
                "outcome_statement": outcome_statement,
                "start_date": start_date,
                "target_date": target_date,
                "owner_engineer_id": owner_engineer_id,
            },
        )

    @mcp.tool
    async def get_initiative_rollup(initiative_id: int) -> dict:
        """Roll up an initiative's health across its sub-projects.

        Returns each sub-project's summary plus aggregates: total/completed tasks, latest end
        date, the riskiest sub-project's risk score/level, worst drift, the open-decision
        backlog, and whether the latest end is on track for the initiative's target date.
        """
        return await client.get(f"/initiatives/{initiative_id}/rollup")

    @mcp.tool
    async def get_initiative_digest(initiative_id: int) -> dict:
        """A manage-by-exception weekly digest for an initiative: a `headline`, the `attention`
        list (what's off-track / blocked / awaiting a decision), status (progress, forecast P85,
        risk, drift, open blockers/decisions), outcomes, and a ready-to-send `markdown` rendering.

        Use this as the spine of the `daily-standup` skill / a weekly leadership update — it leads
        with exceptions (green is silent). Delivery to Slack/email is a hook over this output."""
        return await client.get(f"/initiatives/{initiative_id}/digest")

    @mcp.tool
    async def set_project_initiative(project_id: int, initiative_id: int | None = None) -> dict:
        """Link a project to an initiative (pass initiative_id=null to unlink)."""
        return await client.patch(f"/projects/{project_id}", {"initiative_id": initiative_id})

    @mcp.tool
    async def get_initiative_critical_path(initiative_id: int) -> dict:
        """The critical path across an initiative's sub-projects (in working days).

        Returns the critical chain of tasks (each tagged with its project), the total
        working-day length, whether it `spans_projects`, and the cross-project **hand-offs**
        on it — the between-team dependencies most likely to slip the initiative. Add such a
        hand-off with `link_dependency` between tasks in two projects of the same initiative.
        """
        return await client.get(f"/initiatives/{initiative_id}/critical-path")

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
