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

    @mcp.tool
    async def get_adr(adr_id: int) -> dict:
        """Read a full ADR: its fields, comment thread, and stakeholder-review summary."""
        return await client.get(f"/architecture/adrs/{adr_id}")

    @mcp.tool
    async def propose_adr(
        project_id: int,
        title: str,
        proposed_by_id: int,
        context: str | None = None,
        decision: str | None = None,
        alternatives: list[str] | None = None,
        reversibility: str | None = None,
        stakeholder_ids: list[int] | None = None,
    ) -> dict:
        """Propose a decision (engineer flow): creates an ADR in `proposed` status.

        Use this when an engineer raises a decision for the owner to triage, rather than
        an architect recording an already-made one. `proposed_by_id` is the author.
        """
        return await client.post(
            "/architecture/adrs",
            {
                "project_id": project_id,
                "title": title,
                "proposed_by_id": proposed_by_id,
                "context": context,
                "decision": decision,
                "alternatives": alternatives or [],
                "reversibility": reversibility,
                "stakeholder_ids": stakeholder_ids or [],
                "status": "proposed",
            },
        )

    @mcp.tool
    async def transition_adr(adr_id: int, status: str, decide_by: str | None = None) -> dict:
        """Move an ADR through its lifecycle (e.g. under_discussion, accepted, deferred).

        Only legal transitions are allowed. `deferred` requires a `decide_by` date
        (YYYY-MM-DD). Returns the updated ADR.
        """
        body: dict = {"status": status}
        if decide_by is not None:
            body["decide_by"] = decide_by
        return await client.patch(f"/architecture/adrs/{adr_id}", body)

    @mcp.tool
    async def comment_adr(
        adr_id: int,
        body: str,
        kind: str = "comment",
        engineer_id: int | None = None,
        author_name: str | None = None,
    ) -> dict:
        """Add to an ADR's discussion thread.

        kind is comment|approve|request_changes|reject. A non-`comment` kind is a formal
        review action (counts toward the stakeholder-review summary). Pass `engineer_id`
        so the action is attributed to a stakeholder.
        """
        return await client.post(
            f"/architecture/adrs/{adr_id}/comments",
            {
                "body": body,
                "kind": kind,
                "engineer_id": engineer_id,
                "author_name": author_name,
            },
        )

    @mcp.tool
    async def decision_queue(project_id: int | None = None) -> dict:
        """The decision queue: ADRs needing attention (triage / stuck / deferred-due).

        Omit project_id for an org-wide view. Each item carries a bucket, a reason, and
        whether it's overdue — the architect's (and engineer's) morning surface.
        """
        params = {"project_id": project_id} if project_id is not None else None
        return await client.get("/decisions/queue", params=params)
