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
    async def get_risk(project_id: int) -> dict:
        """Get the project's leading-indicator risk score + drillable breakdown.

        Returns a 0-100 score and families (schedule / capacity / architecture / quality),
        each with indicators (summary, score, drill-down details) and the open mitigations.
        Architecture risk includes deferred decisions past decide-by and ADRs stuck in
        discussion (see the decisions tools). Quality risk is not yet wired.
        """
        return await client.get(f"/projects/{project_id}/risk")

    @mcp.tool
    async def log_risk_mitigation(
        project_id: int,
        indicator_key: str,
        note: str,
        owner_engineer_id: int | None = None,
        check_in: str | None = None,
    ) -> dict:
        """Acknowledge a risk indicator with a mitigation note, owner, and check-in date.

        `indicator_key` is one from `get_risk` (e.g. deadline_violations, over_allocation,
        deferred_overdue, stuck_decisions). `check_in` is YYYY-MM-DD.
        """
        return await client.post(
            f"/projects/{project_id}/risk/mitigations",
            {
                "indicator_key": indicator_key,
                "note": note,
                "owner_engineer_id": owner_engineer_id,
                "check_in": check_in,
            },
        )

    @mcp.tool
    async def list_retrospectives(project_id: int) -> list[dict]:
        """List a project's retrospectives and incident postmortems."""
        return await client.get(f"/projects/{project_id}/retrospectives")

    @mcp.tool
    async def create_retrospective(
        project_id: int, kind: str = "project_retro", title: str | None = None
    ) -> dict:
        """Open a retrospective (kind=project_retro auto-seeds its body from project state:
        milestones, schedule variance, drift, ADR churn) or an incident_postmortem."""
        return await client.post(
            f"/projects/{project_id}/retrospectives", {"kind": kind, "title": title}
        )

    @mcp.tool
    async def comment_retrospective(project_id: int, retro_id: int, body: str) -> dict:
        """Add a comment to a retrospective / postmortem thread."""
        return await client.post(
            f"/projects/{project_id}/retrospectives/{retro_id}/comments", {"body": body}
        )

    @mcp.tool
    async def retrospective_follow_up(
        project_id: int, retro_id: int, action: str, title: str
    ) -> dict:
        """Mint a follow-up from a retrospective. action: task (open a task) | adr (propose
        an ADR linked to the retro's affected components)."""
        return await client.post(
            f"/projects/{project_id}/retrospectives/{retro_id}/follow-up",
            {"action": action, "title": title},
        )

    @mcp.tool
    async def create_adr(
        project_id: int,
        title: str,
        context: str | None = None,
        decision: str | None = None,
        consequences: str | None = None,
        alternatives: list[str] | None = None,
        reversibility: str | None = None,
        decision_owner_id: int | None = None,
        stakeholder_ids: list[int] | None = None,
        status: str = "proposed",
    ) -> dict:
        """Record an Architecture Decision Record (ADR) on a project.

        The ADR number is assigned automatically. `reversibility` is one_way|two_way
        (one_way = hard to reverse). `stakeholder_ids` are engineers who must review.
        Status lifecycle: proposed -> under_discussion -> accepted|rejected ->
        superseded|deprecated, plus `deferred` (needs a decide_by date via update_adr).
        """
        return await client.post(
            "/architecture/adrs",
            {
                "project_id": project_id,
                "title": title,
                "context": context,
                "decision": decision,
                "consequences": consequences,
                "alternatives": alternatives or [],
                "reversibility": reversibility,
                "decision_owner_id": decision_owner_id,
                "stakeholder_ids": stakeholder_ids or [],
                "status": status,
            },
        )
