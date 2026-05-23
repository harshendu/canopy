"""Architecture tools: components, the system map, and ADR analysis."""

from __future__ import annotations


def register(mcp, client) -> None:
    @mcp.tool
    async def list_components(project_id: int) -> list[dict]:
        """List a project's architecture components (the system-map nodes)."""
        return await client.get("/architecture/components", params={"project_id": project_id})

    @mcp.tool
    async def create_component(
        project_id: int, name: str, kind: str = "service"
    ) -> dict:
        """Create an architecture component. kind: service|module|datastore|external|ui."""
        return await client.post(
            "/architecture/components",
            {"project_id": project_id, "name": name, "kind": kind},
        )

    @mcp.tool
    async def link_components(source_id: int, target_id: int, kind: str = "depends_on") -> dict:
        """Add a directed relationship between two components (system-map edge)."""
        return await client.post(
            "/architecture/component-links",
            {"source_id": source_id, "target_id": target_id, "kind": kind},
        )

    @mcp.tool
    async def import_adr(project_id: int, provider: str, connection_id: int, ref: str) -> dict:
        """Import an ADR from a markdown doc. provider: github (file path) | gdrive (file id)."""
        return await client.post(
            "/architecture/adrs/import",
            {
                "project_id": project_id,
                "provider": provider,
                "connection_id": connection_id,
                "ref": ref,
            },
        )

    @mcp.tool
    async def adr_impact(adr_id: int) -> dict:
        """Blast radius of an ADR: directly-affected components + everything depending on them."""
        return await client.get(f"/architecture/adrs/{adr_id}/impact")
