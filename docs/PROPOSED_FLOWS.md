# Canopy — Proposed Revision & Extension of User Flows

> **Status: proposal, not yet built.** This document critiques the flows in
> [`USER_FLOWS.md`](./USER_FLOWS.md) and proposes a revised + extended set. `USER_FLOWS.md`
> remains the source of truth for what *is* implemented; this file is the source of intent for
> what *should* change. Each proposal names the UI surface, the API, and the MCP tool so it can be
> lifted straight into `USER_FLOWS.md` as it lands.
>
> Companion doc: [`EXECUTION_PHILOSOPHY.md`](./EXECUTION_PHILOSOPHY.md) — the *why* behind these
> changes (the operating model for high-velocity, high-quality delivery). This doc is the *what*.

---

## 0. The core critique (read this first)

Canopy is unusually complete on the **visibility** axis — Gantt/CPM, dependency graph, capacity
heatmap, first-class decisions with a lifecycle, an architecture map, drift detection, a risk
score, retros, burndown, an activity feed, plus a 45-tool MCP surface with skills and subagents.
That breadth is real and worth defending. But measured against the brief — *an architect guiding a
team that executes **concurrently, decentrally** across **sub-projects**, with **maximum agility**
and **high quality*** — six structural problems hold the product back. Every proposal below traces
to one of these.

