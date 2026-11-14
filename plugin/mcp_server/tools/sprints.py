"""Delivery methods + sprints: how a team runs its work (kanban | sprint | both) and, for sprint
teams, planning / running / measuring sprints (USER_FLOWS §C11)."""

from __future__ import annotations

import httpx


async def _refusal(exc: httpx.HTTPStatusError) -> dict:
    try:
        detail = exc.response.json().get("detail")
    except ValueError:
        detail = exc.response.text
    return {"ok": False, "status_code": exc.response.status_code, "error": detail}


def register(mcp, client) -> None:
    async def _call(coro) -> dict | list:
        try:
            return await coro
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (403, 404, 409, 422):
                return await _refusal(exc)
            raise

    @mcp.tool
    async def get_team_delivery(team_id: int) -> dict:
        """How a team runs its work across ALL its projects: `delivery_method` kanban | sprint |
        both (`effective_method` is kanban while the sprints feature is off), sprint length,
        estimate unit (points | days | count), the active sprint, and whether the caller may
        change it (`can_manage`). Check this before planning sprints or reading velocity."""
        return await client.get(f"/teams/{team_id}/delivery")

    @mcp.tool
    async def set_team_delivery(
        team_id: int,
        delivery_method: str | None = None,
        sprint_length_days: int | None = None,
        estimate_unit: str | None = None,
    ) -> dict:
        """Choose how a team runs its work (applies to every project of the team): kanban
        (continuous flow, WIP limits, cycle time), sprint (time boxes, sprint planning,
        velocity) or both. The team's directors/managers only. Switching to kanban needs the
        active sprint completed; past sprints stay as history. Only the arguments passed change."""
        body: dict = {}
        for field, value in (
            ("delivery_method", delivery_method),
            ("sprint_length_days", sprint_length_days),
            ("estimate_unit", estimate_unit),
        ):
            if value is not None:
                body[field] = value
        return await _call(client.put(f"/teams/{team_id}/delivery", body))

    @mcp.tool
    async def list_sprints(team_id: int, state: str | None = None) -> list | dict:
        """A team's sprints — active first, then planned, then completed — each with its dates,
        state, owner ("canopy" or the tracker it is mirrored from: then read-only), commitment
        and live counts. `state` filters: planned | active | completed."""
        params = {"state": state} if state else None
        return await _call(client.get(f"/teams/{team_id}/sprints", params=params))

    @mcp.tool
    async def get_sprint(sprint_id: int, include_report: bool = False) -> dict:
        """A sprint with its tasks and the planning view: open estimate vs the team's capacity
        (person-days from allocations/PTO) and mean velocity — `over_capacity` warns, it never
        blocks. With `include_report`, adds the sprint report: daily burndown vs ideal, scope
        added/removed, completed vs committed (reliability) and carry-over."""
        detail = await _call(client.get(f"/sprints/{sprint_id}"))
        if include_report and isinstance(detail, dict) and detail.get("ok") is not False:
            detail["report"] = await _call(client.get(f"/sprints/{sprint_id}/report"))
        return detail

    @mcp.tool
    async def plan_sprint(
        team_id: int | None = None,
        sprint_id: int | None = None,
        add_task_ids: list[int] | None = None,
        remove_task_ids: list[int] | None = None,
        name: str | None = None,
        goal: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict:
        """Create a sprint (pass team_id, no sprint_id — dates default to the day after the last
        sprint, for the team's length) and/or change a sprint's membership: add tasks from the
        team's projects (each leaves any previous sprint) or remove them back to the backlog.
        Every move is recorded (commitment, scope change, carry-over). Use it for an explicit
        instruction; a sprint change you *inferred* goes through `propose_changes` (task
        `sprint_id`). Tasks whose sprint is set by a tracker are refused."""
        if sprint_id is None:
            if team_id is None:
                return {"ok": False, "error": "pass team_id to create a sprint, or sprint_id"}
            body: dict = {}
            for field, value in (
                ("name", name),
                ("goal", goal),
                ("start_date", start_date),
                ("end_date", end_date),
            ):
                if value is not None:
                    body[field] = value
            created = await _call(client.post(f"/teams/{team_id}/sprints", body))
            if not isinstance(created, dict) or created.get("ok") is False:
                return created if isinstance(created, dict) else {"result": created}
            sprint_id = int(created["id"])
        elif any(v is not None for v in (name, goal, start_date, end_date)):
            patch: dict = {}
            for field, value in (
                ("name", name),
                ("goal", goal),
                ("start_date", start_date),
                ("end_date", end_date),
            ):
                if value is not None:
                    patch[field] = value
            await _call(client.patch(f"/sprints/{sprint_id}", patch))
        if add_task_ids:
            added = await _call(
                client.post(f"/sprints/{sprint_id}/tasks", {"task_ids": add_task_ids})
            )
            if isinstance(added, dict) and added.get("ok") is False:
                return added
        for task_id in remove_task_ids or []:
            removed = await _call(client.delete(f"/sprints/{sprint_id}/tasks/{task_id}"))
            if isinstance(removed, dict) and removed.get("ok") is False:
                return removed
        return await _call(client.get(f"/sprints/{sprint_id}"))

    @mcp.tool
    async def start_sprint(sprint_id: int) -> dict:
        """Start a planned sprint: it becomes active and its commitment is captured. One active
        sprint per team (per pod for pod-scoped sprints)."""
        return await _call(client.post(f"/sprints/{sprint_id}/start"))

    @mcp.tool
    async def complete_sprint(
        sprint_id: int, carry_over: str = "backlog", next_sprint_id: int | None = None
    ) -> dict:
        """Complete the active sprint: capture what was done, then send each unfinished task to
        the backlog (carry_over="backlog") or into `next_sprint_id` (carry_over="next")."""
        body: dict = {"carry_over": carry_over}
        if next_sprint_id is not None:
            body["next_sprint_id"] = next_sprint_id
        return await _call(client.post(f"/sprints/{sprint_id}/complete", body))

    @mcp.tool
    async def get_velocity(team_id: int) -> dict:
        """A team's velocity: completed estimate per completed sprint (mean and range over the
        last six), commitment reliability (completed ÷ committed), and the P50/P85 number of
        sprints to finish its open work. Team-level only — never per engineer. Needs 3
        completed sprints (`sufficient`)."""
        return await _call(client.get(f"/teams/{team_id}/velocity"))
