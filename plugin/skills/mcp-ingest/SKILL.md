---
name: mcp-ingest
description: Reads an external system (a work tracker such as Jira or Linear, or GitHub) with your own connectors and pushes the data into canopy idempotently, for connections whose reads or writes are MCP-managed (canopy doesn't call the provider API itself) or trackers canopy can't read directly. Use when an admin has set a provider's integration strategy to MCP, when "Sync now" is disabled or answers not_directly_readable, or to run a scheduled sync from your Claude account. Also records draft-plan items you create yourself back onto canopy.
---

# MCP-orchestrated ingest

When an admin sets a provider's **integration strategy** to MCP (see Connectors → admin
Integrations, USER_FLOWS §A8), canopy stops calling that provider's API: the reconciliation poll
and webhooks stand down, and the direct push paths are disabled. **You** become the integration
runtime — read the external system with your own tools, then push normalized data into canopy
here. The same lane keeps a tracker canopy can't read at all (`direct_read: false` in
`canopy:list_trackers`, e.g. a generic tracker) in sync. Every ingest is idempotent (keyed on
the external id), upsert-only (never deletes), and maps into the connection's bound project, so
a partial pull can't shrink canopy's state.

## When to use this
- `canopy:list_connections` shows a connection whose `read_strategy`/`write_strategy` is `mcp`
  (the UI badges it "MCP-managed" and disables "Sync now"), **or**
- the architect asks you to sync from the tracker/GitHub and the direct sync isn't available
  (`sync_project_tracking` answers `not_directly_readable`), **or**
- you're running on a schedule (see "Scheduled sync" below).

**Mirror, not judgment.** Ingest is the *verbatim* lane: it upserts what the external
system says, field for field, with no review step — that's safe because it carries no
interpretation. The moment you're **inferring** something (a blocker from a Slack thread,
a risk from an email, scope from meeting notes), that's not ingest — stage it as a change
proposal instead (`harvesting-signals` / `updating-canopy`), so a human reviews the
judgment before it lands.

## Ingest tracker items → tasks
1. `canopy:list_connections` → the tracker connection id; `canopy:get_project_tracking` shows
   which project it is bound to.
2. Read the items you need with your **own** tracker tools (Jira, Linear, … — what you can see).
3. Normalize each item and call `canopy:ingest_work_items(connection_id, items, project_id?)`:
   `{"external_id": "<the tracker's stable id>", "external_key": "PROJ-123", "summary": "...",
   "status": "In Progress", "status_category": "in_progress", "kind": "epic" | "item" |
   "subitem" (or "issue_type": "Story"), "parent_external_id": "<parent id or null>",
   "updated": "<the tracker's updated timestamp>", "assignee_name": "…", "estimate": 3}`.
   Send `status_category` (todo | in_progress | done | cancelled) when the tracker says — every
   metric reads it. Epics become summary tasks; children are parented via
   `parent_external_id`. Status is mirrored **read-only** (the tracker stays the owner).
   Re-ingesting updates, never duplicates; new tasks trigger a replan. Pass `project_id` when
   the connection feeds several projects.

## Ingest GitHub PRs → cache
`canopy:ingest_github_pull_requests(connection_id, pull_requests)` with
`{"number": 42, "title": "...", "state": "open", "url": "https://...", "author": "octocat",
"updated": "<timestamp>", "branch": "feat/SHOP-12-x"}`. Keyed on (repo, number); the repo comes
from the connection config. A PR is tied to the task whose key appears in its title or branch.

## Write-back: draft plan → tracker (when writes are MCP-managed)
If the tracker's **writes** are MCP-managed, finalising a draft plan can't write to it. Instead:
1. `canopy:get_draft_plan(plan_id)` to read the reviewed tasks.
2. Create the items in the tracker with your **own** tools (epics before stories).
3. `canopy:record_draft_push(plan_id, results)` with
   `[{"draft_task_id": 12, "provider": "jira", "external_id": "<id>", "external_key":
   "PROJ-123"}]` to stamp each task and flip the plan to `synced`. Idempotent — a re-run won't
   create duplicates.

## Alternative: file drop (no live read at all)
If reads are set to `file` (or the architect just has an export), the same ingest accepts a
**JSON or CSV** file instead of live data: upload it on `/connectors` → **Import file**, or have
the architect drop it into the configured shared folder (`<root>/<connection_id>/*.{json,csv}`,
local or S3) for canopy's poll to pick up. Same idempotent upsert, same normalized shape.

## Scheduled sync (from your Claude account)
The admin can run this on a schedule so canopy stays fresh without a server-side poll:
- Authenticate the MCP server with an **agent-scope token** (`POST /auth/agent-token`, see
  USER_FLOWS §A6) set as `CANOPY_API_TOKEN`. Ingest and record-push are internal two-way-door
  writes, so an agent token is allowed (the external read/write happens through your own
  connectors, outside canopy's bounded-agency gate).
- Drive it on an interval with `/loop` (e.g. `/loop 30m run the mcp-ingest skill for the
  tracker connection`) or a scheduled task on your Claude account. canopy does not schedule this itself.
