---
name: capacity-planning
description: Balances a team's capacity against the plan in canopy — spotting over-allocation, and using what-if scheduling to test adding/removing people or cutting scope. Use when the architect asks about staffing, whether the team can hit a date, who is overloaded, or "what if we add an engineer / cut scope".
---

# Capacity planning in canopy

Use this when the question is about *people vs. plan*: is the team overloaded, can we
hit the date, what happens if staffing or scope changes.

## Workflow

1. **See the load.** `canopy:get_capacity` returns the engineer × week allocation grid.
   Anything over 100% in a week is over-allocated. `canopy:list_alerts` surfaces the same
   over-allocations alongside deadline misses and overdue milestones.
2. **Find the constraint.** Cross-reference over-allocated people with the critical path
   (`canopy:get_gantt` / `canopy:replan_schedule` returns critical-path task ids). Overload on
   a critical-path task is what actually slips the end date.
3. **Test changes with what-if.** `canopy:whatif_schedule` projects an end date for hypothetical
   task durations *without persisting* — model "add an engineer" (shorter durations on their
   tasks) or "cut scope" (drop/zero a task) and compare the projected end date + deadline
   violations to today's plan.
4. **Recommend.** Report in the architect's terms: who is overloaded and in which weeks, whether
   the date is at risk, and the smallest staffing/scope change that resolves it.

## Notes
- Capacity is modeled separately from assignment (allocations have percent + date range), so a
  person can be over-allocated across overlapping allocations even if no single one exceeds 100%.
- What-if never writes to the plan — always confirm before making a change permanent (durations,
  allocations) via the normal tools.
