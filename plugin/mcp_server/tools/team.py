"""Team & capacity tools."""

from __future__ import annotations


def register(mcp, client) -> None:
    @mcp.tool
    async def list_engineers() -> list[dict]:
        """List engineers on the team (id, name, title, role)."""
        return await client.get("/team/engineers")

    @mcp.tool
    async def add_engineer(name: str, title: str | None = None) -> dict:
        """Add an engineer to the team."""
        return await client.post("/team/engineers", {"name": name, "title": title})

    @mcp.tool
    async def get_capacity(project_id: int) -> dict:
        """Get the weekly capacity grid (engineer × week allocation %) for a project."""
        return await client.get("/team/capacity", params={"project_id": project_id})