| # | Problem | Evidence in the code | Consequence |
|---|---------|----------------------|-------------|
| **C1** | **No layer above `Project`.** The unit of management is a single project; the portfolio is a flat list. | No `Initiative`/`Program` model; `GET /projects/portfolio` is a flat array; no cross-project dependencies (`grep` finds none). | The architect's actual unit of work — the *initiative spanning sub-projects* — has no home. Cross-project sequencing and contention are invisible. |
| **C2** | **Capacity is per-project only.** | `GET /team/capacity` *requires* `project_id`; the heatmap is one project at a time. | The most dangerous overload — one engineer at 50% on three projects (=150%) — is structurally invisible. The EM persona is under-served exactly where it matters. |
| **C3** | **The planning spine is deterministic (CPM/baseline/drift-from-baseline), bolted onto agile data.** | `scheduling.py` is a forward/backward CPM pass in working-days; baselines + Gantt drift overlay; tasks carry `duration` in days. | CPM assumes known durations. Knowledge work doesn't have them. The plan is precise-but-wrong; "drift from baseline" punishes the agility the brief asks for. |
| **C4** | **The MCP surface is read-rich, write-poor.** | 45 tools, but no `update_task`/`assign_task`, no `create_allocation`, no `create_project`, no `list_adrs` (the `pr-to-adr-linker` skill calls a `canopy:list_adrs` that **doesn't exist**). | Claude can *see* everything and *act* on almost nothing tactical. "Maximum agility through the conversational front door" is blocked. |
| **C5** | **Risk is mostly lagging, manual, and mis-treats missing signal.** | Risk snapshots are captured on demand (`POST .../risk/snapshot`), not nightly; the **quality family renormalizes away when a project has no observability events** (`risk.py`). | A blind project scores *less* risky than an observed one. Absence of signal ≠ absence of risk. The trend that matters most isn't being collected. |
| **C6** | **Coherence is asserted, not verified or closed-loop.** | Drift is manual + Python-only + open-loop (no CI/webhook trigger; bindings hand-maintained); "unimplemented ADR" is proxied by "components show no commits"; `can_accept` is advisory; no decision→work→verification link. | The headline promise — *no drift between architecture and implementation* — degrades to a stale, best-effort snapshot. Decisions and the code that's meant to honor them never close the loop. |

The rest of this document is organized as **(I) revisions to existing flows**, keyed to the
sections in `USER_FLOWS.md`, and **(II) net-new flows**. A consolidated **MCP additions table** and
a **sequenced rollout** close it out.

---

# Part I — Revisions to existing flows

## A. Authentication & access → make the **engineer** a first-class operator

Today engineers are barely-present (`/me`, `/me/today`) and write access is mostly planner-gated
(§A3a). For *decentralized* execution the engineer has to be able to *act*, not just *view*.

- **A-R1 — Engineer self-service (`/onboarding`).** Promote the deferred §A5 flow to built: an
  engineer linked to a login confirms their own timezone, working hours, skills, and PTO. This is
  the data the capacity model needs and the architect should not be hand-maintaining it.
  - UI `/onboarding` · API `PATCH /me/profile` · MCP `update_my_profile`.
- **A-R2 — Own-allocation & availability carve-out.** Close the §A3a "not enforced yet" gap: an
  engineer may set their own PTO/availability and adjust their own allocation within a planner-set
  ceiling. PTO must feed the working calendar (see C-R3).
  - API `POST /me/availability` (PTO ranges) · MCP `set_my_availability`.
- **A-R3 — Keep decision gates advisory by default, but make one-way doors enforceable.** See
  G-R3; the access model already distinguishes planner vs engineer — extend it so a one-way-door
  ADR *can* require explicit owner sign-off before dependent work is marked ready.

## B. Projects & portfolio → an **Initiative/Program** layer (addresses C1)

The single most important structural change. Introduce `Initiative` (a.k.a. Program) as the parent
of `Project`. The architect manages the initiative; sub-projects are how teams execute it
concurrently.

- **B-R1 — Initiative model & dashboard. ✅ Shipped (first slice).** `Initiative { key, name,
  outcome_statement, start/target dates, owner }` with `Project.initiative_id`.
  - UI `/initiatives` (list + create) and `/initiatives/:id` (rolled-up health: progress, **worst**
    sub-project risk + drift, open-decision backlog, on-track-vs-target, sub-project cards) · API
    `GET/POST/PATCH/DELETE /initiatives`, `GET /initiatives/{id}/rollup` · MCP `list_initiatives`,
    `create_initiative`, `get_initiative_rollup`, `set_project_initiative`. The rollup reuses the
    portfolio's `summarize_project`.
  - **Still pending:** the **cross-project critical path** on the cockpit needs cross-project
    dependencies (D-R1) — the next slice.
- **B-R2 — Outcome-first portfolio.** Revise §B1: the portfolio card leads with the **outcome** and
  a **confidence-to-hit-the-window** band (from forecasting, C-R1), not just avg-%-complete. Add the
  promised sortable columns + last-decision recency (the §B1 "not built").
- **B-R3 — Project as a *bet*, not just a container.** Each project carries a one-line hypothesis
  ("we believe X will yield Y, measured by Z"). Surfaced on the cockpit header and in retros (it's
  the thing a retro evaluates). API: add `hypothesis`, `success_metric` to `PATCH /projects/{id}`.
- **B-R4 — Close the §B4 UI gap.** Project rename/archive/date edits are API-only today; put them
  in the UI. Trivial, but it's a daily papercut.

## C. Work breakdown & scheduling → **flow + probabilistic forecast** alongside CPM (addresses C3)

Keep CPM — it's genuinely useful for hard-sequenced, well-estimated work (a launch runbook, a
migration cutover). But stop treating it as *the* spine. Add the flow lens the brief actually needs.

- **C-R1 — Probabilistic forecast. ✅ Shipped.** Alongside the CPM date, a **Monte-Carlo forecast**
  from the team's historical weekly **throughput** reports **P50 / P85** completion dates — the
  honest answer to "when will it ship?" for knowledge work, embracing uncertainty instead of faking
  precision. Insufficient (with a reason) until ~3 weeks of throughput exist.
  - Service `app/services/forecast.py` (pure, unit-tested) · API `GET /projects/{id}/forecast` and
    `GET /initiatives/{id}/forecast` · MCP `get_forecast`.
  - UI: a forecast card on the Gantt tab and a **P85** stat on the initiative cockpit.
  - *Still open:* surfacing it on the portfolio cards (N forecasts is expensive — deferred);
    cycle-time-based forecasting as an alternative to throughput.
