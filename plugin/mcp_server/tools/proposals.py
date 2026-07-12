"""Change-proposal tools + session orientation.

These are the plugin's **review-first write lane**: instead of mutating canopy directly,
a session stages a `propose_changes` batch (with per-item provenance — which Slack
thread / email / meeting / ticket the fact came from) and hands the human a review URL.
Applying is deliberately **not** exposed as a tool and the API endpoint is human-only,
so the change can only land when a person reviews and commits it in the canopy UI.

`get_workspace_context` is the orientation verb every canopy session should start with:
who am I, what's my persona (function) and token scope, which projects/initiatives exist,
what's already awaiting review, and where the dashboard lives.
"""

from __future__ import annotations

import os

import httpx


def _dashboard_base() -> str:
    """Where the canopy React dashboard lives (for review links shown to the user).

    CANOPY_DASHBOARD_URL wins; otherwise fall back to the API origin (correct in
    production, where one origin serves both the app and /api)."""
    base = (
        os.environ.get("CANOPY_DASHBOARD_URL")
        or os.environ.get("CANOPY_API_BASE_URL")
        or "http://localhost:8000"
    )
    return base.rstrip("/")


def _review_url(proposal_id: int | None = None) -> str:
    return f"{_dashboard_base()}/reviews" + (f"/{proposal_id}" if proposal_id else "")


