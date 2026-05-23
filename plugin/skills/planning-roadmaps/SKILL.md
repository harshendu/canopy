---
name: planning-roadmaps
description: Turns a high-level initiative or spec into a canopy plan — projects, summary phases, tasks, dependencies — then schedules it with the critical path method. Use when the architect wants to lay out a roadmap, break work down, sequence tasks, or (re)compute a timeline and critical path.
---

# Planning roadmaps in canopy

Use this when the architect describes work to be planned ("plan the auth rewrite",
"lay out Q3", "what's our critical path?"). canopy owns the schedule; Jira owns the
tickets (see the `syncing-jira` skill to pull real epics/stories first).

## Workflow

1. **Find or create the project.** Call `canopy:list_projects`. If none fits, create
   one in the app (or ask the architect). Note the numeric `project_id`.
2. **Build the work breakdown structure (WBS).**
   - Create `summary` tasks for phases/workstreams with `canopy:create_task`
     (`task_type="summary"`).
   - Create leaf `task`s under each phase (`parent_id` = the summary task id).
   - Use `milestone` tasks for zero-duration checkpoints, and
     `canopy:create_milestone` for named, date-bearing milestones.
   - Give every leaf task a realistic `duration` in days.
3. **Sequence the work.** Add dependencies with `canopy:link_dependency`. Default to
   `FS` (finish-to-start). Use `SS`/`FF`/`SF` and `lag` only when genuinely needed.
   Avoid cycles — the scheduler rejects them.
4. **Schedule.** Call `canopy:replan_schedule`. It returns the critical-path task ids
   and the project end date. Summarize: end date, which tasks are critical, and where
   the float is.
5. **Iterate.** When the architect changes scope, durations, or the team, adjust tasks
   and re-run `canopy:replan_schedule`.

## Conventions
- Prefer a shallow WBS (phases → tasks). Don't nest more than 2–3 levels.
- Keep task names outcome-oriented ("Ship token refresh", not "work on auth").
- The critical path is whatever has zero float — protect those tasks when negotiating
  scope or dates.
- Report timelines in terms the architect cares about: end date, critical path, and
  the riskiest dependency, not raw task dumps.
