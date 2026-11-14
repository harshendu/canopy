---
name: drafting-tickets
description: Turn requirements / design docs (and the epics already planned) into a reviewable draft plan, then finalise it — into canopy tasks for a native project, or into tickets in the project's tracker (Jira, Linear…) for a mirrored one — with estimates and story points. Use when the architect wants to "plan then create the tickets/tasks", break a spec into epics/stories, or push a finalized plan into the tracker.
---

# Drafting a plan and finalising it into real work

canopy stages proposed work as a **draft plan** the architect reviews first, then **finalises**
it. Finalising follows the project's tracking mode (`canopy:get_project_tracking`):
- **native** — canopy creates the tasks itself (keys, first statuses, parents, then a replan);
- **mirrored** — canopy writes the plan's items to the bound tracker: **content** only
  (summary, description, story points, the epic→story parent) — **never status** — and the next
  sync pulls them back as canopy tasks.

**Two staging lanes — pick the right one.** A **draft plan** (this skill) stages *new work*
that will become tasks/tickets; finalising is the human-approved commit. A **change proposal**
(`propose_changes`, see `updating-canopy`) stages changes to *existing canopy data*, committed
from the Reviews queue. Don't route one through the other.

## Workflow
1. **Gather the inputs.** Design docs / PRDs (`canopy:read_design_doc`, `canopy:read_repo_file`);
   what already exists (`canopy:list_tasks`, and for a mirrored project a fresh
   `canopy:sync_project_tracking`). Note the numeric `project_id` (`canopy:list_projects`).
2. **Open a draft plan.** `canopy:create_draft_plan(project_id, title, source=…)` — put the
   doc reference in `source` so provenance is recorded.
3. **Propose the work.** `canopy:add_draft_task` per chunk: `task_type="summary"` for an epic /
   phase, leaf tasks under it via `parent_id`, each with `estimate_days` and, where known,
   `story_points`. Keep names outcome-oriented ("Ship token refresh", not "auth work").
4. **Review with the architect.** `canopy:get_draft_plan`; refine with `update_draft_task` /
   `delete_draft_task`. **Don't finalise until they approve.**
5. **Finalise — a human does it.** `canopy:finalize_draft_plan(plan_id)` is human-only: an agent
   token gets 403, so ask the human to finalise in canopy (the draft plan view) unless this
   session runs on their full token and they asked you to. A re-finalise updates what was
   created before instead of duplicating; `mode` in the result says native or tracker.
6. **Fold it in.** Native: the tasks are live and replanned. Mirrored: run
   `canopy:sync_project_tracking(project_id)` to pull the new items back, then
   `canopy:replan_schedule`.

## Conventions
- The draft is the review surface — iterate there, not in the tracker.
- Story points need the binding's estimate field — its `mapping.estimate_field` (e.g.
  `customfield_10016`, set with `canopy:set_project_tracking`; for Jira the connection's
  `story_point_field` is the fallback); without one only summary/description are written.
  New items take the mapping's types too (its first `epic_types` entry, its `item_type`).
- When the tracker's writes are MCP-managed, finalising can't write to it: create the items
  with your own tools and record them with `canopy:record_draft_push` (see `mcp-ingest`).
- Report what was created/updated (with the new keys) and any failures — a failure doesn't
  abort the rest, and a re-finalise retries it.