def register(mcp, client) -> None:
    @mcp.tool
    async def propose_changes(
        scope_level: str,
        scope_id: int,
        title: str,
        items: list[dict],
        summary: str | None = None,
        origin: str | None = None,
    ) -> dict:
        """Stage a batch of canopy changes for **human review** — the default way to write
        anything you inferred (from Slack/email/meetings/Jira/GitHub/docs) rather than were
        explicitly told, and for any multi-entity or schedule-shaping edit. Nothing touches
        the live plan until a person applies it in the canopy UI; always show the returned
        `review_url` to the user.

        `scope_level` is "project" or "initiative"; every item must stay inside that scope.
        Each item: `{"entity_type": ..., "action": ..., "payload": {...}}` plus optional
        `entity_id` (required for update/resolve), `ref`, `reason`, `source_kind`,
        `source_label`, `source_url`.

        - `entity_type`: task | dependency | milestone | blocker | risk | outcome |
          decision | doc_reference. `action`: create | update | resolve (blockers only).
        - Payload fields mirror the create/update APIs (task: name, duration, type,
          parent_id, start, deadline, assignee_engineer_id, tags, estimate_*; dependency:
          predecessor_id, successor_id, type, lag; blocker: task_id, reason, category,
          severity, needed_by; risk/outcome/doc_reference: their usual fields — scope
          defaults to the proposal's scope). Jira-mirrored task `status` is NOT stageable.
        - **Refs:** give a create item `"ref": "t1"`, then point later items at it with
          `parent_ref` / `predecessor_ref` / `successor_ref` / `task_ref` — so one proposal
          can stage "create phase → create tasks under it → wire dependencies".
        - **Provenance:** set `source_kind` (slack | email | calendar | meeting | jira |
          github | drive | document | chat), `source_label`, and `source_url` on every item
          you derived from an external source — the reviewer sees where each change came from.
        - `reason`: one line on *why* this change (shown beside the diff).

        Validation is strict (400 lists per-item errors — fix and restage). Returns the
        staged proposal (id, items) plus `review_url`.
        """
        proposal = await client.post(
            "/proposals",
            {
                "scope_level": scope_level,
                "scope_id": scope_id,
                "title": title,
                "summary": summary,
                "origin": origin or "claude-session",
                "items": items,
            },
        )
        proposal["review_url"] = _review_url(proposal.get("id"))
        return proposal

    @mcp.tool
    async def list_proposals(
        scope_level: str | None = None,
        scope_id: int | None = None,
        status: str | None = None,
    ) -> list[dict]:
        """List change proposals, newest first (filter by scope and/or status:
        open | applied | rejected | withdrawn). Use status="open" to see what still awaits
        human review; a `rejected` proposal's `review_note` says why — read it before
        restaging."""
        params: dict = {}
        if scope_level is not None:
            params["scope_level"] = scope_level
        if scope_id is not None:
            params["scope_id"] = scope_id
        if status is not None:
            params["status"] = status
        rows = await client.get("/proposals", params=params or None)
        for row in rows:
            row["review_url"] = _review_url(row.get("id"))
        return rows

    @mcp.tool
    async def get_proposal(proposal_id: int) -> dict:
        """A proposal's full review state: status, items (payload, provenance, stage-time
        `before` snapshot, live `current` values, `stale` flag, reviewer exclusions,
        per-item errors), the reviewer's `review_note`, and the `review_url`.

        Check this after staging to learn the human's verdict: `applied` (done — items carry
        `applied_entity_id`), `rejected` (read `review_note`, adjust, restage), or still
        `open` (remind the user where to review). There is deliberately no apply tool —
        committing a proposal happens in the canopy UI, by a person.
        """
        proposal = await client.get(f"/proposals/{proposal_id}")
        proposal["review_url"] = _review_url(proposal_id)
        return proposal

    @mcp.tool
    async def withdraw_proposal(proposal_id: int) -> dict:
        """Withdraw an open proposal you staged (e.g. it was superseded or you found an
        error). Only the author or a planner may withdraw; applied/rejected proposals are
        immutable history."""
        return await client.post(f"/proposals/{proposal_id}/withdraw")

    @mcp.tool
    async def get_workspace_context() -> dict:
        """Orient a canopy session — **call this first** in any session that reads or
        writes canopy. Returns:

        - `user` + `function` (their cross-functional persona: engineering | product |
          design | architecture | management | leadership — adapt your altitude to it) and
          `role` (what they may write).
        - `token_scope`: "agent" means this session runs on a bounded token — it can stage
          proposals and do reversible work, but one-way-door/external-write actions
          (applying proposals, accepting one-way-door ADRs, push-to-Jira, applying
          scenarios) will 403; route them through the human in the UI.
        - `features`: the admin's feature-gate map (skip surfaces that are off).
        - `initiatives` + `projects`: the portfolio to anchor ids against.
        - `open_proposals`: staged changes already awaiting review (don't duplicate them).
        - `dashboard_url` / `reviews_url`: where to send the user to look and to commit.
        """
        context: dict = {
            "dashboard_url": _dashboard_base(),
            "reviews_url": _review_url(),
        }
        session = await client.get("/auth/session")
        context["user"] = session.get("user")
        context["token_scope"] = session.get("scope", "full")
        features = await client.get("/features")
        context["features"] = features.get("features", features)
        context["projects"] = [
            {
                "id": p.get("id"),
                "key": p.get("key"),
                "name": p.get("name"),
                "initiative_id": p.get("initiative_id"),
                "health": p.get("health"),
                "target_date": p.get("target_date"),
            }
            for p in await client.get("/projects")
        ]
        try:
            context["initiatives"] = [
                {
                    "id": i.get("id"),
                    "key": i.get("key"),
                    "name": i.get("name"),
                    "health": i.get("health"),
                    "target_date": i.get("target_date"),
                }
                for i in await client.get("/initiatives")
            ]
        except httpx.HTTPStatusError:
            context["initiatives"] = []  # portfolio.initiatives gated off
        try:
            open_rows = await client.get("/proposals", params={"status": "open"})
            context["open_proposals"] = [
                {
                    "id": r.get("id"),
                    "title": r.get("title"),
                    "scope_label": r.get("scope_label"),
                    "item_count": r.get("item_count"),
                    "review_url": _review_url(r.get("id")),
                }
                for r in open_rows
            ]
        except httpx.HTTPStatusError:
            context["open_proposals"] = []  # ai.proposals gated off
        return context
