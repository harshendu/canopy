---
name: syncing-jira
description: Deprecated name of the syncing-trackers skill (kept one release) — syncing epics, stories and status from Jira into canopy. Use syncing-trackers.
---

# Syncing from Jira → see `syncing-trackers`

Jira is one work tracker among several now. Follow the **`syncing-trackers`** skill: orient with
`get_project_tracking`, sync with `sync_project_tracking` / `sync_tracker`, link items with
`link_tracker_item`, and bind/switch trackers with `switch_project_tracking` (preview; a human
applies). The Jira-named tools (`trigger_jira_sync`, `link_jira_ticket`, `list_jira_links`,
`resync_jira_link`, `unlink_jira_ticket`, `ingest_jira_issues`) still work as aliases for one
release. canopy never writes status to Jira.
