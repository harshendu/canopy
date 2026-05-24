"""Delivery-metadata tools: 3-point estimates, tags, project/initiative health, and the
human risk register (RAID). These let Claude enrich the plan the way a PM / eng-leader would.

The risk register is kept **separate** from the computed risk score (`get_risk`): these are
qualitative risks an architect records by hand. 3-point estimates are **advisory** — they never
move a task's scheduling `duration`; their spread surfaces as a schedule-risk uncertainty signal.
"""

from __future__ import annotations

_SCOPE_PATHS = {"task": "/tasks", "project": "/projects", "initiative": "/initiatives"}


def register(mcp, client) -> None:
    def _path(scope: str, entity_id: int) -> str:
        base = _SCOPE_PATHS.get(scope)
        if base is None:
            raise ValueError("scope must be one of: task | project | initiative")
        return f"{base}/{entity_id}"

    @mcp.tool
    async def set_task_estimates(
        task_id: int,
        optimistic: int | None = None,
        likely: int | None = None,
        pessimistic: int | None = None,
    ) -> dict:
        """Set a task's 3-point (PERT) estimate in working days — advisory metadata.

        `optimistic` (aggressive), `likely` (practical), `pessimistic` (buffered). This does NOT
        change the task's scheduling `duration`; a wide optimistic→pessimistic spread instead
        raises the schedule-risk 'estimate uncertainty' indicator. Only the args you pass change.
        """
        body: dict = {}
        for field, value in (
            ("estimate_optimistic", optimistic),
            ("estimate_likely", likely),
            ("estimate_pessimistic", pessimistic),
        ):
            if value is not None:
                body[field] = value
        return await client.patch(f"/tasks/{task_id}", body)

    @mcp.tool
    async def set_tags(scope: str, id: int, tags: list[str]) -> dict:
        """Replace the tags on a task | project | initiative (normalised: lowercased, deduped).

        `scope` is "task", "project", or "initiative"; `id` is that entity's id. Pass the full
        desired tag list — use `add_tags`/`remove_tags` to change a few without replacing all.
        """
        return await client.patch(_path(scope, id), {"tags": tags})

    @mcp.tool
    async def add_tags(scope: str, id: int, tags: list[str]) -> dict:
        """Add tags to a task | project | initiative without dropping the existing ones."""
        current = await client.get(_path(scope, id))
        merged = list(current.get("tags", [])) + list(tags)
        return await client.patch(_path(scope, id), {"tags": merged})

    @mcp.tool
    async def remove_tags(scope: str, id: int, tags: list[str]) -> dict:
        """Remove tags from a task | project | initiative (matching is case-insensitive)."""
        drop = {t.strip().lower() for t in tags}
        current = await client.get(_path(scope, id))
        kept = [t for t in current.get("tags", []) if t not in drop]
        return await client.patch(_path(scope, id), {"tags": kept})

    @mcp.tool
    async def set_project_health(
        project_id: int, health: str, status_note: str | None = None
    ) -> dict:
        """Set a project's manual health (on_track | at_risk | off_track) and weekly status note.

        This is the architect's narrative status — it sits alongside (and can override the read
        of) the computed risk score. Stamps the update time.
        """
        body: dict = {"health": health}
        if status_note is not None:
            body["status_note"] = status_note
        return await client.patch(f"/projects/{project_id}", body)

    @mcp.tool
    async def set_initiative_health(
        initiative_id: int, health: str, status_note: str | None = None
    ) -> dict:
        """Set an initiative's manual health (on_track | at_risk | off_track) and status note."""
        body: dict = {"health": health}
        if status_note is not None:
            body["status_note"] = status_note
        return await client.patch(f"/initiatives/{initiative_id}", body)

    @mcp.tool
    async def list_risks(
        scope: str | None = None, scope_id: int | None = None, status: str | None = None
    ) -> list[dict]:
        """List risk-register (RAID) entries, newest first; each carries a computed exposure.

        Filter by `scope` (task|project|initiative) + `scope_id`, and/or `status`
        (open|mitigating|accepted|resolved|occurred). This is the human risk register — distinct
        from the computed risk score in `get_risk`.
        """
        params: dict = {}
        if scope is not None:
            params["scope_level"] = scope
        if scope_id is not None:
            params["scope_id"] = scope_id
        if status is not None:
            params["status"] = status
        return await client.get("/risks", params=params or None)

    @mcp.tool
    async def add_risk(
        scope: str,
        scope_id: int,
        title: str,
        category: str = "technical",
        probability: str = "medium",
        impact: str = "medium",
        description: str | None = None,
        owner_engineer_id: int | None = None,
        mitigation: str | None = None,
        contingency: str | None = None,
        target_resolution_date: str | None = None,
    ) -> dict:
        """Log a risk in the register, hung off a task | project | initiative.

        `category`: schedule|scope|technical|resource|external|quality|security. `probability`
        and `impact`: low|medium|high (exposure = probability x impact). `mitigation` is the plan
        to lower probability; `contingency` is the plan if it occurs; `target_resolution_date` is
        YYYY-MM-DD. These are proposals the architect should confirm.
        """
        return await client.post(
            "/risks",
            {
                "scope_level": scope,
                "scope_id": scope_id,
                "title": title,
                "category": category,
                "probability": probability,
                "impact": impact,
                "description": description,
                "owner_engineer_id": owner_engineer_id,
                "mitigation": mitigation,
                "contingency": contingency,
                "target_resolution_date": target_resolution_date,
            },
        )

    @mcp.tool
    async def update_risk(
        risk_id: int,
        title: str | None = None,
        category: str | None = None,
        probability: str | None = None,
        impact: str | None = None,
        status: str | None = None,
        owner_engineer_id: int | None = None,
        mitigation: str | None = None,
        contingency: str | None = None,
        target_resolution_date: str | None = None,
        description: str | None = None,
    ) -> dict:
        """Update a register risk (only the args you pass change). `status` open|mitigating|
        accepted|resolved|occurred; terminal statuses stamp the resolution time."""
        body: dict = {}
        for field, value in (
            ("title", title),
            ("category", category),
            ("probability", probability),
            ("impact", impact),
            ("status", status),
            ("owner_engineer_id", owner_engineer_id),
            ("mitigation", mitigation),
            ("contingency", contingency),
            ("target_resolution_date", target_resolution_date),
            ("description", description),
        ):
            if value is not None:
                body[field] = value
        return await client.patch(f"/risks/{risk_id}", body)

    @mcp.tool
    async def close_risk(risk_id: int, status: str = "resolved", note: str | None = None) -> dict:
        """Close a register risk to a terminal state: resolved | accepted | occurred.

        `occurred` means the risk materialised (it became a real issue). An optional `note` is
        appended to the risk's mitigation narrative as the resolution.
        """
        return await client.post(f"/risks/{risk_id}/close", {"status": status, "note": note})
