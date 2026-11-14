---
name: drafting-jira-tickets
description: Deprecated name of the drafting-tickets skill (kept one release) — turning docs into a reviewed draft plan and creating Jira tickets from it. Use drafting-tickets.
---

# Drafting Jira tickets → see `drafting-tickets`

Draft plans now finalise into whichever tracker the project uses — or into native canopy tasks
when it has none. Follow the **`drafting-tickets`** skill: stage the plan, review it with the
architect, then `finalize_draft_plan` (human-only). `push_draft_to_jira` still works as an alias
for Jira-bound projects for one release. canopy writes ticket content only — never status.
