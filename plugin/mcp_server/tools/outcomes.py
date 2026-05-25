"""Outcome tools: outcomes over output — a project/initiative as a measurable bet."""

from __future__ import annotations


def register(mcp, client) -> None:
    @mcp.tool
    async def list_outcomes(
        scope_level: str, scope_id: int, status: str | None = None
    ) -> list[dict]:
        """Outcomes on a project/initiative. scope_level: project | initiative. Optionally filter
        by status (pending | on_track | at_risk | validated | invalidated). Each carries
        baseline/target/current + a computed progress_ratio."""
        params: dict = {"scope_level": scope_level, "scope_id": scope_id}
        if status:
            params["status"] = status
        return await client.get("/outcomes", params=params)

    @mcp.tool
    async def add_outcome(
        scope_level: str,
        scope_id: int,
        statement: str,
        metric: str | None = None,
        unit: str | None = None,
        baseline_value: float | None = None,
        target_value: float | None = None,
        target_date: str | None = None,
        owner_engineer_id: int | None = None,
    ) -> dict:
        """Define an outcome — the *bet* a project/initiative is making. `statement` is the
        hypothesis ("we believe X will yield Y"); `metric` is how you'll know; set
        baseline/target (+ unit) so progress is measurable. scope_level: project | initiative."""
        return await client.post(
            "/outcomes",
            {
                "scope_level": scope_level,
                "scope_id": scope_id,
                "statement": statement,
                "metric": metric,
                "unit": unit,
                "baseline_value": baseline_value,
                "target_value": target_value,
                "target_date": target_date,
                "owner_engineer_id": owner_engineer_id,
            },
        )

    @mcp.tool
    async def update_outcome(
        outcome_id: int,
        current_value: float | None = None,
        status: str | None = None,
        target_value: float | None = None,
        statement: str | None = None,
        metric: str | None = None,
    ) -> dict:
        """Record progress on an outcome — set the observed `current_value` and/or move the
        `status` (pending | on_track | at_risk | validated | invalidated). Mark `validated` /
        `invalidated` once the bet has resolved (this is what a retro evaluates)."""
        payload: dict = {}
        for key, value in (
            ("current_value", current_value),
            ("status", status),
            ("target_value", target_value),
            ("statement", statement),
            ("metric", metric),
        ):
            if value is not None:
                payload[key] = value
        return await client.patch(f"/outcomes/{outcome_id}", payload)
