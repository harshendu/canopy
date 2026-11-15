"""Scheduling / dependency / architecture-decision tools, plus the board (moves, workflows)."""

from __future__ import annotations

import httpx


async def _refusal(exc: httpx.HTTPStatusError) -> dict:
    """A refused board write as data (owner, url, limit...) instead of an opaque failure."""
    try:
        detail = exc.response.json().get("detail")
    except ValueError:
        detail = exc.response.text
    return {"ok": False, "status_code": exc.response.status_code, "error": detail}


def register(mcp, client) -> None:
    @mcp.tool
    async def list_tasks(project_id: int) -> list[dict]:
        """List all tasks for a project, including computed schedule and critical-path flags."""
        return await client.get("/tasks", params={"project_id": project_id})

    @mcp.tool
    async def update_task(
        task_id: int,
        name: str | None = None,
        duration: int | None = None,
        start: str | None = None,
        end: str | None = None,
        deadline: str | None = None,
        percent_complete: float | None = None,
        parent_id: int | None = None,
    ) -> dict:
        """Update a task's planning fields (only the arguments you pass are changed).

        `duration` is working days; `start`/`end`/`deadline` are YYYY-MM-DD; `percent_complete`
        is 0-100 (the progress an engineer reports); `parent_id` moves it under a summary task.
        Run `replan_schedule` afterward if you changed duration / structure. Task **status** is
        not settable here — a status change is a board move (`move_task`), and only for tasks
        canopy owns (`status_owner == "canopy"`); a mirrored task's status belongs to its tracker.
        """
        body: dict = {}
        for field, value in (
            ("name", name),
            ("duration", duration),
            ("start", start),
            ("end", end),
            ("deadline", deadline),
            ("percent_complete", percent_complete),
            ("parent_id", parent_id),
        ):
            if value is not None:
                body[field] = value
        return await client.patch(f"/tasks/{task_id}", body)

    @mcp.tool
    async def assign_task(task_id: int, engineer_id: int | None = None) -> dict:
        """Assign a task to an engineer (pass engineer_id=null to unassign).

        `engineer_id` is a team Engineer id (see `list_engineers`). Assignment powers the
        engineer's /me workspace and the per-engineer capacity view.
        """
        return await client.patch(f"/tasks/{task_id}", {"assignee_engineer_id": engineer_id})

    @mcp.tool
    async def raise_blocker(
        task_id: int,
        reason: str,
        blocking_task_id: int | None = None,
        raised_by_engineer_id: int | None = None,
        category: str | None = None,
        severity: str | None = None,
        owner_engineer_id: int | None = None,
        needed_by: str | None = None,
    ) -> dict:
        """Flag a blocker (impediment) on a task — the leading signal that work has stalled.

        `blocking_task_id` optionally names the task that must finish first. `raised_by_engineer_id`
        defaults to the calling user's engineer. Open blockers show in the engineer workspace and
        the project alerts digest.

        For PM triage: `category` is dependency|resource|decision|external|technical; `severity`
        is low|medium|high|critical (high/critical escalate the digest alert to an error);
        `owner_engineer_id` is who must clear it; `needed_by` is the YYYY-MM-DD date it's needed by.
        """
        return await client.post(
            f"/tasks/{task_id}/blockers",
            {
                "reason": reason,
                "blocking_task_id": blocking_task_id,
                "raised_by_engineer_id": raised_by_engineer_id,
                "category": category,
                "severity": severity,
                "owner_engineer_id": owner_engineer_id,
                "needed_by": needed_by,
            },
        )

    @mcp.tool
    async def list_blockers(project_id: int | None = None, open_only: bool = True) -> list[dict]:
        """List blockers, newest first. Scope to a project and/or to open (unresolved) ones."""
        params: dict = {"open_only": open_only}
        if project_id is not None:
            params["project_id"] = project_id
        return await client.get("/blockers", params=params)

    @mcp.tool
    async def resolve_blocker(blocker_id: int, resolved: bool = True) -> dict:
        """Resolve a blocker (or reopen it with resolved=false)."""
        return await client.patch(f"/blockers/{blocker_id}", {"resolved": resolved})

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
    async def set_baseline(project_id: int, note: str | None = None) -> dict:
        """Snapshot the current schedule as the baseline (the plan-of-record for schedule
        variance). Re-baselining is a deliberate, logged act — pass a `note` saying why the
        plan was reset. Returns the logged baseline event."""
        return await client.post(f"/projects/{project_id}/baseline", {"note": note})

    @mcp.tool
    async def get_burndown(project_id: int) -> dict:
        """Get the weekly burndown (remaining vs completed) for a project."""
        return await client.get(f"/projects/{project_id}/burndown")

    @mcp.tool
    async def get_board(
        project_id: int | None = None, team_id: int | None = None, sprint: str | None = None
    ) -> dict:
        """Get the Kanban board — for a project, or for a team (one board over every project the
        team runs, on the team's columns). Columns in order (empty ones included) with WIP per
        column against its limit, cards in rank order, the cycle-time P85 and which open cards
        are **aging** (in their status longer than P85 — the leading 'this is stuck' signal).
        Each card says who owns its status (`status_owner`: "canopy" or a tracker) and whether
        it is `movable`; `mode` is native|mirrored and `delivery_method` kanban|sprint|both.
        `sprint` narrows it to active | backlog | all | a sprint id. Manage flow by finishing
        aging/high-WIP work before starting more. Agent work: a card's `delegation` ("agent"
        when a person delegated it to the work queue), `claim` (the session working it: role,
        since, heartbeat age), `gate` (what a person must decide; `parked` when canopy stopped
        offering it), and each lane's `worked_by` role."""
        params = {"sprint": sprint} if sprint else None
        if team_id is not None:
            return await client.get(f"/teams/{team_id}/board", params=params)
        return await client.get(f"/projects/{project_id}/board", params=params)

    @mcp.tool
    async def move_task(
        task_id: int,
        to_status: str | None = None,
        after_task_id: int | None = None,
        before_task_id: int | None = None,
        position: str = "bottom",
        expected_status: str | None = None,
    ) -> dict:
        """Move a card on the board: change its status and/or its place in the column.

        `to_status` must be a column of the project's workflow (see `get_workflow`); omit it to
        only reorder. Only canopy-owned tasks change status here — for a task mirrored from a
        tracker the result names the owner and the item's URL (`status_externally_owned`): change
        it in that tracker, never by any other route. Place the card between `after_task_id` and
        `before_task_id`, else at the `position` ("top" | "bottom") end of the column.
        `expected_status` refuses the move if someone changed the card meanwhile.

        Use it for an explicit instruction ("move CHK-12 to In Review"). A status you *inferred*
        from a signal (Slack, a meeting) goes through `propose_changes` instead, for a human to
        review. Every move is recorded in the task's status history (burndown, cycle time).
        Returns {task, changed, warnings} — `wip_limit_exceeded` means the column is now over its
        limit; under `block` enforcement the move is refused instead.

        A **delegated** card (`delegation: "agent"`) moves through the agent work queue: on an
        agent token this returns `use_work_claim` — claim it (`claim_work`) and hand off with
        `submit_work`, and canopy moves it.
        """
        body: dict = {"position": position}
        for field, value in (
            ("to_status", to_status),
            ("after_task_id", after_task_id),
            ("before_task_id", before_task_id),
            ("expected_status", expected_status),
        ):
            if value is not None:
                body[field] = value
        try:
            return await client.post(f"/tasks/{task_id}/move", body)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (403, 409, 422):
                return await _refusal(exc)
            raise

    @mcp.tool
    async def get_workflow(project_id: int | None = None, team_id: int | None = None) -> dict:
        """The board's columns (status, category todo|in_progress|done|cancelled, WIP limit) for
        a project or a team — pass exactly one. `scope` says where they are defined (project |
        team | template | default); `inherited` means the project/team uses its team's or the
        workspace's columns."""
        if team_id is not None:
            return await client.get(f"/teams/{team_id}/workflow")
        return await client.get(f"/projects/{project_id}/workflow")

    @mcp.tool
    async def set_workflow(
        columns: list[dict],
        project_id: int | None = None,
        team_id: int | None = None,
        name: str = "Default",
        wip_enforcement: str = "warn",
        move_tasks_to: dict | None = None,
    ) -> dict:
        """Replace a team's board columns (shared by all its projects) or one project's override
        — pass exactly one of team_id / project_id.

        `columns` is an ordered list of {name, category, wip_limit?, previous_name?}: category is
        todo|in_progress|done|cancelled (at least one todo and one done column); set
        `previous_name` to rename a column (its tasks follow). Removing a column that still holds
        tasks needs `move_tasks_to` ({"Old": "New"}) — those tasks move with a recorded
        transition. `wip_enforcement` is off|warn|block. Team columns: the team's directors and
        managers; a project override: its planners.
        """
        body = {
            "name": name,
            "wip_enforcement": wip_enforcement,
            "columns": columns,
            "move_tasks_to": move_tasks_to or {},
        }
        path = f"/teams/{team_id}/workflow" if team_id is not None else (
            f"/projects/{project_id}/workflow"
        )
        try:
            return await client.put(path, body)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (403, 409, 422):
                return await _refusal(exc)
            raise

    @mcp.tool
    async def get_forecast(
        project_id: int | None = None, initiative_id: int | None = None
    ) -> dict:
        """Probabilistic (Monte-Carlo) completion forecast — pass exactly one of project_id /
        initiative_id.

        Simulates finishing the remaining items by sampling the team's historical weekly
        throughput, returning P50 / P85 completion dates (the honest answer for knowledge work,
        next to the deterministic CPM date). If `sufficient` is false there isn't enough
        completed-work history yet — see `reason`.
        """
        if initiative_id is not None:
            return await client.get(f"/initiatives/{initiative_id}/forecast")
        return await client.get(f"/projects/{project_id}/forecast")

    @mcp.tool
    async def list_alerts(project_id: int) -> dict:
        """Get the project's alerts digest: deadline misses, overdue milestones, over-allocations."""
        return await client.get(f"/projects/{project_id}/alerts")

    @mcp.tool
    async def get_risk(project_id: int) -> dict:
        """Get the project's leading-indicator risk score + drillable breakdown.

        Returns a 0-100 score, a `confidence` flag (high|low), and families (schedule /
        capacity / architecture / quality), each with indicators (summary, score, drill-down
        details) and the open mitigations. Architecture risk includes deferred decisions past
        decide-by and ADRs stuck in discussion. Quality risk is fed by observability events
        (build failures / open incidents); when none are wired, the quality family scores the
        missing **observability coverage** and `confidence` is "low" — a blind project is not
        treated as safer, just less certain.
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
