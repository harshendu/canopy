---
name: planning-sprints
description: Plans, runs and reviews sprints for a team that works in sprints in canopy — building a sprint from the team's backlog against capacity and velocity, starting it, closing it with carry-over, and reading the sprint report and velocity forecast. Use when someone asks to plan the next sprint, what fits in a sprint, how the current sprint is going, to close a sprint, or about velocity / commitment reliability. Also tells you when a team runs Kanban instead (then sprints don't apply).
---

# Planning and running sprints in canopy

A **team** chooses how it runs work across *all* its projects: `kanban`, `sprint` or `both`.
Sprints belong to the team (optionally one pod) and span every project it runs.

## 0. Check the method first

`canopy:get_team_delivery(team_id)` → if `effective_method` is `kanban`, sprints don't apply:
manage flow with the board (`get_board`, WIP limits, aging) instead. Changing the method is
`set_team_delivery` — the team's directors/managers only, and only when asked.

## 1. Plan a sprint

1. **Context.** `list_sprints(team_id)` (is one active? is the next one already planned?) and
   `get_velocity(team_id)` (mean completed per sprint, reliability, how many sprints of history).
2. **Backlog.** `get_board(team_id=…, sprint="backlog")` — open work of the team's projects that
   sits in no live sprint, in rank order (the order *is* the priority — respect it).
3. **Create / fill.** `plan_sprint(team_id=…, name?, goal?, add_task_ids=[…])` creates a planned
   sprint (dates default to the day after the last one, for the team's length) and plans tasks
   in. For an existing sprint: `plan_sprint(sprint_id=…, add_task_ids=[…] / remove_task_ids=[…])`.
4. **Check capacity.** `get_sprint(sprint_id)` → `capacity`: open estimate vs person-days
   (days unit) or vs mean velocity (points/count). `over_capacity` **warns, never blocks** —
   say so, and propose what to drop (lowest-ranked first), don't silently trim.
5. **Start** when the humans agree: `start_sprint(sprint_id)` (captures the commitment).

## 2. During the sprint

- `get_board(team_id=…, sprint="active")` is the sprint board — same columns, moves and WIP
  rules as Kanban. Move cards with `move_task` (canopy-owned tasks only).
- `get_sprint(sprint_id, include_report=True)` → burndown vs ideal, **scope added** after the
  start (shown separately — call it out), completed so far.
- The project alerts include `sprint_overrun`: a task whose *computed* end falls after its
  sprint ends. Sprints never pin the schedule — surface the conflict, let the planner decide.

## 3. Close it

`complete_sprint(sprint_id, carry_over="next", next_sprint_id=…)` (or `"backlog"`). Report:
completed vs committed (reliability), scope change, what carried over and why it matters for
the next plan. Then `get_velocity` for the trend and the P50/P85 sprints-to-done forecast.

## Rules

- **Who owns a sprint.** A sprint mirrored from a tracker (`owner` ≠ "canopy") is read-only
  here, and a mirrored task whose tracker syncs sprints can't be re-planned in canopy — the
  tools say so (`sprint_externally_owned`, `membership_externally_owned`); change it in the
  tracker. canopy never writes sprints back to a tracker.
- **Explicit vs inferred.** `plan_sprint` / `start_sprint` / `complete_sprint` are for explicit
  instructions. A change you *inferred* from a signal (Slack, a meeting) — "X should go into the
  next sprint" — goes through `propose_changes` (task `sprint_id`) for a human to review.
- **Team-level only.** Velocity and reliability describe the team, never an individual —
  don't break them down per engineer or compare teams.
- **Units.** A team estimates in points, days or count; with points but no estimates yet, the
  numbers fall back to a count of tasks (`unit` says which).
