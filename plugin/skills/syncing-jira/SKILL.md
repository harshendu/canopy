---
name: syncing-jira
description: Syncs epics, stories, and their status from Jira into canopy and reconciles the plan afterward. Use when the architect wants to pull the latest from Jira, refresh ticket status, import a backlog, or reconcile canopy tasks with the Jira board.
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

## Notes
- Status shown on canopy tasks mirrors Jira; treat it as read-only.
- Webhooks push live changes; the periodic reconciliation poll is the backstop. A
  manual sync is still useful right before planning or a review.
- If a story's epic hasn't synced yet, its parent link resolves on the next sync.