- **C-R2 — Flow board + WIP + aging. ✅ Shipped.** A **Board** tab groups leaf tasks into status
  lanes (from Jira) with **WIP** per lane and an **aging** highlight (in-status age > the team's
  cycle-time P85). `GET /projects/{id}/board` (pure `flow.py`; dates from `TaskStatusHistory`) ·
  MCP `get_board`. Status stays Jira-owned/read-only.
  - *Still open:* **persisted** per-lane/per-engineer WIP limits (the limit is a client-side knob
    for now); drag-to-change.
- **C-R3 — PTO & calendars feed CPM *and* forecast.** Promote the deferred §F "PTO→CPM" item: the
  `WorkingCalendar` already skips weekends + holidays; extend it to per-engineer availability
  (A-R2). A plan that ignores who's actually out is not a plan.
- **C-R4 — Re-baseline as a deliberate, logged act — and reframe "drift." ✅ Shipped.** Schedule
  "drift-from-baseline" is renamed **schedule variance** throughout (risk indicator copy, Gantt
  overlay, docs); "drift" now means *architecture* drift only (§N). Re-baselining takes an optional
  **note** and is logged as a `Baseline` event (`POST .../baseline` → `GET .../baselines`), shown in
  a **Baseline history** panel under the Gantt — re-planning is a feature, not a failure, so the
  reset of the plan-of-record carries its reason and a trail. (`models.Baseline` + migration;
  `set_baseline` MCP takes a note.)
- **C-R5 — `update_task` everywhere.** `PATCH /tasks/{id}` exists (with the own-task guard) but has
  **no MCP tool**. Add `update_task` (duration, dates, deadline, parent) and `assign_task`
  (assignee) so Claude can act tactically — see C4 / the MCP table.

## D. Dependencies → typed, **cross-project**, and **blocker-aware** (addresses C1)

- **D-R1 — Cross-project dependencies. ✅ Shipped.** A dependency edge may link tasks in different
  projects of the **same initiative** (rejected otherwise, 400); `GET /initiatives/{id}/critical-path`
  computes the **cross-project critical path** at the initiative level (reusing `compute_cpm` over
  the union graph) and surfaces the cross-project **hand-offs** — the between-team dependencies most
  likely to slip — on the initiative cockpit. Per-project replan stays project-local. (`get_initiative_critical_path` MCP.)
- **D-R2 — Live blockers as a first-class signal. ✅ Shipped.** `Blocker { task_id, reason,
  raised_by_engineer_id, blocking_task_id?, created_at(opened), resolved_at }`. An engineer raises a
  blocker from `/me`; open blockers surface in the workspace and the project alerts digest.
  - UI: "Flag a blocker" + resolve on `/me` · API `POST /tasks/{id}/blockers`,
    `GET /blockers?project_id=&open_only=`, `PATCH /blockers/{id}`, `DELETE /blockers/{id}` · MCP
    `raise_blocker`, `list_blockers`, `resolve_blocker`.
  - *Still open:* the **red halo** on the dependency-graph/Gantt node and folding **blocked-time**
    into the composite risk score (Q-R2) — for now blockers show in the lagging alerts digest.
- **D-R3 — UI for non-FS links + lag.** Today the UI only creates FS links (§C2/D); expose SS/FF/SF
  + lag in the form (the API/MCP already support them).

## F. Team & capacity → **cross-project, hours-based, and reality-checked** (addresses C2)

This is the EM's surface and it's currently the weakest quantitative one.

