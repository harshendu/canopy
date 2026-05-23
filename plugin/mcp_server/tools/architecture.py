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
    async def list_adrs(project_id: int | None = None) -> list[dict]:
        """List ADRs (architecture decisions), newest number first.

        Omit `project_id` for every project's decisions, or pass one to scope it. Each item
        carries its status, reversibility, owner, stakeholders, and affected component ids —
        use `get_adr` for the full body + discussion thread.
        """
        params = {"project_id": project_id} if project_id is not None else None
        return await client.get("/architecture/adrs", params=params)

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

    # --- Architecture drift ---
    @mcp.tool
    async def list_code_bindings(project_id: int) -> list[dict]:
        """List the code bindings (component → path glob + module prefix) for a project."""
        return await client.get("/architecture/code-bindings", params={"project_id": project_id})

    @mcp.tool
    async def add_code_binding(
        component_id: int,
        path_glob: str,
        module_prefix: str | None = None,
        connection_id: int | None = None,
        repo: str | None = None,
    ) -> dict:
        """Bind a component to where it lives in code (the linchpin for drift detection).

        `path_glob` e.g. "backend/app/services/**"; `module_prefix` e.g. "app.services" maps
        Python imports back to this component.
        """
        return await client.post(
            "/architecture/code-bindings",
            {
                "component_id": component_id,
                "path_glob": path_glob,
                "module_prefix": module_prefix,
                "connection_id": connection_id,
                "repo": repo,
            },
        )

    @mcp.tool
    async def get_drift(project_id: int) -> dict:
        """Get the project's drift score + queue (open + triaged drift events)."""
        return await client.get(f"/projects/{project_id}/drift")

    @mcp.tool
    async def scan_drift(
        project_id: int,
        actual_edges: list[list[int]],
        inactive_component_ids: list[int] | None = None,
        implicit_signals: list[dict] | None = None,
    ) -> dict:
        """Report what the code actually shows; the server runs drift detection and updates
        the queue.

        `actual_edges` are observed component-to-component dependencies as [source_id,
        target_id] pairs (map imports to components via their module prefixes).
        `inactive_component_ids` are components with no recent commits (for unimplemented-ADR
        detection). `implicit_signals` are dicts like {"kind": "new_dependency", "summary":
        "...", "suspected_cause": "PR #42", "component_id": 3} for architectural changes with
        no ADR. Returns the refreshed drift score + queue.
        """
        return await client.post(
            f"/projects/{project_id}/drift/scan",
            {
                "actual_edges": actual_edges,
                "inactive_component_ids": inactive_component_ids or [],
                "implicit_signals": implicit_signals or [],
            },
        )

    @mcp.tool
    async def reconcile_drift(project_id: int, event_id: int, action: str) -> dict:
        """Triage a drift event. action: accepted (auto-propose an ADR) | rejected (open a
        revert task) | false_positive (suppress this rule on future scans)."""
        return await client.post(
            f"/projects/{project_id}/drift/{event_id}/reconcile", {"action": action}
        )
