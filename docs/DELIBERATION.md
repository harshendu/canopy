# Deliberation — structured thinking before the decision, linked not stored

> **Status: proposal, not built.** This document designs how the output of a structured
> deliberation — a multi-perspective research, brainstorming, debate, pre-mortem or review session
> run outside canopy — enters canopy's decision spine, and how deliberation that blocks work flows
> through the agent work queue. canopy gains no deliberation engine and calls no model.
> [`USER_FLOWS.md`](./USER_FLOWS.md) remains the source of truth for what *is* built.
>
> The first facilitator this is designed against is **Council** (the `harshendu/agents`
> repository): a roster of AI personas ("a chamber") deliberates under a protocol that Council's
> MCP server enforces, with Claude as the only model. Its side of the design — the protocol
> engine, the plugin, and the bridge plugin that choreographs both products — is in that
> repository at `docs/feat/council-canopy-loop/` (`CONCEPT_REVIEW.md`, `PLAN.md`). Nothing below
> is specific to Council: a design-review meeting or an RFC thread can use the same seams.
>
> Companions: [`AI_NATIVE_EXECUTION.md`](./AI_NATIVE_EXECUTION.md) §0 ("the binding constraint
> moves *up* the stack — to judgment"), §7 gaps #5 and #7;
> [`EXECUTION_PHILOSOPHY.md`](./EXECUTION_PHILOSOPHY.md) §3 (one-way doors "deserve friction") and
> §7 ("the retro's output is a change to the system");
> [`AGENT_EXECUTION.md`](./AGENT_EXECUTION.md) principles P1–P11, cited below by number.
>
> Everything stated about current behaviour was verified by reading the code at `b79cbe8`; nothing
> was executed.

---

## 0. Summary

**The gap.** canopy holds decisions (ADRs with a lifecycle, reversibility, a queue), intent
(specs, outcomes) and plans, and it detects when judgment is missing: a decision is stuck, a plan
rests on an unsettled decision, an agent's confidence is low, a task is parked. What it has no
home for is the thinking that *produces* a decision. The words ideation, debate, deliberation,
pre-mortem and dissent do not occur in the code, the plugin or the docs. An ADR can carry
`alternatives` as a flat list of strings and a comment thread; that is all.

**The proposal in eight decisions.**

1. **canopy owns the decision; the deliberation lives elsewhere.** A deliberation's transcript,
   positions and minutes stay with the facilitator. canopy keeps what it keeps for any design
   doc: a link, a kind, a version, a summary of at most 2,000 characters and a locally computed
   hash (§V5, "link, don't store").
2. **A deliberation lands as one reviewed proposal.** Its recommendation is agent judgment the
   planner has not seen, so it sits on rung 3 of the write ladder (`updating-canopy` §2): one
   `propose_changes` batch carrying the proposed decision, its risks and its follow-up work. A
   person applies it. No direct ADR write, no status transition.
3. **The record is a design doc, linked as the decision's basis.** Accepting the ADR pins the
   record's version (`design_docs.pin_basis_links`); a later revision raises `behind_pin`. The
   existing doc graph already does this.
4. **Deliberation is risk-tiered, never routine** (P4). One-way doors, unsettled decisions that
   block work, low-confidence plans, parked tasks, stuck decisions and retros warrant it.
   Two-way doors are decided fast, as today.
5. **Deliberation that blocks work is work.** It runs as a stage a `deliberator` role works
   inside one claim and ends at a human decision column. This uses stage policy as built.
6. **Advice is not a decision** (P5). A session may attach advice to a task or cite it in a
   question; only a person answers a gate or accepts an ADR.
7. **canopy never calls the facilitator** (P2). A Claude session with both plugins installed
   carries context out (as labelled content) and the outcome back (as a proposal). There is no
   server-to-server coupling and no shared credential.
8. **It is an experiment until measured.** The prior-art survey's conclusion applies here too:
   "each gate is best treated as an experiment". §9 lists what to measure.

**What ships first.** With no backend change: a session takes a `proposed` ADR from the decision
queue, convenes a chamber on it, and files the result as one proposal — the decision text, its
alternatives and consequences, the record registered as a tracked doc with a `basis` link, risks
and follow-up tasks — for the planner to review, edit and apply. That slice needs the hardening
in §4 and the skill in §5.1, nothing else on this side.

---

## 1. Where deliberation would attach today

Stage names follow the document lifecycle canopy already uses (`DocStage`: frame · define ·
design · decide · plan · build · release · learn).

| Stage | canopy today | What is missing | Answer |
|---|---|---|---|
| **Frame** — which problem, which bet | `Initiative.outcome_statement`, `Outcome` (hypothesis + metric), doc kind `research`, leadership notes | No home for options under consideration or open questions above a task; no idea backlog | A discovery brief as a linked doc (§3); ideas as cards on a discovery board (§7) |
| **Decide** — which option | ADR with `context`, `decision`, `consequences`, `alternatives: list[str]`, `reversibility`, stakeholders, `decide_by`; the decision queue; `Project.decision_rule` | Nothing structures how alternatives are examined; dissent, confidence and who was consulted have no field | The record carries them; the ADR links it as basis (§3) |
| **Define / plan** — what, in what order | Specs with criteria, draft plans, proposals with a plan-first preview, three-point estimates on tasks | Nothing challenges a plan before it is applied | A pre-mortem or estimate session revises the open proposal (`revise_proposal`) (§3) |
| **Build** — execution | Work queue; the plan artifact's `confidence` and `open_questions`; `unsettled` decisions in the brief; `question` and `escalation` gates; parking | A low-confidence plan or an unsettled decision routes only to a person, who decides unaided; `open_questions` is stored and read by nothing | Advice attached to the task; a deliberation stage (§6, §7) |
| **Verify** | Review and QA verdicts, the traceability ledger, fitness functions | Nothing prompts a second look at a decision when its verdict is `violated` or `at_risk` | A triage signal (§8) |
| **Learn** | Retrospective (one markdown body), rule suggestions from gate notes and review findings, outcome verdicts | Retro output feeds nothing else: no service reads the body, and follow-ups are created by hand | A retro session files `rule`, `outcome` and `task` items as a proposal (§3) |

---

## 2. Principles

- **D1 — Two records, two owners.** The facilitator owns the deliberation (who said what, in
  which round, on which evidence). canopy owns the decision (what was decided, by whom, its
  status and what implements it). Neither re-keys the other; each holds a link.
- **D2 — Inbound through review.** Everything a deliberation proposes enters through
  `propose_changes`. Direct writes are limited to what `updating-canopy` already allows for a
  change the user dictated in the session: registering the record as a doc they asked to track.
- **D3 — Content, not instructions** (P7). Deliberation text that reaches a brief, a proposal or
  an ADR is content. It never carries policy trust. §4 item H3 closes the one place where it
  could today.
- **D4 — Evidence over assertion** (P8). A facilitator's tally or "the panel agreed" is an
  attestation. canopy shows the link and the summary and does not turn agreement among AI
  personas into a review signal: personas are never `Engineer` rows, never stakeholders, and
  their positions never count toward `can_accept`.
- **D5 — Thin spine.** No new entity until the linked-doc approach has been used and found
  short. "No ceremony that doesn't shorten a loop."
- **D6 — Neutral seams.** canopy names the concept (a deliberation record), not the vendor. The
  facilitator-specific choreography lives in the facilitator's plugin.
- **D7 — Team-level measures only** (P10).

---

## 3. The filing contract (works today, no backend change)

A session that holds a concluded deliberation files it in two calls.

**Step 1 — register the record** (a direct write; the user asked for it):

```
register_design_doc(
  url=<https link to the minutes>, title="Deliberation: <question>", kind="deliberation",
  format="document", summary=<≤2,000 chars: recommendation, strongest dissent, open questions>,
  version=<the record's revision label, e.g. "r2">, content=<minutes text; hashed locally>,
  visibility="users" | "org" | "public", scope_level="project", scope_id=<project id>)
```

An unrecognised host classifies as provider `web` and dedupes on the URL
(`services/doc_urls.py`). The sharing rule (`doc_not_shared`) applies to provider `claude` only,
so the session must itself make sure the link opens for the people who will review it. A new kind
slug is accepted and filed under stage `other` until a planner stages it (§6, B1).

**Step 2 — stage one proposal** with the record as its source:

```
propose_changes(
  scope_level="project", scope_id=<id>,
  title="Decision: <question>",
  summary=<2–5 lines: what was asked, what is recommended, what the dissent is>,
  origin="council · <chamber> · <protocol>",
  source_doc_id=<doc id from step 1>, source_doc_version="r2",
  items=[
    {"entity_type": "decision", "action": "create", "ref": "d1",
     "payload": {"title": ..., "context": ..., "decision": ..., "consequences": ...,
                 "alternatives": ["B — <title>: <one-line case for and against>", ...],
                 "reversibility": "one_way" | "two_way", "decide_by": "YYYY-MM-DD",
                 "decision_owner_id": <engineer id>},
     "reason": ..., "source_kind": "deliberation",
     "source_label": "Council · <chamber> — <session title> (r2)", "source_url": <link>},
    {"entity_type": "doc_link", "action": "create",
     "payload": {"doc_id": <doc id>, "entity_type": "decision", "entity_ref": "d1",
                 "relation": "basis"}},
    {"entity_type": "risk", "action": "create", "payload": {...}},      # one per recorded risk
    {"entity_type": "task", "action": "create", "payload": {...}},      # spikes, follow-ups
    {"entity_type": "blocker", "action": "create",
     "payload": {"task_id": ..., "category": "decision", "reason": ..., "needed_by": ...}}
  ])
```

The reviewer sees "From <doc>, <version>", each item's reason and provenance, the plan-level
preview, and can edit, exclude and apply. `source_kind` is a free string in the model, the schema
and the review UI, so `deliberation` needs no backend change.

**Rules the filing skill enforces.**

- A staged decision always lands `proposed`. Never call `create_adr` with a `status`, and never
  `transition_adr` on a deliberation's behalf.
- Dissent goes in the proposal `summary` and, after apply, in one
  `comment_adr(kind="comment", author_name="Council (advisory)")`. Never a review kind
  (`approve`, `request_changes`, `reject`) and never an `engineer_id`.
- `alternatives` are strings: one per rejected option, the case for and against in a line.
- The doc `summary` is visible to everyone who can see the doc. No personal data, no persona
  names presented as people.
- One proposal per deliberation and per scope. A follow-up revision uses `revise_proposal`.

**Variants.**

| Outcome of | Lands as |
|---|---|
| A debate on a decision that has no ADR yet | The two steps above |
| A debate on an existing `proposed` / `under_discussion` ADR | Step 1 with `links=[{decision, <adr id>, basis}]`; an advisory comment; risks and tasks as a proposal. Text changes to the ADR are made by a person until `decision.update` exists (§6, B2) |
| A pre-mortem or estimate session on an open proposal | `revise_proposal` (durations, added mitigations, three-point estimates) plus `risk.create` items; the record linked to the project as `reference` |
| A discovery or research session | The record as kind `research` or `discovery_brief`, homed at the initiative; `outcome.create` items for hypotheses; candidate decisions as `decision.create` |
| A retro session | The record linked to the retro (`entity_type: "retro"`); `rule.create`, `outcome.update`, `task.create` items |
| Advice on an open gate | A `note` artifact on the task and the record linked to the task; the person answers the gate (§6, P1) |

**Lost in translation today** (and where each goes instead): per-option pros and cons (the
record), dissent as a first-class row (comment and record), confidence and participation (the
doc summary and `origin`), stakeholders and components on a staged decision (set by a person
after apply until B2).

---

## 4. Hardening first

Four existing gaps become more exposed once sessions file decisions in volume. They are not
introduced by this proposal and should land before it.

| # | Gap | Where | Change |
|---|---|---|---|
| H1 | `POST /architecture/adrs` honours a caller-supplied `status` with only `ContributorWriter`. The planner-only rule, the agent one-way-door block and `pin_basis_links` exist only on `PATCH`. An agent token can create an ADR that is already `accepted` | `backend/app/api/v1/architecture.py:309-330` vs `:571-634` | On create, apply the same rules as a transition: a non-planner or an agent token gets `proposed`; `accepted` on create follows the `PATCH` rule and pins basis links. Extend `tests/test_bounded_agency.py` to the create path |
| H2 | `POST /architecture/adrs/{id}/comments` records a formal review (`approve`, `request_changes`, `reject`) under any `engineer_id` the caller supplies | `architecture.py:545-568` | An agent token may post `kind="comment"` only. A review kind requires a human token and an `engineer_id` that is the caller's own engineer (a planner may record on behalf, attributed as such) |
| H3 | The work brief's `decisions` block is `trust: "policy"` and includes the first 600 characters of `unsettled` (proposed, under-discussion) ADRs. Text an agent wrote can reach an implementer as policy before a person accepts it | `backend/app/services/work_brief.py:299-314` | Keep `binding` under `policy`; move `unsettled` to a `content` block. The `on_conflict` rule stays policy |
| H4 | The MCP client raises on any non-2xx with `raise_for_status()`, so the body — `invalid_items` with per-item errors, `doc_not_shared`, `feature_disabled`, the human-only message — never reaches the model for most tools. A multi-item filing cannot self-correct | `plugin/mcp_server/client.py:103` | Raise an error that carries `status_code`, `code` and `detail`; return it as data the way `tools/work.py:_refusal` already does |

Related, lower priority: plugin subagents list tools as `mcp__canopy__…`, while a plugin-bundled
server exposes `mcp__plugin_canopy_canopy__…` (the hooks already address it as
`plugin:canopy:canopy`). By the current Claude Code documentation the seven allow-listed
subagents would have no canopy tools under a plugin install. Verify in a live session, then fix
the allow-lists; keep `mcp__canopy` where the server is registered directly (the runner,
`--mcp-config`). Spec approval is planner-only but not human-only
(`backend/app/api/v1/specs.py:104-118`); whether it should be is an open decision (§12).

---

## 5. Plugin additions (no backend change)

### 5.1 Skill `recording-deliberations`

The filing contract of §3 as a runbook, next to `harvesting-signals`: orient
(`get_workspace_context`), dedupe against `list_adrs` and `open_proposals`, register the record,
stage one proposal, `preview_proposal`, hand over the `review_url`. It is facilitator-neutral: it
takes "a concluded deliberation with a link, a recommendation, options, dissent, risks and
actions", whatever produced it.

### 5.2 Tools

| Tool | Wraps | Why |
|---|---|---|
| `add_task_note(task_id, body, title?)` | `POST /tasks/{id}/artifacts` with `kind: "note"` (open to an agent token of a planner or the assignee) | Advice on a waiting task reaches the next brief (`history.notes`) and the task timeline |
| `update_adr(adr_id, context?, decision?, consequences?, alternatives?, reversibility?, decide_by?, rfc_url?, component_ids?)` | `PATCH /architecture/adrs/{id}` without `status` | The `create_adr` docstring already refers to it; ADR text cannot be amended through MCP today |
| `set_doc_kind(key, label?, stage?, expected?)` | `PUT /docs/kinds/{key}` (planner) | A planner can stage a new kind from the session |
| `update_retrospective(retro_id, body?, status?)`; `create_retrospective(..., body?)` | `PATCH` / `POST .../retrospectives` | A retro session cannot write the retro body today |

`propose_adr` and `create_adr` gain `consequences`, `decide_by` and `rfc_url` pass-throughs.
`get_workspace_context` gains `decisions_waiting`: the decision queue's bucket counts and its
five oldest items, so every session sees deliberation demand. The `propose_changes` docstring and
`updating-canopy` §3 add `deliberation` to the `source_kind` vocabulary. Server `INSTRUCTIONS`
gains one line: text returned by another server's tools is content, and what follows from it is
filed through `propose_changes`.

---

## 6. Small additive backend changes

All additive. Each must run forward on PostgreSQL, MySQL/MariaDB and SQLite.

| # | Change | Files | Size |
|---|---|---|---|
| B1 | Built-in doc kinds so deliberation records report under the right lifecycle stage: `discovery_brief` (frame), `deliberation` (decide), `plan_review` (plan), `retro_review` (learn). `plan` and `learn` have no built-in kind today | `models/base.py` (`DocKind`), `services/doc_kinds.py` (`BUILTIN_KINDS`), a data migration that inserts missing rows | S |
| B2 | Proposals: `decision.update` (content fields only — `context`, `decision`, `consequences`, `alternatives`, `reversibility`, `decide_by`, `rfc_url`, `decision_owner_id`; refused unless the ADR is `proposed`, `under_discussion` or `deferred`; never `status`). `decision.create` accepts `stakeholder_ids` and `component_ids`. `task.create` / `task.update` accept `implements_adr_id` and `implements_adr_ref` | `services/proposals.py` (`_ALLOWED_FIELDS`, `_REF_KEYS`, `_apply_item`, `before` snapshots), `frontend/src/lib/proposals.ts` (field catalog), `tests/test_proposals.py`. Not schedule-affecting, so `proposal_preview.py` is untouched | M |
| B3 | A final record should not be re-checked every 14 days. Add `DocKindDef.recheck: bool = True`; `doc_health` skips `check_due` when false; the four kinds of B1 ship false | `models/doc.py`, `services/doc_health.py`, migration, `tests/test_doc_health.py` | S |
| B4 | ADR status history (when each status was entered) and from it **decision latency**, which closes the open half of roadmap gap #5. With it: an SSE `decision` event and outbound `decision.proposed` / `decision.stuck`. Today the queue ages from `created_at` and nothing is published for an ADR | new `ADRStatusHistory` model written by the ADR status path, `services/decisions.py`, `core/events.py`, `services/notify.py`, initiative cockpit | M |
| B5 | Stage-policy condition `open_questions`: a plan that lists open questions asks for approval. The field is stored and read by nothing today | `services/stage_policy.py` (conditions), `services/gates.py` (`ConditionFacts`), tests | S |
| B6 | The gate page shows the task's `note` artifacts and linked docs beside the question, so advice is in front of the person deciding. It renders the subject artifact, the hand-off and the reviews today | `frontend/src/pages/GateReview.tsx`, no API change | S |

Deliberately not proposed: structured options, dissent or confidence columns on
`ArchitectureDecision`. They live in the record. If filed decisions prove unreadable without
them, the first step is rendering the linked record's summary on the ADR page, not widening the
model.

---

## 7. Deliberation as work

A decision that blocks delivery is already visible to the queue: it appears in the brief as
`decisions.unsettled`, as a plan-gate reason, and as blockers with `category="decision"`. The
missing piece is a place where an agent session may *work* on it before a person decides. Stage
policy supports this without new concepts: `worked_by` accepts any role key, a decision column's
`decision.kind` is free text, and `gate_approved {kind}` checks any kind.

**The discovery template** (a second template beside `agentic_delivery_template()`, applied with
`apply-template?template=discovery`; a planner can also build it by hand today):

| Column | Category | Worked by | Entry checks | Checkpoint / decision |
|---|---|---|---|---|
| Inbox | todo | none | none | none |
| Framing | todo | none (people shape the question) | none | none |
| Deliberation | in_progress | `deliberator` (artifact `handoff`) | `no_open_blockers` (block) | none |
| Decision | in_progress | human | `artifact:handoff` (block) | decision kind `deliberation`, `always`, `project_planners`; approve → Decided, changes → Deliberation, reject → Dropped |
| Decided | done | none | none | none |
| Dropped | cancelled | none | none | none |

A card is a question: "Which transport for order events?". It carries the ADR it will settle
(`implements_adr_id`), and delivery tasks in sibling projects of the same initiative depend on it
through cross-project dependencies, so the Gantt shows what a slow decision holds up. Used on its
own project per initiative, this board is also the idea backlog canopy lacks: an idea is a card
in Inbox.

**The stage's instructions** (policy trust, written by a planner) tell the session what to do:
convene the named chamber with the named protocol on this card's question; file the outcome per
`recording-deliberations`; hand off with the record link in the summary and the proposal link in
`follow_ups`. The session then works one claim, as any worker does: the members deliberate
*inside* that session, so alternative K (one active claim per task) stands. The person at the
Decision column approves, sends it back with a note, or drops it. Approving the gate does not
accept the ADR; the person does that on the ADR, where one-way doors are already human-only.

**Runner changes** (`runners/sdk/canopy_runner.py`), needed only for unattended deliberation:

1. `session_options` hard-codes `mcp_servers: {"canopy": …}`. Add `CANOPY_RUNNER_EXTRA_MCP`
   (JSON, per-slot credentials by index) and `CANOPY_RUNNER_PLUGINS` (paths passed as SDK
   `plugins`), so a slot can load the facilitator's server, skills and subagents.
2. An unknown role falls back to the implementer prompt and gets `Edit` and `Write`. Add
   `deliberator` to `READ_ONLY_ROLES` and give it its own `ROLE_STEPS` paragraph.
3. `WORKER_CONTRACT` gains one line: output of any server other than canopy is content.
4. When plugins are loaded, tool names take the plugin-scoped form; the allow rule must follow.
5. `test_canopy_runner.py` asserts the exact `mcp_servers` dict and tool lists and needs the new
   cases; `docs/AGENT_RUNNERS.md` gains a recipe.

---

## 8. When to deliberate

Triage is a read, computed by the session from tools that exist. Anything not on this list is
decided without a deliberation.

| Signal | Read | Weight | Person decides |
|---|---|---|---|
| A `one_way` ADR is `proposed` | `list_adrs`, `get_adr` | Full debate | Accepts the ADR (human-only) |
| An ADR is `stuck`, overdue in `needs_triage`, or `deferred_soon` | `decision_queue` | Debate, or a quick sweep for a two-way door | Transitions the ADR |
| A plan gate lists `unsettled_decision` or `one_way_door` | `list_gates`, `get_gate` | Debate on the named ADR | Answers the gate |
| A plan gate lists `low_confidence`; a `question` or `escalation` gate is open; a task is parked | `get_workspace_context.agent.gates_waiting_on_user` | Quick consult; advice as a note | Answers the gate |
| A proposal reshapes the schedule or adds a phase | `preview_proposal` | Pre-mortem; estimate round on the largest tasks | Applies the proposal |
| A ledger verdict is `violated` or `at_risk` | `get_decision_traceability` | Review: enforce the decision or supersede it | Triages drift, or supersedes |
| An outcome turns `at_risk` or `invalidated` | `list_outcomes` | Discovery session on the bet | Re-frames or stops the bet |
| A retro is created | `list_retrospectives` | Retro session | Applies the resulting proposal |

---

## 9. Measures

Team-level, never per person, and reported with `sufficient=false` when thin.

- **Decision latency**: time from `proposed` to `accepted` or `rejected`, for decisions with and
  without a basis deliberation record. Needs B4.
- **Coverage**: share of accepted `one_way` ADRs that have a `basis` doc of stage `decide`.
- **Review effort**: for proposals whose `origin` names a deliberation — applied as staged,
  applied with overrides or exclusions, rejected. An apply rate near 100% with no edits is a
  reason to lighten the protocol; a high reject rate is a reason to stop.
- **Durability**: accepted ADRs superseded within 90 days, with and without a record.
- **Gate age**: time to decision for advised and unadvised `question` and `plan_approval` gates.

---

## 10. Permissions, feature gates, flows

- **Permissions.** Unchanged. Staging is open to agent tokens; apply is planner and human-only;
  accepting a one-way door is human-only; deciding a gate is human-only. H1 and H2 remove the two
  ways around this.
- **Feature gates.** None new for §5 and B1–B3: the affected routers are already gated
  (`ai.proposals`, `governance.docs`, `architecture`). B4's events ride `integrations.outbound`.
  The discovery template rides `ai.stage_policy`. A dedicated `ai.deliberation` gate is warranted
  only if a UI affordance is added ("Request deliberation" on an ADR).
- **USER_FLOWS** when built: a new section (code `AC`) for the filing flow and the discovery
  template; edits to §A6 (H1, H2), §G2–G3 (`update_adr`, comment rule), §V5 (kinds), §AA1
  (`decision.update`, vocabulary), §AE6 (template, condition), §AE11 (runner), §L (skill and
  tools), and a bullet in "Source-of-truth boundaries": *a facilitator owns the deliberation;
  canopy keeps a link, a summary and a version, and files what follows from it as a proposal.*

---

## 11. Rollout

| Phase | Contents | Depends on |
|---|---|---|
| **D0 — Hardening** | H1–H4; verify and fix the subagent tool prefix | — |
| **D1 — Filing** | Skill `recording-deliberations`; tools of §5.2; vocabulary; `decisions_waiting` | D0 |
| **D2 — Fit** | B1, B2, B3 | D1 used on real decisions |
| **D3 — Deliberation as work** | Discovery template; runner changes; B5, B6 | D1; the facilitator's unattended mode |
| **D4 — Measures** | B4 and §9 on the initiative cockpit | D2 |

**Test plan.** `test_bounded_agency.py`: an agent token cannot create an `accepted` ADR, cannot
post a review kind, and a human cannot post a review as another engineer. `test_proposals.py`:
`decision.update` whitelist, status refusal, stale detection, `implements_adr_ref` ordering.
`test_doc_health.py`: `recheck=false` suppresses `check_due` only. Work-brief test: an unsettled
ADR's text is under `content`. Plugin: the client surfaces `code` and per-item errors; CI's
existing "every hook tool is registered" check extends to "every tool named in a skill or
subagent is registered". Runner: extra servers, plugin loading, `deliberator` is read-only.
`test_demo_seed.py`: one seeded deliberation record with a basis link, so the UI surface has
data. Demo content stays fictional.

---

## 12. Alternatives considered

- **Build deliberation into canopy** (personas, rounds, a chat surface). Rejected: canopy calls
  no model and has "no chat box in the UI; the conversation stays in the person's own Claude
  session".
- **A `Deliberation` entity** (question, scope, status requested → in session → concluded,
  recommendation, dissent, confidence). Deferred under D5. The doc graph gives link, version,
  pin and staleness; the queue gives requested → in progress → decided. Revisit if people ask to
  filter or report on deliberations as such.
- **Pairing through `ExternalRef`** with a new provider. Rejected for now: no endpoint or tool
  reads or writes arbitrary refs, and a `DocLink` already gives the reverse lookup.
- **Server-to-server**: canopy posting "decision needed" to the facilitator, or the facilitator
  writing to canopy's API. Rejected for the first phases: it needs a shared credential and puts
  agent-written text into canopy without a session's token scope. B4's outbound events allow it
  later for *notification* only.
- **Parallel roles on one column** so several reviewers hold one task. Unnecessary: the parallel
  perspectives run inside one claim.
- **Personas as stakeholders** whose approvals count toward `can_accept`. Rejected under D4 and
  P5.

---

## 13. Open decisions

| # | Decision | Recommendation |
|---|---|---|
| 1 | Should `source_kind` for a filed deliberation be `deliberation` (the medium) or the facilitator's name? | `deliberation`, with the facilitator in `source_label` |
| 2 | Ship the four doc kinds as built-ins (B1) or leave them as data a planner stages? | Built-ins: stage reporting should not depend on a manual step |
| 3 | Should approving a spec be human-only, like approving a design doc? | Yes; decide separately from this proposal |
| 4 | Discovery as its own project per initiative, or as two extra columns on a delivery workflow? | Its own project: it keeps WIP limits and flow metrics honest for both tracks |
| 5 | Where should minutes live when the facilitator has no team sharing: an unlisted facilitator link, a repo file, or a Claude Doc? | The team's choice per workspace; canopy treats all three as a doc link |
| 6 | Is B4 (ADR status history) in scope here or its own change? | Its own change; it is the prerequisite for measuring any of this |
