---
name: updating-canopy
description: The operating guide for ANY session that reads or updates canopy — how to orient (who the user is, their persona/function, token scope, feature gates), when to write directly vs stage a change proposal for human review, and the source-of-truth rules that must never be violated. Use at the start of every canopy session, whenever you're about to create/update canopy data (tasks, milestones, blockers, risks, outcomes, decisions, docs), and especially before turning information from other tools (Slack, Gmail, Calendar, meetings, Jira, GitHub, Drive) into canopy updates.
---

# Updating canopy — the session operating guide

Canopy is the architect's system of record for plans, decisions, risks, and delivery
health. You are a first-class operator of it — but a **bounded** one: reversible work runs
freely, and anything consequential lands through a **human review in the canopy UI**.
This guide is the contract for every canopy session; the other canopy skills assume it.

## 1. Orient first (always)

Call `canopy:get_workspace_context` before anything else. It tells you:

- **Who you're working for** — `user` + `function` (their persona) and `role` (what they
  may write). Adapt altitude and defaults to the persona (see the `persona-playbooks`
  skill): a product user cares about outcomes/milestones/status; management about
  capacity/blockers/digests; architecture about decisions/drift/critical path;
  leadership reads digests and rarely writes.
- **`token_scope`** — `"agent"` means this session holds a bounded token (USER_FLOWS §A6):
  staging, reading, and reversible writes work; one-way-door / external-write actions
  (applying proposals, accepting a one-way-door ADR, push-to-Jira, applying a scenario)
  will 403. Don't fight the 403 — it is the design. Route those through the human in the UI.
- **`features`** — the admin's gate map. A 403 with `feature_disabled` means the surface is
  off; say so instead of retrying.
- **`projects` / `initiatives`** — anchor every id you use against these; never guess ids.
- **`open_proposals`** — changes already awaiting review. Read them before staging more so
  you extend rather than duplicate.

## 2. The write ladder — decide *how* a change lands

Work out which rung every intended change sits on **before** calling any write tool:

1. **Just read** — questions, briefings, analysis. Most sessions end here. Prefer the
   purpose-built reads (`get_initiative_digest`, `get_board`, `get_risk`, `get_forecast`,
   `decision_queue`) over raw entity dumps.
2. **Direct write** — allowed when ALL of these hold:
   - the user **explicitly asked for this specific change** in this conversation
     ("rename that task", "set health to at-risk", "raise a blocker on X"), and
   - it's **small** (one or two entities) and **reversible**, and
   - it's not schedule-shaping beyond what they dictated.
   Tools like `update_task`, `assign_task`, `raise_blocker`, `set_project_health`,
   `comment_adr`, `set_tags` exist for exactly this tactical lane. After a schedule-
   affecting direct edit, run `replan_schedule` and report the new end date.
3. **Stage a change proposal** (`canopy:propose_changes`) — the **default** whenever any
   of these is true:
   - the change is **inferred from external sources** (Slack, Gmail, Calendar, meeting
     notes, Jira comments, PRs, docs) rather than dictated by the user in this session;
   - it touches **several entities** (roughly 3+) or **re-shapes the schedule** (new
     tasks/dependencies, duration changes, milestone moves);
   - it records **judgment** the user hasn't seen yet (risks, outcomes, proposed
     decisions, health narratives you drafted);
   - the user says "for review", "draft", "propose", or is not the planner themselves.
   Staged items never touch the live plan, Gantt, CPM, or board until a human applies
   them in the **Reviews** queue. Always end by giving the user the returned
   `review_url` and a one-line summary of what awaits them there.
4. **Human-only, never you** — applying proposals, accepting a **one-way-door** ADR,
   pushing drafts to Jira (unless the human runs it), applying a scenario, minting
   tokens, anything admin. Your job is to *prepare* these perfectly and hand over the link.

When in doubt between rungs 2 and 3, stage. A proposal that gets applied unchanged
costs the human one click; an unwanted direct write costs them trust.

## 3. Provenance discipline (non-negotiable for harvested facts)

Every proposal item derived from an external source carries:
- `source_kind` — slack | email | calendar | meeting | jira | github | drive | document | chat
- `source_label` — human-readable ("Slack #payments — standup thread, Jul 10",
  "Email: 'Pentest SOW' from vendor", "Design review meeting notes")
- `source_url` — deep link when one exists
- `reason` — one line of *why this change follows* from that source

The reviewer must be able to audit every line without asking you. An item with no
provenance is your own inference — say so in its `reason`.

## 4. Source-of-truth rules (never violate)

- **Jira owns tickets and status.** Never write ticket status anywhere — not via
  `update_task` (the API refuses), not via a proposal (`status` is not stageable), not
  via your own Jira tools *for tasks canopy mirrors*. Plan→Jira ticket creation goes
  through the reviewed **draft plan** flow (`drafting-jira-tickets`), content only.
- **GitHub owns code; Drive owns design docs.** Canopy links, it never copies
  (`add_doc_reference`); the only canopy→Drive write is an export snapshot.
- **Canopy owns the plan** (tasks/dependencies/milestones), decisions, risks, outcomes —
  that's what proposals and the direct tools edit.
- **Structured mirror-sync is not a proposal.** Syncing Jira issues into canopy verbatim
  (`trigger_jira_sync`, `ingest_jira_issues`, `link_jira_ticket`) is judgment-free
  mirroring — use the `syncing-jira` / `mcp-ingest` skills. Proposals are for changes
  that carry *your judgment*.

## 5. Review etiquette (the loop after staging)

- One proposal per coherent review (per project or per theme), typically 3–15 items.
  Title it for the reviewer ("Standup follow-ups — payments", not "Updates").
  `summary` = your rationale in 2–5 lines. Set `origin` to your persona context, e.g.
  `"claude-session (management persona)"`.
- **Tell the user**: what you staged, the item count, and the `review_url`. In the UI
  they can exclude individual items before applying — mention that.
- **Follow up** with `canopy:get_proposal` when the session resumes or they ask:
  `applied` → confirm and continue from the applied state; `rejected` → read
  `review_note`, adjust, restage smaller; still `open` → gentle reminder with the link.
- Withdraw (`canopy:withdraw_proposal`) anything superseded — a stale open proposal is
  noise in the reviewer's queue.

## 6. Session checklist

1. `get_workspace_context` → persona, scope, features, ids, open proposals.
2. Read before writing; anchor ids.
3. Classify each intended change on the write ladder; batch rung-3 changes into one
   well-titled proposal with provenance.
4. Replan after schedule-affecting direct edits; proposals replan automatically on apply.
5. End with: what changed directly, what awaits review (+ `review_url`), what you
   deliberately did NOT do (gates, human-only doors, missing signal).
