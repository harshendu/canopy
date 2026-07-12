---
name: persona-playbooks
description: Day-in-the-life playbooks for each canopy persona (function) — architect, product/PM, engineering manager/delivery, leadership/exec, engineer, design — mapping what each reads first, which canopy verbs they use, what gets staged for review vs written directly, and which sibling skills to chain. Use when tailoring a session to who the user is ("act as my chief of staff", "I'm the PM on this", "run my morning as an EM"), when get_workspace_context reports their function, or when asked what canopy can do for a given role.
---

# Persona playbooks

Canopy personas (`function` on the user, USER_FLOWS §A7) are a **lens, not a wall**:
reads are open to everyone; writes are gated by `role`; the persona sets the altitude and
the default surfaces. Get the user's function from `canopy:get_workspace_context`, open
with their playbook, and keep the `updating-canopy` write ladder in force throughout —
what differs per persona is *what you read and stage*, not the review rules.

## Architecture (staff/principal architect)
- **Read first:** `decision_queue` (stuck/overdue decisions), `get_drift` per project
  (+ `scan_due`), the cross-project `get_initiative_critical_path`, `get_risk`.
- **Core verbs:** `create_adr`/`propose_adr`/`transition_adr`/`comment_adr`,
  `add_adr_fitness`, `adr_impact`, `scan_drift`/`reconcile_drift` (via `drift-sentinel`),
  plan edits, `whatif_schedule`.
- **Stage vs direct:** decisions harvested from threads/meetings → `decision.create`
  items in a proposal; WBS re-shapes → proposal; a one-line ADR comment or a transition
  the architect just dictated → direct. Accepting a **one-way-door** ADR is theirs alone,
  in the UI.
- **Chain:** `writing-adrs`, `planning-roadmaps`, `decision-deadline-nudger`,
  `pr-to-adr-linker`, `drift-sentinel` agent.

## Product (PM)
- **Read first:** `get_initiative_digest` (exception-first), `list_outcomes` (the bets),
  `list_milestones` + roadmap horizon, `get_forecast` (P50/P85 vs the date they promised),
  `get_doc_coverage` (missing PRDs/designs).
- **Core verbs:** `add_outcome`/`update_outcome`, `create_milestone`,
  `add_doc_reference`, `set_project_health` (narrative), draft plans → Jira
  (`drafting-jira-tickets`), specs (`spec-driven-development`).
- **Stage vs direct:** metric movements, scope adds, milestone moves, and anything from
  customer/stakeholder email → proposal; recording the current_value they just read out
  → direct. PMs are often not planners — staging is also how their judgment lands
  without write permissions.
- **Chain:** `harvesting-signals` (inbox → plan), `daily-standup` for the weekly update.

## Management (EM / delivery lead / director)
- **Read first:** `get_capacity` (org-wide — cross-project overload), `list_blockers`
  (open, by severity/needed-by), `get_board` per project (WIP + aging), `list_alerts`,
  `get_delivery_metrics` (team-level DORA + flow).
- **Core verbs:** `assign_task`, `allocate_engineer`, `raise_blocker`/`resolve_blocker`,
  `add_risk`, `set_project_health`, `update_task` (durations from standup reality).
- **Stage vs direct:** the standup/inbox sweep (`harvesting-signals`) → proposal;
  re-assignments and estimate corrections they dictated in-session → direct + replan.
  PTO seen in Calendar: report it — availability is planner UI work, not yours.
- **Chain:** `capacity-planning`, `daily-standup`, `delivery-enricher` agent for the
  pre-steering annotation pass.

## Leadership (exec)
- **Read first (usually read-only):** `get_initiative_digest` per initiative,
  `list_projects` portfolio health, worst risks (`get_risk`), outcome verdicts.
- **Core verbs:** almost none — synthesize; don't drown them in entities. Their asks
  ("push that date", "who owns this?") usually become items **staged for their planners**
  to review, not writes you make.
- **Chain:** `daily-standup` with an initiative loop; export snapshots exist in the UI
  for board packs (no MCP tool).

## Engineering (IC engineer)
- **Read first:** `my_workspace` (their tasks, blockers, decisions to review),
  `get_spec` for the spec they're implementing.
- **Core verbs:** `update_task` on **their own task** (progress), `raise_blocker`,
  `update_spec_criterion` (self-audit met/unmet), `propose_adr`, `comment_adr`.
- **Stage vs direct:** their own-task progress and blockers → direct (that's their
  lane); anything touching the wider plan → proposal (they usually can't write it
  anyway — staging carries their judgment to the planner).
- **Chain:** `spec-driven-development`, `writing-adrs` (propose flow).

## Design (UX)
- **Read first:** the doc graph (`list_doc_references` — design/PRD coverage), the tasks
  their designs gate, `decision_queue` for decisions naming them as stakeholders.
- **Core verbs:** `add_doc_reference` (Figma/design links), `comment_adr` (design
  review), `raise_blocker` ("design not ready" is a real dependency signal).
- **Stage vs direct:** linking one doc they pasted → direct; a design-review sweep
  producing scope/risk changes → proposal.

## Common shape of a persona session

1. Orient (`get_workspace_context`) → open with the persona's "read first" set,
   exception-first (green is silent).
2. Offer the persona's 2–3 highest-leverage actions for what you found — not a tool tour.
3. Execute on the write ladder; batch judgment into one proposal; end with the review
   link and what needs *them* (decisions, approvals, the one thing most likely to slip).
