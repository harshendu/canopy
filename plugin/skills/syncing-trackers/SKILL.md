---
name: syncing-trackers
description: Syncs epics, stories and their status from the project's work tracker (Jira, Linear, a generic tracker…) into canopy and reconciles the plan afterwards; binds a project to a tracker or switches it between native and mirrored tracking. Use when the architect wants to pull the latest from the tracker, refresh ticket status, import a backlog, link specific tickets to a project/initiative, bind or unbind a tracker, or reconcile canopy tasks with the tracker's board.
---

# Syncing from a work tracker

A project is tracked **natively** (canopy owns every status — the board is the truth) or
**mirrored** from a tracker (the tracker owns the items it knows and their **status**; canopy
mirrors them as tasks and **never writes status back**). Epics become summary tasks (phases);
stories/tasks/bugs become leaf tasks parented under their epic. Canopy-only work in a mirrored
project stays canopy-owned.

## Orient first
1. `canopy:get_workspace_context` → each project's `tracking_mode`, and `trackers` (what's
   enabled and what each supports). `canopy:list_trackers` has the full catalog.
2. `canopy:get_project_tracking(project_id)` → the project's binding (connection, scope such as
   a Jira project key, the tracker's statuses), what the tracker supports
   (`direct_read`, `create_items`, `webhooks`, `iterations`…) and who owns how many statuses.
   Only promise what the tracker's capabilities allow.

## Sync
- One project: `canopy:sync_project_tracking(project_id)` (incremental; `full=True` re-reads
  everything and refreshes the tracker's statuses — the mirrored board's columns).
- A whole connection (every project/initiative it feeds): `canopy:sync_tracker(connection_id,
  incremental=True)`.
- Both are idempotent (re-running never duplicates) and replan when tasks were created. Then
  review with `canopy:list_tasks` / `canopy:get_board` and fill in durations/dependencies (see
  `planning-roadmaps`).
- `409 not_directly_readable`: canopy doesn't read that tracker itself (its reads are MCP/file,
  or it is a generic tracker) — read it with your own tools and use the `mcp-ingest` skill.

## Link specific items (instead of the whole tracker project)
1. Pick the tracker `connection_id` (`canopy:list_connections`) and the target's id.
2. `canopy:link_tracker_item(root_key, target_type, target_id, connection_id)`:
   - `target_type="project"` maps the item **and its descendant subtree** into that project.
   - `target_type="initiative"` maps each descendant **epic → a project** under the initiative
     and its items → tasks.
3. `canopy:list_tracker_links` / `canopy:resync_tracker_link` / `canopy:unlink_tracker_item`
   (unlinking keeps what was mapped).

## Bind, unbind or switch a tracker (a human applies it)
`canopy:switch_project_tracking(project_id, to_mode, connection_id?, scope?, strategy?)` —
**preview first** (the default `dry_run=True`) and show the human the plan: per task `keep`,
`adopt` (matched to a tracker item), `publish` (created in the tracker), `release` (leaves the
old tracker; canopy owns its status) or `remap` (released into the native column of the same
category). Strategies for the work the project already has: `keep_separate` (default — it stays
canopy-only), `match` (adopt tasks whose key/title match an item), `publish` (create open tasks
in the tracker; they start in its first status). **Applying is human-only** — ask the human to
apply it in canopy (Tracking panel) or with their own session; an agent token gets 403. Adjust
an existing binding in place (scope, type mapping, sprint mirroring) with
`canopy:set_project_tracking`.

## Notes
- Status on a mirrored task is read-only in canopy: never `move_task` it to another column,
  never stage its status in a proposal, never write it with your own tracker tools *for tasks
  canopy mirrors* on the user's behalf.
- Webhooks push live changes; the periodic poll is the backstop; a nightly job tops up exact
  status history from the tracker's changelog. A manual sync is still useful before planning.
- A child whose parent hasn't synced yet is wired on the next sync.
- The `*_jira_*` tools (`trigger_jira_sync`, `link_jira_ticket`, …) are deprecated aliases kept
  for one release.
