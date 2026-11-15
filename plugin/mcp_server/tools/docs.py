"""Document-graph + design-doc tools: link (don't store) Claude docs and artifacts, PRDs,
designs, tech designs and architecture docs; register what a session makes, link it to the
work it serves, promote personal docs; set up the AI-driven epic→doc field mapping, harvest,
and report coverage (USER_FLOWS §V).

Canopy never receives a document's content. When a tool takes `content` it is only hashed
here, inside the MCP server process, and canopy gets the SHA-256 digest."""

from __future__ import annotations

import hashlib


def _digest(content: str | None) -> str | None:
    """SHA-256 of exported content, computed locally — the content itself is never sent."""
    if not content:
        return None
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


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
        "doc_kind": "design"}. doc_kind is any kind from the catalog (`list_doc_kinds`) — a
        new one joins the catalog under stage `other`. Set parse_remote_links to harvest Jira
        remote links (Confluence / web) as `other`, and parse_description_links to sweep links
        in the epic description.
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
        """Deprecated alias of `list_design_docs` (kept one release). Document references on
        an entity — docs filed there and docs linked to it. scope_level: project | initiative |
        task."""
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
        visibility: str = "unknown",
    ) -> dict:
        """Deprecated alias of `register_design_doc` (kept one release): link a document to a
        canopy entity by URL as a plain, untracked link. kind is any kind. A Claude link needs
        visibility users | org | public (it must be shared in Claude first)."""
        return await client.post(
            "/docs",
            {
                "scope_level": scope_level,
                "scope_id": scope_id,
                "url": url,
                "kind": kind,
                "title": title,
                "owner_engineer_id": owner_engineer_id,
                "visibility": visibility,
            },
        )

    @mcp.tool
    async def register_design_doc(
        url: str,
        title: str,
        kind: str,
        summary: str | None = None,
        format: str | None = None,
        version: str | None = None,
        visibility: str = "unknown",
        scope_level: str | None = None,
        scope_id: int | None = None,
        personal: bool = False,
        links: list[dict] | None = None,
        content: str | None = None,
        content_hash: str | None = None,
        supersedes_id: int | None = None,
        track: bool = True,
    ) -> dict:
        """Track a design doc — a Claude Doc, an artifact (page, prototype, diagram, image
        page), or any other doc — in canopy, right after it is published for tracked work.

        Canopy stores the link, its identity at the source, kind, format, version and a short
        summary — **never the content**. Idempotent per document: registering the same artifact
        again (any spelling of its link) returns the existing record with `created: false` and
        adds any `links`.

        - `kind`: any kind (`list_doc_kinds` shows the catalog; prefer an existing one — prd,
          design, tech_design, architecture, rfc, research, qa, release, runbook, …).
        - `format`: document | page | prototype | diagram | image | deck | canvas | sheet.
        - `summary`: two plain sentences; it is shown to everyone who can see the doc in canopy,
          so leave it empty for anything sensitive.
        - `visibility`: who can open it in Claude — owner | users | org | public. A shared doc
          (the default) of a Claude link must be users/org/public or this returns 409
          `doc_not_shared`: ask the user to share it in Claude, or register it `personal=True`.
        - `scope_level` + `scope_id`: the doc's home (project | initiative | task); required
          unless `personal`.
        - `links`: [{"entity_type": "decision", "entity_id": 7, "relation": "basis"}, …] —
          entity_type project | initiative | task | decision | spec | milestone | outcome |
          risk | retro | component; relation basis (pins the version) | gate | reference.
        - `content`: optional exported text to hash locally; only the SHA-256 is sent.
        - `track`: start the review lifecycle at draft (false = a plain link).
        """
        body: dict = {
            "url": url,
            "title": title,
            "kind": kind,
            "summary": summary,
            "format": format,
            "version": version,
            "visibility": visibility,
            "scope_level": scope_level,
            "scope_id": scope_id,
            "personal": personal,
            "links": links or [],
            "content_hash": content_hash or _digest(content),
            "supersedes_id": supersedes_id,
            "track": track,
        }
        return await client.post("/docs/register", body)

    @mcp.tool
    async def link_design_doc(
        doc_id: int,
        entity_type: str,
        entity_id: int,
        relation: str = "reference",
        pinned_version: str | None = None,
    ) -> dict:
        """Link a tracked doc to the work it serves. entity_type: project | initiative | task |
        decision | spec | milestone | outcome | risk | retro | component. relation: `basis`
        (the entity was derived from / decided on this doc — pins its current version, and a
        later version raises an alert), `gate` (the entity should not complete until the doc
        is approved), `reference` (context). Idempotent per doc + entity. You may link only to
        work the user may edit (a contributor: their own tasks)."""
        return await client.post(
            f"/docs/{doc_id}/links",
            {
                "entity_type": entity_type,
                "entity_id": entity_id,
                "relation": relation,
                "pinned_version": pinned_version,
            },
        )

    @mcp.tool
    async def promote_design_doc(
        doc_id: int, scope_level: str, scope_id: int, visibility: str | None = None
    ) -> dict:
        """Share a personal doc with the team: file it under a home (project | initiative |
        task). A Claude doc must already be shared in Claude — pass its new `visibility`
        (users | org | public) once the user has shared it, else 409 `doc_not_shared`."""
        return await client.post(
            f"/docs/{doc_id}/promote",
            {"scope_level": scope_level, "scope_id": scope_id, "visibility": visibility},
        )

    @mcp.tool
    async def get_design_doc(doc_id: int) -> dict:
        """One tracked doc with its links (relation + pinned version), kind, stage, status and
        version. Personal docs are visible only to their owner."""
        return await client.get(f"/docs/{doc_id}")

    @mcp.tool
    async def list_design_docs(
        scope_level: str | None = None,
        scope_id: int | None = None,
        entity_type: str | None = None,
        entity_id: int | None = None,
        kind: str | None = None,
        stage: str | None = None,
        provider: str | None = None,
        review_status: str | None = None,
        personal: bool | None = None,
    ) -> list[dict]:
        """Design docs you may see, newest first. A scope (project | initiative | task) returns
        docs filed there and docs linked to it; `entity_type`+`entity_id` returns docs linked
        to any entity (an ADR, a spec…). Filters: kind, stage (frame | define | design |
        decide | plan | build | release | learn | other), provider (claude | gdrive | github |
        figma | confluence | jira | web), review_status (draft | in_review | approved |
        superseded | archived | untracked), personal=true for your own private docs."""
        params: dict = {}
        for name, value in (
            ("scope_level", scope_level), ("scope_id", scope_id), ("entity_type", entity_type),
            ("entity_id", entity_id), ("kind", kind), ("stage", stage), ("provider", provider),
            ("review_status", review_status),
        ):
            if value is not None:
                params[name] = value
        if personal is not None:
            params["personal"] = str(personal).lower()
        return await client.get("/docs", params=params)

    @mcp.tool
    async def record_design_doc_version(
        doc_id: int,
        version: str | None = None,
        content: str | None = None,
        content_hash: str | None = None,
        change_summary: str | None = None,
        reachable: bool = True,
        visibility: str | None = None,
    ) -> dict:
        """Record what you saw when you opened a tracked doc — after every republish, and on
        each check. Pass the source's `version` label (a page artifact's published version, a
        Claude Doc's revision, a commit); a new label is appended to the version log. Pass the
        exported text as `content` to fingerprint it — it is hashed here, only the SHA-256 is
        sent. `reachable=False` records that the link no longer opens (flags it broken).
        `visibility` reports its sharing level in Claude (owner | users | org | public) — a
        shared doc made private is flagged. Every call stamps `last_checked_at`. Returns
        `new_version` and the doc with its health flags."""
        return await client.post(
            f"/docs/{doc_id}/revisions",
            {
                "version": version,
                "content_hash": content_hash or _digest(content),
                "change_summary": change_summary,
                "reachable": reachable,
                "visibility": visibility,
            },
        )

    @mcp.tool
    async def request_design_doc_review(doc_id: int, version: str | None = None) -> dict:
        """Put a version of a shared doc up for review (draft → in_review; or approved →
        in_review after a material change). The doc's planners see it under /me and approve it
        in the canopy UI — approval is a human act you cannot take. A Claude doc must be shared
        in Claude (409 `doc_not_shared`); a personal doc has no review (409 `doc_personal`)."""
        return await client.post(f"/docs/{doc_id}/request-review", {"version": version})

    @mcp.tool
    async def get_doc_worklist(project_id: int | None = None, limit: int = 50) -> dict:
        """Docs a session should open and re-check: Claude docs never opened since they were
        registered, and tracked docs not re-checked within the check window — oldest first.
        Open each one you can, then `record_design_doc_version` (or `reachable=False`)."""
        params: dict = {"limit": limit}
        if project_id is not None:
            params["project_id"] = project_id
        return await client.get("/docs/worklist", params=params)

    @mcp.tool
    async def list_doc_kinds() -> list[dict]:
        """The workspace's document-kind catalog: key, label, lifecycle stage, whether coverage
        expects it, and how many docs use it. Any kind is allowed — pick an existing key before
        inventing one (a new kind joins under stage `other`)."""
        return await client.get("/docs/kinds")

    @mcp.tool
    async def get_doc_coverage(scope_level: str, scope_id: int) -> dict:
        """Doc coverage for an entity: which expected kinds (from the catalog) are present vs
        missing, each expected kind's best review state (approved | in_review | draft | linked
        | missing), and counts by kind and lifecycle stage — rolled up across child
        projects/tasks and the docs linked there. A missing kind is a signal (absence of a doc
        is not neutral). scope_level: project | initiative | task."""
        return await client.get(
            "/docs/coverage", params={"scope_level": scope_level, "scope_id": scope_id}
        )
