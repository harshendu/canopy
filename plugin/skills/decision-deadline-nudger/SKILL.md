---
name: decision-deadline-nudger
description: Surfaces deferred architecture decisions whose decide-by date is approaching and nudges the owner. Use when the architect asks "what decisions are coming due?", "anything I'm forgetting to decide?", or as a scheduled (e.g. weekly) sweep. Architects forget their own deferred decisions — the system should remember.
---

# Decision-deadline nudger

Deferred decisions (ADRs in the `deferred` state) carry a `decide_by` date. This skill finds the
ones coming due and prompts the owner with the context they need to decide.

## Workflow

1. Pull the decision queue with `canopy:decision_queue` (omit `project_id` for an org-wide sweep, or
   pass one to scope it). Look at the `deferred_soon` bucket — these are `deferred` ADRs whose
   `decide_by` is within ~14 days (or already past, flagged `overdue`).
2. For each, read it with `canopy:get_adr` to recover the context, the **alternatives considered**,
   and the decision owner.
3. Draft a tight nudge: the decision, its `decide_by`, the alternatives still on the table, and the
   one question that needs answering. Post it to the ADR thread with `canopy:comment_adr` (so it's
   captured where the decision lives), addressed to the owner.
4. Lead your reply to the architect with anything **overdue**, then what's due soonest. Don't dump
   the whole queue — surface the few that need action now.

## Notes
- A decision with no `decide_by` that's stuck in `deferred` is itself a smell — call it out.
- If an alternative has clearly won since the deferral, suggest moving the ADR to
  `under_discussion` or `accepted` via `canopy:transition_adr` (with the owner's go-ahead).
