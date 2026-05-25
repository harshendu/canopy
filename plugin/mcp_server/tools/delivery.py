"""Delivery-metrics tool: DORA + flow at project or initiative scope (team-level only)."""

from __future__ import annotations


def register(mcp, client) -> None:
    @mcp.tool
    async def get_delivery_metrics(
        project_id: int | None = None,
        initiative_id: int | None = None,
        weeks: int = 12,
    ) -> dict:
        """DORA + flow delivery metrics over the last `weeks` (default 12, max 52). Pass
        `initiative_id` for the program-wide rollup or `project_id` for one project.

        Returns DORA (deploy frequency, change-fail rate, failed-deployment recovery time) from
        the activity feed, and flow (throughput, cycle time median/P85, WIP, aging WIP) from task
        status history — plus `notes` explaining proxies and any insufficient-data caveats. These
        are **team-level by design**; there is deliberately no per-engineer breakdown."""
        if initiative_id is not None:
            return await client.get(
                f"/initiatives/{initiative_id}/delivery", params={"weeks": weeks}
            )
        if project_id is not None:
            return await client.get(f"/projects/{project_id}/delivery", params={"weeks": weeks})
        raise ValueError("Provide either project_id or initiative_id")
