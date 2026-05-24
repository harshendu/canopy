---
name: syncing-jira
description: Syncs epics, stories, and their status from Jira into canopy and reconciles the plan afterward. Use when the architect wants to pull the latest from Jira, refresh ticket status, import a backlog, link specific Jira tickets to a project/initiative, or reconcile canopy tasks with the Jira board.
---

# Syncing from Jira

Jira is the source of truth for epics, stories, and ticket **status**. canopy mirrors
them as tasks and **never writes status back**. Epics become summary tasks (phases);
stories/tasks/bugs become leaf tasks parented under their epic.

## Workflow

1. **Find the Jira connection.** Call `canopy:list_connections` and pick the one with
   provider `jira`. Note its `connection_id`. (If none exists, the architect must add
   it in canopy's Connectors settings with base_url, email, API token, the canopy
   `project_id`, and the `jira_project_key`.)
2. **Sync.** Call `canopy:trigger_jira_sync`:
   - `incremental=True` (default) for a fast catch-up since the last watermark.
   - `incremental=False` for a full re-sync (first run, or after large backfills).
   It returns counts of created / updated / skipped issues. The sync is idempotent —
   re-running never duplicates tasks.
3. **Reconcile the plan.** New tasks arrive without dates. Run
   `canopy:replan_schedule` so they get scheduled and the critical path updates. Then
   review tasks with `canopy:list_tasks` and fill in durations/dependencies as needed
   (see the `planning-roadmaps` skill).

## Linking specific tickets (instead of the whole project)

When the architect wants only a *chosen* slice of Jira — a specific initiative, epic, or
story — rather than the whole project, link the ticket directly:

1. Pick the Jira `connection_id` (`canopy:list_connections`) and the target's id.
2. Call `canopy:link_jira_ticket(jira_key, target_type, target_id, connection_id)`:
   - `target_type="project"` maps the ticket **and its entire descendant subtree** into that
     project (epics → summary tasks, stories → leaf tasks, parented).
   - `target_type="initiative"` maps each descendant **epic → a Project** under the initiative
     and its stories → tasks (Jira initiative→epic→story onto canopy initiative→project→task).
   It returns counts of projects/tasks created. Re-linking is an idempotent update.
3. Inspect or refresh links with `canopy:list_jira_links` / `canopy:resync_jira_link`, and
   remove one with `canopy:unlink_jira_ticket` (mapped entities stay; they're canopy-owned).

Use a full `trigger_jira_sync` to mirror the whole Jira project; use `link_jira_ticket` to
pull just a chosen ticket tree into a specific target.

## Notes
- Status shown on canopy tasks mirrors Jira; treat it as read-only.
- Webhooks push live changes; the periodic reconciliation poll is the backstop. A
  manual sync is still useful right before planning or a review.
- If a story's epic hasn't synced yet, its parent link resolves on the next sync.
