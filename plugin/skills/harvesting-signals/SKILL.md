---
name: harvesting-signals
description: Sweep the user's other connected tools — Slack, Gmail, Google Calendar, meeting notes (Granola/Drive), Jira comments, GitHub PRs — for project-relevant signal (blockers, risks, decisions, status changes, date commitments, new scope, documents) and turn it into a change proposal the human reviews in canopy. Use when asked to "catch canopy up", "process my inbox/standup/meeting notes into the plan", "what happened this week — update canopy", or on a scheduled sweep. Requires the updating-canopy skill's rules.
---

# Harvesting signals → canopy proposals

Project truth lives scattered in Slack threads, inboxes, calendars, and meeting notes.
This skill is the pipeline that lands it in canopy **without bypassing the human**: you
read with the session's own connectors, classify, dedupe against canopy, and stage ONE
reviewable proposal per scope. You never write the live plan directly from harvested
signal (see `updating-canopy` §2 — harvested facts are always rung 3).

## 1. Scope the sweep

- `canopy:get_workspace_context` → persona, projects/initiatives, open proposals.
- Agree the window ("since Monday", "this sprint") and the scope (one project, an
  initiative, or the user's whole portfolio) with the user unless they already said.
- Inventory which source tools this session actually has (Slack, Gmail, Calendar,
  Granola/meeting notes, Jira, GitHub, Drive). Only promise what's connected.

## 2. Read each source with intent (not exhaustively)

Look for the seven signal types canopy can hold; skip everything else:

| Signal | Looks like | Canopy landing |
|---|---|---|
| **Blocker** | "waiting on…", "blocked by…", unanswered ask, vendor/legal delay | `blocker.create` (category, severity, needed_by) |
| **Risk** | "worried about…", flaky vendor, unproven tech, key person out | `risk.create` (probability × impact, mitigation) |
| **Decision** | "we decided/agreed…", "let's go with X over Y" in a thread/meeting | `decision.create` (staged as a *proposed* ADR) |
| **Status/progress** | "shipped", "done", "half way", demo notes | `task.update` (percent_complete — NEVER Jira status) |
| **Date/scope commitment** | "we'll deliver by…", "adding a hardening phase", new asks | `task.create` / `task.update` (duration/deadline) / `milestone.create` / `dependency.create` |
| **Outcome signal** | metric moved ("p95 now 310ms"), bet validated/at risk | `outcome.create` / `outcome.update` |
| **Document** | PRD/design/runbook link shared in thread or invite | `doc_reference.create` (kind + url) |

Source-specific hints:
- **Slack**: standup threads, #incident channels, decisions buried in replies. Capture
  the permalink as `source_url`.
- **Gmail**: vendor/procurement threads (blockers), stakeholder commitments (dates),
  attachments referenced by link (docs).
- **Calendar**: PTO/OOO events are capacity signal (surface in the summary for the human
  — availability editing is UI/planner work); recurring "decision review" or steering
  meetings tell you where decisions get made.
- **Meeting notes (Granola/Drive)**: action items → tasks/blockers; "we agreed" →
  proposed decisions; demo feedback → risks/scope.
- **Jira comments / GitHub PRs**: scope creep in comments, "blocked" labels, PRs that
  contradict an accepted ADR (see `pr-to-adr-linker`).

## 3. Dedupe against canopy before staging

For each candidate: check it isn't already there — `list_blockers(open_only=true)`,
`list_risks`, `list_tasks` / `get_board`, `list_adrs`, `list_outcomes`,
`list_doc_references`, and the `open_proposals` from context. An existing entity that
changed → an `update` item; already staged → skip (or note it in the summary).

## 4. Stage one proposal per scope

`canopy:propose_changes` with:
- a reviewer-facing `title` ("Week 28 signal sweep — Payments") and a `summary` that
  says what you read and the judgment you applied;
- `origin` = your persona context, e.g. `"claude-session (signal harvest)"`;
- every item carrying `source_kind` / `source_label` / `source_url` / `reason`
  (provenance is non-negotiable — `updating-canopy` §3);
- refs (`ref` + `parent_ref`/`predecessor_ref`/`task_ref`) when items build on each other.

Order items create-before-reference. Keep a proposal reviewable: if the sweep found 30
things, split by project or by theme rather than staging one monster.

## 5. Report to the user

End with, in this order:
1. The **review link(s)** and item counts ("12 changes staged — review at …").
2. What you found but did **not** stage (duplicates, ambiguous signal, capacity/PTO
   observations, anything needing their judgment) — with source links.
3. Anything time-critical they should act on today (a high-severity blocker with a
   needed-by date beats everything else).

Then follow the review loop in `updating-canopy` §5 (check `get_proposal` later; read
`review_note` on rejection; withdraw anything superseded).

## Scheduling

This skill is safe to run on a cadence (it writes only staged proposals). Pair it with
`/loop` or a scheduled task — e.g. every weekday morning before standup — using an
**agent-scope token** (USER_FLOWS §A6), which structurally cannot apply what it stages.
For heavier sweeps, delegate to the `signal-harvester` subagent.
