"""Document-graph tools: link (don't store) PRDs/designs/tech-design/architecture docs,
set up the AI-driven epic→doc field mapping, harvest, and report coverage."""

from __future__ import annotations


def register(mcp, client) -> None:
    @mcp.tool
    async def sample_epic_doc_fields(connection_id: int, limit: int = 5) -> dict:
        """Fetch a sample of Jira epics' URL-bearing fields + remote links so you can propose
        a field→kind mapping for the doc graph.

        This is step 1 of the one-time, AI-driven setup. Inspect the returned `distinct_fields`
        (each has a field_id, its human field_name, and sample urls) and the per-epic
        `field_candidates` / `description_urls` / `remote_links`. Infer each field's doc kind
        from its name and URL domain (e.g. figma.com → design, a "PRD" field → prd, a repo
        ARCHITECTURE.md → architecture), then confirm the mapping with the admin before saving
        it via set_epic_doc_field_mapping.
        """
        return await client.get(
            f"/connectors/jira/{connection_id}/doc-fields/sample", params={"limit": limit}
        )

    @mcp.tool
    async def get_epic_doc_field_mapping(connection_id: int) -> dict:
        """The doc field mapping currently configured on a Jira connection."""
        return await client.get(f"/connectors/jira/{connection_id}/doc-field-mapping")

    @mcp.tool
    async def set_epic_doc_field_mapping(
        connection_id: int,
        mappings: list[dict],
        parse_description_links: bool = False,
        parse_remote_links: bool = True,
    ) -> dict:
        """Save the admin-confirmed epic→doc field mapping on a Jira connection.

        `mappings` is a list of {"jira_field": "customfield_10042", "field_name": "Design Link",
        "doc_kind": "design"}. doc_kind ∈ prd | design | tech_design | architecture | release |
        qa | runbook | other. Set parse_remote_links to harvest Jira remote links (Confluence /
        web) as `other`, and parse_description_links to sweep links in the epic description.
        """
        return await client.post(
            f"/connectors/jira/{connection_id}/doc-field-mapping",
            {
                "mappings": mappings,
                "parse_description_links": parse_description_links,
                "parse_remote_links": parse_remote_links,
            },
        )

    @mcp.tool
    async def harvest_epic_docs(connection_id: int) -> dict:
        """Harvest doc links from every synced epic and attach each to the canopy entity it
        maps to (a summary task, or a project for an initiative-linked epic). Idempotent —
        re-running updates rather than duplicates. Returns created/updated/skipped counts."""
        return await client.post(f"/connectors/jira/{connection_id}/harvest-docs")

    @mcp.tool
    async def list_doc_references(
        scope_level: str, scope_id: int, kind: str | None = None
    ) -> list[dict]:
        """Document references on an entity. scope_level: project | initiative | task.
        Optionally filter by kind (prd | design | tech_design | architecture | …)."""
        params: dict = {"scope_level": scope_level, "scope_id": scope_id}
        if kind:
            params["kind"] = kind
        return await client.get("/docs", params=params)

    @mcp.tool
    async def add_doc_reference(
        scope_level: str,
        scope_id: int,
        url: str,
        kind: str = "other",
        title: str | None = None,
        owner_engineer_id: int | None = None,
    ) -> dict:
        """Link a document to a canopy entity by URL (canopy stores the link, never the file).
        scope_level: project | initiative | task. kind: prd | design | tech_design |
        architecture | release | qa | runbook | other."""
        return await client.post(
            "/docs",
            {
                "scope_level": scope_level,
                "scope_id": scope_id,
                "url": url,
                "kind": kind,
                "title": title,
                "owner_engineer_id": owner_engineer_id,
            },
        )

    @mcp.tool
    async def get_doc_coverage(scope_level: str, scope_id: int) -> dict:
        """Doc coverage for an entity: which expected kinds (prd/design/tech_design/
        architecture) are present vs missing, rolled up across child projects/tasks. A missing
        kind is a signal (absence of a doc is not neutral). scope_level: project | initiative |
        task."""
        return await client.get(
            "/docs/coverage", params={"scope_level": scope_level, "scope_id": scope_id}
        )
