"""Spec-driven development tools: capture intent + acceptance criteria, link the work, and
self-audit each criterion against the implementation."""

from __future__ import annotations


def register(mcp, client) -> None:
    @mcp.tool
    async def list_specs(project_id: int | None = None, status: str | None = None) -> list[dict]:
        """List specs. Filter by project_id and/or status (draft | approved | in_progress |
        verified | archived)."""
        params: dict = {}
        if project_id is not None:
            params["project_id"] = project_id
        if status:
            params["status"] = status
        return await client.get("/specs", params=params or None)

    @mcp.tool
    async def create_spec(
        project_id: int,
        title: str,
        problem: str,
        context: str | None = None,
        out_of_scope: str | None = None,
        source_url: str | None = None,
        adr_id: int | None = None,
        owner_engineer_id: int | None = None,
    ) -> dict:
        """Create a spec — intent as the source of truth for a slice of work. `problem` states
        what/why; add explicit, checkable acceptance criteria with add_spec_criterion. Link the
        governing decision via adr_id and the PRD/design via source_url (the doc graph holds the
        richer link set)."""
        return await client.post(
            "/specs",
            {
                "project_id": project_id,
                "title": title,
                "problem": problem,
                "context": context,
                "out_of_scope": out_of_scope,
                "source_url": source_url,
                "adr_id": adr_id,
                "owner_engineer_id": owner_engineer_id,
            },
        )

    @mcp.tool
    async def get_spec(spec_id: int) -> dict:
        """The self-audit bundle for a spec: its acceptance criteria, the tasks implementing it
        (Task.spec_id), and computed readiness (criteria_met / criteria_total, acceptance_ratio).
        Read this to judge each criterion against the implementation, then record verdicts with
        update_spec_criterion."""
        return await client.get(f"/specs/{spec_id}")

    @mcp.tool
    async def set_spec_status(spec_id: int, status: str) -> dict:
        """Set a spec's status: draft | approved | in_progress | verified | archived. Mark
        `verified` only once every acceptance criterion is met."""
        return await client.patch(f"/specs/{spec_id}", {"status": status})

    @mcp.tool
    async def add_spec_criterion(
        spec_id: int, text: str, verification: str | None = None, sort_order: int = 0
    ) -> dict:
        """Add one acceptance criterion to a spec — a single checkable statement of done.
        `verification` optionally notes how it will be checked (a test, a fitness function, a demo)."""
        return await client.post(
            f"/specs/{spec_id}/criteria",
            {"text": text, "verification": verification, "sort_order": sort_order},
        )

    @mcp.tool
    async def update_spec_criterion(
        criterion_id: int,
        status: str | None = None,
        text: str | None = None,
        verification: str | None = None,
    ) -> dict:
        """Record the self-audit verdict for one criterion. status: open | met | unmet | waived.
        Add a short `verification` note saying how you checked it (test name, fitness function,
        observed behavior)."""
        payload: dict = {}
        if status is not None:
            payload["status"] = status
        if text is not None:
            payload["text"] = text
        if verification is not None:
            payload["verification"] = verification
        return await client.patch(f"/criteria/{criterion_id}", payload)

    @mcp.tool
    async def link_task_to_spec(task_id: int, spec_id: int) -> dict:
        """Link a task to the spec it implements (intent → work traceability). Sets Task.spec_id
        so the spec's self-audit can see the implementing work."""
        return await client.patch(f"/tasks/{task_id}", {"spec_id": spec_id})
