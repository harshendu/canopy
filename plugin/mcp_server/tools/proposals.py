"""Change-proposal tools + session orientation.

These are the plugin's **review-first write lane**: instead of mutating canopy directly,
a session stages a `propose_changes` batch (with per-item provenance — which Slack
thread / email / meeting / ticket the fact came from) and hands the human a review URL.
Applying is deliberately **not** exposed as a tool and the API endpoint is human-only,
so the change can only land when a person reviews and commits it in the canopy UI.

The review is a **conversation**, not a one-shot hand-off: while the human looks at the
proposal in the UI they can ask this session for changes ("push the pentest a week, drop
the vendor risk"). `revise_proposal` amends the open proposal in place — their page
updates live — and `preview_proposal` tells you what it does to the plan as a whole, so
you can answer "what does that do to the finish date?" before they click Apply.

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


def _compact_impact(preview: dict) -> dict:
    """The preview minus the two full Gantt payloads — everything needed to *narrate* the
    change (finish-date movement, which tasks are added / edited / pushed, apply-readiness)
    without flooding the context with every task row."""
    projects = []
    for project in preview.get("projects", []):
        slim = {k: v for k, v in project.items() if k not in ("current", "proposed")}
        slim["milestones"] = [
            m for m in project.get("milestones", []) if m.get("kind") != "unchanged"
        ]
        projects.append(slim)
    return {
        "can_apply": preview.get("can_apply"),
        "issues": preview.get("issues", []),
        "included": preview.get("included"),
        "excluded": preview.get("excluded"),
        "counts": preview.get("counts", {}),
        "projects": projects,
    }


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
          parent_id, constraint_start, deadline, assignee_engineer_id, tags, estimate_*;
          dependency: predecessor_id, successor_id, type, lag; blocker: task_id, reason,
          category, severity, needed_by; risk/outcome/doc_reference: their usual fields —
          scope defaults to the proposal's scope). Jira-mirrored task `status` is NOT
          stageable.
        - **Moving work in time:** a task's dates are *computed* by the scheduler from
          durations + dependencies, so to move it change `duration`, add a `dependency`,
          or set `constraint_start` ("start no earlier than", YYYY-MM-DD). Staging `start`
          has no lasting effect — the replan overwrites it.
        - People fields (`assignee_engineer_id`, `owner_engineer_id`, …) must be real
          engineer ids (`list_engineers`).
        - **Refs:** give a create item `"ref": "t1"`, then point later items at it with
          `parent_ref` / `predecessor_ref` / `successor_ref` / `task_ref` — so one proposal
          can stage "create phase → create tasks under it → wire dependencies".
        - **Provenance:** set `source_kind` (slack | email | calendar | meeting | jira |
          github | drive | document | chat), `source_label`, and `source_url` on every item
          you derived from an external source — the reviewer sees where each change came from.
        - `reason`: one line on *why* this change (shown beside the diff).

        Validation is strict (400 lists per-item errors — fix and restage). Returns the
        staged proposal (id, items) plus `review_url`. Follow up with `preview_proposal`
        to tell the user what the batch does to the plan (finish date, knock-on shifts),
        and use `revise_proposal` — not a second proposal — when they ask for changes.
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
        `before` snapshot, live `current` values, `stale` flag, per-item errors), the
        reviewer's `review_note`, the `review_url`, and `lookups` (display names for the
        ids the items mention — say "Dana Lee", not "engineer 14").

        It also shows what the **reviewer has done so far** in the UI: `excluded: true`
        items are ones they vetoed, and `overrides` are values they hand-edited (layered
        over your `payload`). Read this before revising so you build on their edits rather
        than fighting them. `revision` / `revision_note` track in-place revisions.

        Check this after staging to learn the human's verdict: `applied` (done — items carry
        `applied_entity_id`), `rejected` (read `review_note`, adjust, restage), or still
        `open` (remind the user where to review). There is deliberately no apply tool —
        committing a proposal happens in the canopy UI, by a person.
        """
        proposal = await client.get(f"/proposals/{proposal_id}")
        proposal["review_url"] = _review_url(proposal_id)
        return proposal

    @mcp.tool
    async def preview_proposal(proposal_id: int, include_plan: bool = False) -> dict:
        """What the plan looks like **before vs after** an open proposal — the same
        current/proposed picture the reviewer toggles in the UI, as data you can narrate.
        A pure simulation (nothing is written) that honours the reviewer's exclusions and
        inline edits, using the same scheduler an apply would.

        Returns, per affected project: `end_current` → `end_proposed` and
        `end_delta_days` (calendar days the finish moves), critical-path task counts,
        `task_changes` (each task `added` by the proposal, `edited` by an item, or
        `shifted` as a knock-on — with before/after dates and the `item_ids` behind it),
        changed `milestones`, `new_deadline_misses`, plus overall `counts` and
        `can_apply` / `issues` (whether Apply would succeed right now, and why not — e.g.
        an item depends on one the reviewer excluded, or a dependency cycle).

        Use it to answer "what does this do to my plan?" in plain language (lead with the
        finish date and the biggest pushes) and to check a revision landed as intended.
        Staged tasks that don't exist yet have negative ids. `include_plan=True` adds the
        full current and proposed Gantt (every task) — only when you need task-level detail.
        """
        preview = await client.get(f"/proposals/{proposal_id}/preview")
        result = preview if include_plan else _compact_impact(preview)
        result["review_url"] = _review_url(proposal_id)
        return result

    @mcp.tool
    async def revise_proposal(
        proposal_id: int,
        note: str,
        update_items: list[dict] | None = None,
        add_items: list[dict] | None = None,
        remove_item_ids: list[int] | None = None,
        title: str | None = None,
        summary: str | None = None,
    ) -> dict:
        """Amend an **open** proposal in place — the conversational half of a review. When
        the user is looking at a proposal in the canopy UI and asks for changes ("make the
        pentest 5 days", "drop the vendor risk", "also add a load test after it", "assign
        that to Dana"), call this instead of staging a new proposal: their open page
        updates live and flags what you changed. Still staging — nothing touches the live
        plan, and applying stays a human click in the UI.

        - `note` (required): one line on what this revision changed, in the user's terms —
          it is shown on their screen as the revision lands.
        - `update_items`: `[{"item_id": 12, "payload": {...}, "remove_fields": [...],
          "reason": ...}]`. `payload` is **merged** into the staged payload (pass only what
          changes); `remove_fields` drops keys; `reason` / `source_*` replace the item's.
          An item's entity type, action, and target can't change — remove it and add a
          new one.
        - `add_items`: new items, same shape as `propose_changes` items (refs to handles
          declared anywhere in the proposal work; order is fixed up for you).
        - `remove_item_ids`: drop items entirely. If something else points at a removed
          item's `ref`, remove or re-point that too in the same call.
        - `title` / `summary`: rewrite the header when the proposal's intent shifted.

        Get item ids from `get_proposal` first — and respect what the reviewer already
        did there: a value you rewrite replaces their inline edit of that same field, but
        their other edits and exclusions are kept. Only the proposal's author or a planner
        may revise. A revision that would introduce a validation problem is refused whole
        (400 with per-item errors by `item_id` / `add_index`) and changes nothing.

        Returns the revised proposal plus `impact` — the before/after plan summary
        (see `preview_proposal`) — so you can immediately tell the user what the change
        does, e.g. "Done — that pulls the finish back from Mar 12 to Mar 5."
        """
        body: dict = {"note": note}
        if update_items:
            body["update_items"] = update_items
        if add_items:
            body["add_items"] = add_items
        if remove_item_ids:
            body["remove_item_ids"] = remove_item_ids
        if title is not None:
            body["title"] = title
        if summary is not None:
            body["summary"] = summary
        proposal = await client.post(f"/proposals/{proposal_id}/revise", body)
        proposal["review_url"] = _review_url(proposal_id)
        try:
            preview = await client.get(f"/proposals/{proposal_id}/preview")
            proposal["impact"] = _compact_impact(preview)
        except httpx.HTTPStatusError:
            proposal["impact"] = None  # the revision landed; the impact read did not
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
        - `open_proposals`: staged changes already awaiting review (don't duplicate them —
          `revise_proposal` an open one instead of staging a near-copy).
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