- **F-R1 — Org-wide capacity (the C2 fix). ✅ Shipped.** `project_id` is now optional on
  `GET /team/capacity`; omitted, it returns each engineer's allocation **summed across all
  projects**, with the contributing project keys per row (rows split across >1 project are
  flagged). Over-allocation that spans projects — the overload that actually bites — is now visible.
  - API: `GET /team/capacity` (project_id optional; response `project_id` may be `null`, rows carry
    `projects`) · MCP `get_capacity(project_id=None)`.
  - UI: a "Capacity across all projects" grid on `/team`. (Still to come: surfacing it on the
    future initiative dashboard, R.)
- **F-R2 — Allocation via MCP + hours model.** Add `allocate_engineer` MCP (there's a `POST
  /team/allocations` endpoint but no tool — C4). Then begin the deferred §F2 hours model: allocation
  in committed hours/week (already a field on `Engineer`) with an explicit **interrupt budget**
  (on-call/support reserve) so "100% allocated" stops meaning "100% productive."
- **F-R3 — Reality-check capacity against actual throughput.** The GitHub connector already reads
  PRs; feed **observed** signal (merged PRs, review load, WIP) next to the *planned* allocation so
  the architect sees planned-vs-realized. A grid that's hand-typed percentages is a guess; a grid
  cross-checked against real activity is evidence. (Needs PR metrics — see J-R1.)
- **F-R4 — Skill-fit hints.** `skill_tags` exist on engineers but feed nothing. When assigning a
  task, surface candidates ranked by skill overlap (cheap, pure, high-leverage for the architect).

## G. Architecture & decisions → **close the decision→implementation→verification loop** (addresses C6)

The decision model is the best part of the product. The gap is *traceability* and *enforcement*.

- **G-R1 — Decision → work → verification spine.** Let an ADR spawn and own its implementing tasks
  (`Task.implements_adr_id`) and its **fitness function** (a machine-checkable assertion — e.g. "no
  module under `app.api` imports `app.connectors` directly"). The ADR's status then reflects
  *reality*: `accepted` but fitness-failing = the drift queue's strongest signal, far better than the
  current "components show no commits" proxy for "unimplemented."
  - API `POST /architecture/adrs/{id}/fitness` (declare a check), the drift scan evaluates it ·
    MCP `add_adr_fitness`, surfaced in `get_adr`.
- **G-R2 — The missing `list_adrs` MCP tool (a real bug).** The `pr-to-adr-linker` skill calls
  `canopy:list_adrs` "if available" — it is **not** available, though `GET /architecture/adrs`
  exists. Add the tool. Without it, the PR-to-ADR-linker can't reliably do step 3.
- **G-R3 — Enforceable gates for one-way doors only.** Keep `can_accept` advisory for two-way-door
  decisions (reversible — bias to action). For `reversibility = one_way`, make the gate real:
  acceptance requires the configured rule to be *met* (owner override allowed but logged with a
  reason). Irreversible decisions deserve friction; reversible ones must not.
- **G-R4 — Decision latency as a tracked metric.** The queue already buckets stuck/deferred items;
  surface **time-in-state** and a rolling **decision-latency** metric on the initiative dashboard.
  Slow decisions are the silent killer of decentralized teams — make the cost visible.
- **G-R5 — `whatif_supersede` preview.** Promote the §G5 "not built": before superseding an ADR,
  preview the blast radius of the *replacement* (which components/tasks/other ADRs are affected).

## I + Q. Alerts & risk → **leading-indicator-first, confidence-aware, auto-captured** (addresses C5)

- **Q-R1 — Fix the renormalization trap. ✅ Shipped.** Previously, a project with no observability
  events had its quality family *excluded* and the score renormalized — so a **blind** project
  looked **safer**. Now the quality family always scores: with no events it surfaces an explicit
  **Observability coverage** indicator and the risk response carries `confidence: "low"` with a note,
  shown as a "Low confidence — flying blind" banner on the Risk tab. A blind project is flagged, not
  silently scored as safe. (`risk.py` + `RiskResponse.confidence` + `RiskView`; `get_risk` and the
  risk-analyst agent updated.)
- **Q-R2 — Promote true leading indicators.** Add (and weight toward) **blocked-time** (D-R2),
  **WIP/aging** (C-R2), **cycle-time trend**, **PR review latency** (J-R1), and **decision latency**
  (G-R4). The current families lean lagging (burndown, deadline-missed, drift-after-the-fact).
  Leading indicators are what let the architect act *before* the slip.
- **Q-R3 — Auto-capture the risk snapshot. ✅ Shipped.** The arq worker runs a nightly cron
  (`capture_risk_snapshots` → `run_risk_snapshots`) that snapshots every project, so `risk/timeline`
  is a real trend instead of only on-demand points.
- **Q-R4 — Mitigation follow-ups actually follow up.** Promote the §Q4 "not built": a mitigation
  past its `check_in` date raises its own (gentle) alert and pings the owner. An acknowledged risk
  with no follow-through is worse than an unacknowledged one.

## N. Architecture drift → **continuous, CI-triggered, multi-signal** (addresses C6)

Drift is the differentiator; today it's the most fragile flow (manual, Python-only, open-loop).

- **N-R1 — Close the loop: drift staleness. ◐ Partly shipped.** Every scan is now logged
  (`DriftScan`); `GET .../drift` returns `last_scanned_at` + `scan_due`, and the Drift tab shows a
  "scan due" badge when bindings exist but the scan is missing or >7 days old — so stale drift is
  *surfaced* instead of silently forgotten. **Remaining:** a GitHub push/merge webhook that
  *enqueues* the Drift Sentinel (the server can't crawl code itself, so the actual scan stays
  agent-driven; the webhook→agent trigger is the open piece).
- **N-R2 — Beyond the import graph.** Structural/import drift is necessary, not sufficient.
  Architectural coherence also means **contract drift** (API schema / event-payload changes vs. the
  declared interface) and **fitness-function drift** (G-R1). Add these as drift signal kinds. A team
  can keep every import legal and still break the architecture.
- **N-R3 — Suppression-management UI + non-Python analyzers.** Promote the §N4 "not built":
  per-project suppression management (today false-positives are only stored), and pluggable
  analyzers beyond Python `ast` (the edge-mapping is already language-agnostic — the parser isn't).

## L. Claude plugin → **write-parity + a tighter agent loop** (addresses C4)

The agentic flows are a genuine strength. The constraint is the write-poor tool surface.

- **L-R1 — Write-parity tools.** Add the verbs Claude needs to *act*: `update_task`, `assign_task`,
  `allocate_engineer`, `create_project`, `list_adrs`, `add_adr_fitness`, `raise_blocker`,
  `set_decision_rule`, `list_milestones`, `record_risk_snapshot`. (Full list in the MCP table.)
  Today the conversational front door can plan from scratch but can't make the small tactical edits
  that *are* day-to-day management.
- **L-R2 — A "morning standup" skill.** A `daily-standup` skill that synthesizes, per initiative:
  what moved, what's blocked (D-R2), decisions awaiting the architect, drift opened overnight (N-R1),
  and the one thing most likely to slip the date (forecast, C-R1). This is the single highest-value
  recurring surface and it composes existing tools.
- **L-R3 — Guardrails for *agentic* code changes.** As Claude increasingly writes the code (not just
  the plan), every agent-authored PR should auto-run the PR-to-ADR linker (§L10) and the fitness
  functions (G-R1) before a human looks. Make the agent's own output subject to the same coherence
  checks as a human's. (See `EXECUTION_PHILOSOPHY.md` §7.)
- **L-R4 — Fix CLAUDE.md staleness.** A minor but telling drift: `CLAUDE.md` says "~26" MCP tools;
  there are **45**. The doc that governs the agents is itself drifting from reality — exactly the
  failure mode the product exists to prevent.

## M. Engineer workspace → **blockers, dependencies, and self-service** (addresses C1/decentralization)

- **M-R1 — "Who's blocking me / who am I blocking."** `/me` shows tasks + decisions but not the
  engineer's **dependency neighborhood**. For decentralized execution the most useful thing an
  engineer can see is the two-hop graph around their work and a one-click "flag blocker" (D-R2).
- **M-R2 — Update progress from the UI.** Engineers can `PATCH` their own task via API (§A3a) but
  there's no UI for it. Give `/me` an inline progress/estimate-remaining control — the input that
  feeds the forecast (C-R1) and burndown.
- **M-R3 — PRs awaiting my review.** Promote the §M "not built": surface review load on `/me` (needs
  J-R1). Review latency is a top throughput constraint and it lives here.

---

# Part II — Net-new flows

## R. Initiative cockpit (the new top of the app)
The home for the architect. Rolls up sub-projects (C1): combined forecast + confidence (C-R1),
cross-project critical path (D-R1), org capacity (F-R1), decision latency (G-R4), open drift across
projects (N-R1), and the initiative's outcome/hypothesis (B-R3). Replaces the flat portfolio as the
landing page for anyone managing more than one project.

## S. Flow & delivery metrics (DORA + flow)
A metrics surface the product currently lacks despite having most of the inputs: **deployment
frequency, lead time for change, change-fail rate, MTTR** (from §J8 activity events) plus **flow
metrics** (WIP, cycle time, throughput, flow efficiency = active ÷ elapsed). These are the
quantitative backbone of `EXECUTION_PHILOSOPHY.md`. UI: an initiative-level **Delivery** tab;
service `app/services/flow_metrics.py` (pure); MCP `get_delivery_metrics`.

## T. Decision-to-code traceability ledger
A read view answering "for decision X, what implemented it and is it still honored?" — joining ADR →
implementing tasks (G-R1) → PRs (J-R1, via the PR-to-ADR linker) → fitness-function status (G-R1) →
drift events (N). This *is* "no drift between architecture and implementation," made concrete and
queryable instead of asserted. UI: a panel on the Decisions tab; MCP `get_decision_traceability`.

## U. Definition-of-Done as policy
A per-project/per-initiative editable **DoD checklist** (tests, ADR if architecturally significant,
observability/telemetry added, docs/USER_FLOWS updated, fitness functions pass). Surfaced on tasks
and enforced softly at PR time via the linker. Encodes the quality bar as data, not folklore — the
operational half of `EXECUTION_PHILOSOPHY.md` §5.

---

## Consolidated MCP additions (closes C4)

Existing surface = 45 read-rich tools. These add the **write/act** and **forecast** verbs that make
the conversational front door able to *manage*, not just *report*. (★ = unblocks an existing skill
or fixes a referenced-but-missing tool.)

| Tool | Maps to | Why it's needed |
|------|---------|-----------------|
| `update_task` ✅ | `PATCH /tasks/{id}` | Tactical edits (name/duration/dates/deadline/percent/parent). **Shipped** (status stays Jira-read-only). |
| `assign_task` ✅ | `PATCH /tasks/{id}` (assignee) | Reassign work — the most common tactical move. **Shipped** (set/clear assignee). |
| `allocate_engineer` ✅ | `POST /team/allocations` | Staffing changes. **Shipped.** |
| `get_capacity` *(extend)* ✅ | `GET /team/capacity?project_id=` | `project_id` now optional → **org-wide** capacity. **Shipped** (C2). |
| `list_adrs` ✅★ | `GET /architecture/adrs` | **Bug fixed:** `pr-to-adr-linker` called a tool that didn't exist. **Shipped.** |
| `create_project` ✅ | `POST /projects` | Let Claude bootstrap a project conversationally. **Shipped.** |
| `set_decision_rule` | `PATCH /projects/{id}` | Tune the decision policy (owner/consensus/lazy). |
| `list_milestones` | `GET /milestones?project_id=` | Read milestones (only `create_milestone` exists). |
| `raise_blocker` / `resolve_blocker` / `list_blockers` ✅ | `…/blockers` | The blocker signal (D-R2). **Shipped.** |
| `get_forecast` ✅ | `GET /projects\|initiatives/{id}/forecast` | Probabilistic delivery date (C-R1). **Shipped.** |
| `get_delivery_metrics` | `GET …/delivery` | DORA + flow metrics (S). |
| `add_adr_fitness` | `POST .../adrs/{id}/fitness` | Machine-checkable decision (G-R1). |
| `get_decision_traceability` | `GET …/traceability` | Decision→code loop (T). |
| `list_initiatives` / `create_initiative` / `get_initiative_rollup` / `set_project_initiative` / `get_initiative_critical_path` ✅ | `/initiatives` | The C1 layer + cross-project critical path. **Shipped.** |
| `record_risk_snapshot` | `POST .../risk/snapshot` | Let the morning agent capture the trend (Q-R3). |

---

## Sequenced rollout (what to build, in what order)

**Now (unblocks the brief's core promise; mostly leverages existing endpoints):**
1. ✅ **MCP write-parity** (C4) — `update_task`, `assign_task`, `allocate_engineer`, `list_adrs`★,
   `create_project` **shipped** (thin wrappers over existing endpoints; `set_decision_rule`,
   `list_milestones`, `record_risk_snapshot` and the new-model tools remain). Cheapest,
   highest-leverage first step.
2. ✅ **Org-wide capacity** (F-R1, C2) — `project_id` now optional; cross-project overload is
   visible on `/team`. **Shipped.**
3. ✅ **Fix the risk renormalization trap** (Q-R1, C5) — an Observability Coverage indicator +
   `confidence` flag; a blind project no longer looks safer. **Shipped.**
4. ✅ **Reframe schedule "drift" → variance; reserve "drift" for architecture** (C-R4). Naming +
   a logged, reasoned re-baseline (note + history). **Shipped** — defuses the agility-vs-baseline
   tension. *(Completes the "Now" tier.)*

**Next (the structural bets):**
5. ✅ **Initiative/Program layer + cross-project dependencies + initiative cockpit** (C1; B-R1, D-R1, R).
   **Shipped:** initiative model + project linkage + CRUD + rollup + cockpit (slice 1), then
   cross-project dependencies + cross-project critical path with hand-offs (slice 2). **C1 complete.**
6. ✅ **Probabilistic forecast** (C-R1, C3) — Monte-Carlo P50/P85 from throughput, on the Gantt tab
   and initiative cockpit. **Shipped.**
7. ✅ **Blockers + flow board + WIP** (D-R2, C-R2). **Shipped:** blockers (model + CRUD + MCP +
   `/me` flag/resolve + alerts digest) and the flow board (status lanes + WIP + cycle-time-P85
   aging, Board tab + `get_board`). *(Open follow-ups: blocked-time in the risk score; persisted
   WIP limits.)*
8. ◐ **Auto-captured risk snapshots + drift staleness** (N-R1, Q-R3, C6). **Shipped:** nightly
   risk-snapshot sweep (arq worker) and drift scan-log + `scan_due` staleness badge. **Remaining:**
   a GitHub push-webhook that enqueues the Drift Sentinel (agent-driven scan).

**Later (depth):**
9. **Decision fitness functions + traceability ledger** (G-R1, T, C6) — verified coherence.
10. **Delivery (DORA+flow) metrics + DoD-as-policy** (S, U) — the quality/velocity backbone.
11. **Hours-based + reality-checked capacity, skill-fit, PR metrics** (F-R2/3/4, J-R1).
12. **Contract drift + non-Python analyzers + suppression UI** (N-R2/3).

---

*Proposal authored as part of a flows + MCP review. Promote items into `USER_FLOWS.md` as they ship,
per `CLAUDE.md` → "Keeping USER_FLOWS.md in sync."*
