---
name: working-the-board
description: Moves work on canopy's Kanban board the right way — moving and reordering cards, pulling unassigned work, respecting WIP limits, and knowing which cards' status canopy owns versus a tracker. Use when the user asks to move a card or task to a column, start/finish work, reorder priorities, check WIP or aging, or tidy a board.
---

# Working the board

Every project has a board: ordered **columns** (each a status with a category — todo,
in_progress, done, cancelled — and an optional WIP limit) and ranked **cards**. Columns come
from the team's workflow (or the project's override, the workspace template, or — for a
mirrored project — its tracker's statuses).

## Read before you move
- `canopy:get_board(project_id=…)` (or `team_id=…` for the team board; `sprint=active|backlog|
  all|<id>` for sprint teams): lanes with `wip`, `scope_wip` (open cards across every project
  sharing the columns — what the limit counts) and `wip_limit`, cards with `key`,
  `status_owner`, `movable`, `aging`, `blocked`. The `viewer` block says what *you* may do.
- `canopy:get_workflow(project_id)` → the columns and WIP enforcement (`off` | `warn` |
  `block`). `scope: "tracker"` means the tracker owns the columns: they can't be edited here.

## Move
- `canopy:move_task(task_id, to_status=…)` changes a card's column — **only for canopy-owned
  cards** (`movable: true`). It records the transition in the task's history (the one status
  write path), and reconciles progress (done → 100%).
- Reorder within a column with `after_task_id` / `before_task_id` / `position` and no
  `to_status` (allowed for mirrored cards too — the order is canopy's).
- Pass `expected_status` (the status you saw) so a concurrent move isn't overwritten (409
  `stale` → re-read the board).
- Who: a planner who may edit the project moves any canopy-owned card; anyone else contributing
  moves their own cards, or **pulls** an unassigned one by moving it to another column (it is
  assigned to them). Reordering an unassigned card doesn't take it.

## Delegated cards (the agent work queue)
A card with `delegation: "agent"` is worked through canopy's work queue: its `claim` badge
shows the session holding it and its `gate` badge what a person must decide. **Don't
`move_task` a delegated card** — an agent token gets `409 use_work_claim`; claim it and hand
off with `submit_work` instead (`working-the-queue`). A person *can* move one (the board
follows reality): the running claim ends and its session is told to stop, and any entry-check
warnings come back in the move response.

## Refusals and what they mean
- `409 status_externally_owned` — a mirrored card: its tracker owns the status. Say so and give
  the link (`url` in the response); don't try another route to change it.
- `409 wip_limit_reached` — enforcement `block` and the column is full: finish or move
  something out first (`warn` succeeds with `warnings: ["wip_limit_exceeded"]` — mention it).
- `422 unknown_status` — not a column of that card's workflow (`columns` lists them).
- `403 native_tracking_disabled` — the admin turned canopy-owned status off.
- `409 use_work_claim` — a delegated card and an agent token: use the work queue's verbs.
- `409 checks_failed` (a person's move of a delegated card) — a column check marked for
  everyone blocks it; a planner may pass `override_reason` (recorded) if they insist.

## Inferred vs instructed
Move a card when the user **tells** you to ("move CHK-12 to In Review"). When you merely
**inferred** a status from a signal (Slack, a meeting, a PR), stage it in a change proposal
(`updating-canopy` / `harvesting-signals`) so a human reviews it — and never for a mirrored
task.
