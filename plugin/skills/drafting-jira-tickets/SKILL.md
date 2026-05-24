---
name: drafting-jira-tickets
description: Turn requirements / design docs (and existing Jira epics) into a reviewable draft plan, then create or update the Jira tickets from it — with estimates and story points. Use when the architect wants to "plan then create the tickets", break a spec into epics/stories, or push a finalized plan into Jira.
---

# Drafting & creating Jira tickets in canopy

Use this when the architect wants to go from inputs (a codebase, a design doc / PRD, and
the epics already in Jira) to **created Jira tickets**. canopy stages the plan as a *draft*
the architect reviews first, then writes it to Jira.

**Boundary:** canopy writes ticket **content** (summary, description, story points) and the
epic→story parent link — it **never** writes ticket status. Jira stays the owner of status.

## Workflow

1. **Gather the inputs.**
   - Read design docs / PRDs: `canopy:read_design_doc` (Google Drive) or
     `canopy:read_repo_file` (GitHub).
   - See what already exists in Jira: `canopy:trigger_jira_sync`, then `canopy:list_tasks`.
   - Find the project (`canopy:list_projects`); note its numeric `project_id`.
2. **Open a draft plan.** `canopy:create_draft_plan(project_id, title, source=…)`. Put the
   doc/PRD reference in `source` so the plan's provenance is recorded.
3. **Propose the work.** For each chunk, `canopy:add_draft_task`:
   - `task_type="summary"` for an **epic / phase**; leaf `task`s under it via `parent_id`.
   - Give each leaf an `estimate_days` (canopy duration) and, where you have it, `story_points`.
   - Keep names outcome-oriented ("Ship token refresh", not "auth work").
4. **Review with the architect.** Show the plan with `canopy:get_draft_plan`. Refine via
   `canopy:update_draft_task` / `canopy:delete_draft_task`. **Do not push until they approve** —
   this is the point of the draft.
5. **Create the tickets.** `canopy:push_draft_to_jira(plan_id)` (auto-detects the project's
   Jira connection; pass `connection_id` if there are several). Epics are created before their
   stories so the parent link resolves; a re-push **updates** the already-created tickets
   instead of duplicating.
6. **Pull them back.** Run `canopy:trigger_jira_sync` so the new issues land as canopy tasks,
   then `canopy:replan_schedule` to fold them into the critical path.

## Conventions
- The draft is the review surface — iterate there, not in Jira. Push once it's agreed.
- Story points need the Jira connection's `story_point_field` configured (e.g.
  `customfield_10016`); without it, points are skipped and only summary/description are written.
- Issue-type names default to **Epic** (summary) and **Story** (task) and are overridable via
  the connection's `epic_issue_type` / `story_issue_type` config.
- After a push, report what was created/updated (with the new Jira keys) and any failures —
  failures don't abort the rest of the push, and a re-push retries them.
