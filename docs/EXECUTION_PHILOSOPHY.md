# Maximum Execution Velocity at Very High Quality — Philosophy & Process

> A working theory of how a software architect drives a decentralized team to ship fast *and* well,
> and how Canopy should embody it. Companion to [`PROPOSED_FLOWS.md`](./PROPOSED_FLOWS.md): that doc
> says *what* to change in the product; this one says *why* — the operating model the changes serve.
> Where a principle maps to a concrete product change, it's cited as `PF §X`.

---

## The one idea everything hangs on

**Velocity and quality are not a trade-off. They are the same lever, viewed from two ends: the
length of your feedback loops.**

The intuition that you "slow down to get quality" or "cut corners to go fast" describes *local,
short-term* moves. At the *system* level, over any horizon longer than a sprint, the teams that ship
the fastest are the ones that ship the *highest* quality — because both are produced by the same
thing: **short feedback loops on small batches, with decisions pushed to where the information is,
inside guardrails that make the safe path the easy path.**

Slow feedback is the tax. A bug found in code review costs minutes; in staging, hours; in
production, days plus trust. An architectural decision made implicitly in a PR and discovered six
months later as drift costs a re-architecture. A dependency between two teams discovered at
integration costs a slipped quarter. Every one of these is a *long loop*. The entire discipline of
high-velocity, high-quality engineering is the relentless **shortening of loops** and the
**shrinking of batches** so that when something is wrong, you find out while it's still cheap to fix.

Everything below is a corollary.

---

## 1. Flow over utilization

The most expensive mistake an engineering org makes is optimizing for **utilization** ("is everyone
busy?") instead of **flow** ("how fast does work move from idea to production?"). They are in
direct tension: a system run at 100% utilization has, by queuing theory, *infinite* wait times.
Slack is not waste; it is the capacity to absorb variability, respond to the unexpected, and keep
work *flowing*.

**What this means in practice**
- Measure and manage **cycle time** (start→done) and **WIP**, not busyness. Little's Law:
  `cycle time = WIP ÷ throughput`. The fastest way to reduce cycle time is to **reduce WIP** —
  finish things before starting new ones.
- Impose **WIP limits**. A team with 5 people and 12 in-flight tasks is a team where everything is
  late and nothing is done. Limiting WIP forces finishing, surfaces blockers, and *increases*
  throughput.
- Treat **blocked time** as the primary enemy. An item sitting blocked is pure lead-time tax with no
  work being done. Blockers must be *visible*, *owned*, and *escalated automatically*.

**In Canopy**
- The capacity model today asks "is this engineer ≤100% allocated?" — a *utilization* question, and
  worse, it's per-project so cross-project overload is invisible (`PF C2`). It should ask flow
  questions: WIP per person, aging work items, blocked time (`PF C-R2, D-R2, Q-R2`).
- The Gantt/CPM spine optimizes a *plan*; a flow board with WIP limits optimizes *movement*. Canopy
  needs both — CPM for hard-sequenced work, flow for the decentralized day-to-day (`PF C-R2`).

> **Anti-metric:** "resource utilization %." If it ever becomes a target, teams will pad estimates
> and hoard work to look busy, and flow will collapse. Watch it; never optimize it.

---

## 2. Small batches, short loops

Batch size is the master variable. Halve the batch size and you more than halve the risk of each
change, shorten the loop to feedback, and compound the rate of learning.

- **Small PRs.** A 50-line PR gets a real review in minutes; a 2,000-line PR gets a rubber stamp.
  Review quality is inversely proportional to PR size. Small PRs are *both* faster to merge *and*
  higher quality — the master lever again.
- **Trunk-based development + short-lived branches.** Long-lived branches are large batches of
  un-integrated risk. Integrate continuously; resolve conflicts while they're small.
- **Continuous delivery.** Deploying frequently in small increments is *safer*, not riskier: each
  deploy carries less change, so when something breaks the cause is obvious and the blast radius is
  small. Deployment frequency and change-fail rate are *positively* correlated in the data (DORA) —
  the orgs that deploy most often also break things least.
- **Decompose to days, not weeks.** A task you can't finish in a couple of days is a task you can't
  reason about. The WBS discipline Canopy already encourages (`summary → leaf tasks`) is right;
  push it further toward small, independently-shippable slices.

**In Canopy:** lead time for change, deploy frequency, and change-fail rate (DORA) should be
first-class metrics (`PF S`). The §J8 activity substrate already captures deploys, build failures,
and incidents — the inputs exist; the metrics view doesn't.

---

## 3. Decentralize decisions — to where the information is

A decentralized team executing concurrently *cannot* route every decision through the architect;
that turns the architect into a bottleneck and the loop goes long. The job is not to *make* every
decision — it's to *design the system in which good decisions get made without you.* That requires
two things working together:

**a) A clear, explicit decision-rights model.** Who decides what, and how. Most decisions should be
made by the engineer or team closest to the work, and merely *recorded*. The architect owns the
*cross-cutting, expensive-to-reverse* decisions and the *coherence* of the whole.

**b) The one-way-door / two-way-door distinction (reversibility).** This is the single most useful
decision heuristic in existence:
- **Two-way doors** (reversible — most decisions): decide fast, locally, with a bias to action. The
  cost of being wrong is a cheap reversal. *Optimizing these for safety is itself a costly mistake.*
- **One-way doors** (hard to reverse — a public API contract, a datastore choice, a security
  boundary): decide deliberately, with review and the alternatives written down. These deserve
  friction.

Canopy already models `reversibility = one_way | two_way` on the ADR — this is exactly right and
under-exploited. The product should make two-way-door decisions *frictionless* (record and move) and
one-way-door decisions *appropriately gated* (`PF G-R3`). Applying the same ceremony to both is how
you get either reckless irreversible decisions or paralyzed reversible ones.

**c) Decision latency is a tracked cost.** In a decentralized team, a decision sitting in
"under discussion" for three weeks blocks N people silently. **Decision latency** — time from raised
to resolved — is a leading indicator of organizational health. Canopy's decision queue already
buckets stuck/deferred items; it should *measure the latency* and surface it as the cost it is
(`PF G-R4`).

> **The architect's leverage is in the system, not the decisions.** Every decision you personally
> make is O(1). Every guardrail you install that makes the *team* decide well is O(team). Spend your
> time on the latter.

---

## 4. Guardrails, not gates — make the safe path the easy path

Decentralization without coherence is chaos; coherence enforced by a central reviewer is a
bottleneck. The resolution is **automated guardrails**: encode the architectural constraints as
*executable checks* that run continuously, so engineers get instant feedback and the architect gets
coherence *without being in the loop*.

This is the difference between:
- **A gate:** "the architect must review every change touching the API layer." (Long loop,
  bottleneck, doesn't scale.)
- **A guardrail:** "a CI fitness function asserts no module under `app.api` imports
  `app.connectors` directly; it fails the build in 30 seconds with a clear message." (Instant loop,
  no bottleneck, scales infinitely.)

**Fitness functions** — automated tests over architectural characteristics (layering, dependency
direction, latency budgets, bundle size, public-API compatibility) — are how you keep architecture
coherent in a fast-moving, decentralized codebase. They turn the architect's intent into *code that
defends itself.*

**In Canopy:** this is the missing spine that would make the drift story *real* rather than
best-effort. Today drift is detected by a manual, Python-import-only, open-loop scan (`PF C6, N`);
an `accepted` ADR is deemed "unimplemented" by the weak proxy "its components show no commits."
Instead, let an ADR declare a **fitness function**, evaluate it in CI on every change, and let
*that* — a real pass/fail — drive the drift signal and the ADR's lived status (`PF G-R1, N-R1,
N-R2`). An accepted decision that its own fitness check now violates is the strongest, earliest,
most actionable drift signal there is.

> **Coherence is a property you *verify continuously*, not a state you *declare once*.** An ADR that
> isn't connected to an executable check is a wish, not a constraint.

---

## 5. Quality is built in, defined explicitly, and verified continuously

"High quality" decomposes into things you can build into the *process* so they're not left to
heroics or memory:

- **Definition of Done as policy, not folklore.** Done means: tested at the right level, an ADR if
  the change is architecturally significant, telemetry/observability added, docs updated (in this
  repo, `USER_FLOWS.md` — the rule already exists in `CLAUDE.md`), and the fitness functions pass.
  Make it *data* attached to the work, enforced softly at PR time (`PF U`).
- **Shift left.** Every class of defect has a cheapest-possible point of detection; push detection
  to that point. Types over runtime checks (this repo's strict mypy/ruff/eslint is exactly this
  instinct — keep it green, it's a *short loop*). Tests over manual QA. Fitness functions over
  drift archaeology. Pre-commit/pre-push hooks (already present) over CI failures over production
  incidents.
- **The test pyramid, honestly.** Many fast unit tests over pure logic (Canopy's services are
  deliberately pure and unit-tested — `scheduling.py`, `risk.py`, `drift.py`, `forecast.py` to come
  — this is the right instinct), fewer integration tests, a thin layer of end-to-end. Tests are a
  *feedback-loop length* investment, not a tax.
- **Observability is part of "done."** You cannot operate fast what you cannot see. A feature without
  telemetry is a feature you'll debug blind. This is also why **absence of observability is a risk,
  not a neutral** — and why Canopy's current risk score, which makes an *unobserved* project look
  *safer*, is backwards and must be inverted (`PF Q-R1`).
- **Progressive delivery.** Feature flags, canaries, and gradual rollout shrink the blast radius of
  every change and shorten the loop from "shipped" to "is it actually working?" MTTR matters more
  than MTBF: you will have failures; what distinguishes great teams is how fast they detect and
  recover.

> **Quality work is fast work.** A well-tested, well-observed, small change is *quicker* to ship
> with confidence than a large untested one is to ship with fear. The fear *is* the slowness.

---

## 6. Forecast probabilistically; plan for variability

Knowledge work does not have known durations, so a single-point plan (CPM's hard end-date) is
precise and wrong. It creates false confidence, and then every replan looks like failure ("drift
from baseline") when it's actually *learning*.

- **Forecast with distributions, not point estimates.** "P50 May 30 / P85 Jun 14" is honest and
  *actionable* in a way "ends May 30" is not. It's computed from the team's *actual* historical
  throughput/cycle-time, so it improves as you gather data — a learning loop (`PF C-R1`).
- **Re-planning is a feature, not a failure.** Agility *means* adapting the plan as you learn. The
  baseline is a reference for *conversation* ("here's what changed and why"), not a stick. Canopy
  should reframe schedule "drift" as **variance** and make re-baselining a deliberate, *reasoned*,
  logged act — reserving the loaded word "drift" for the architecture meaning (`PF C-R4`).
- **The critical path is one lens, not the spine.** It's invaluable for hard-sequenced work (a
  cutover, a launch runbook). For a decentralized team running many parallel slices, the binding
  constraints are usually **cross-team hand-offs** (the cross-project dependencies Canopy can't yet
  model — `PF D-R1`) and **decision/blocker latency**, not the longest task chain.

> **Estimates are forecasts, not commitments.** Treating a forecast as a promise is how you get
> padding, sandbagging, and the death-march dynamics that destroy both velocity and quality.

---

## 7. The learning loop — close it, quantitatively

A high-velocity org is a *learning* org: it gets faster and better over time because it
systematically converts outcomes into improved inputs.

- **Calibrate estimates against actuals.** Feed completed work back into the forecast (`PF C-R1`).
  The system should learn the team's cycle-time distribution, not ask humans to re-guess.
- **Retros that change the system, not just the mood.** Canopy's auto-seeded retros (schedule
  variance, drift, ADR churn) are a strong instinct — the gap is *follow-through*: a retro should
  reliably mint tracked work or a fitness function (the §P "follow-up" flow exists; the discipline
  of closing it is the point). A lesson not encoded as a guardrail will be re-learned the expensive
  way.
- **Postmortems are blameless and systemic.** Every incident is a free lesson about a missing
  guardrail or a too-long loop. The §P2 postmortem flow (auto-opened from an incident webhook,
  `PF`) should always ask: "what check would have caught this earlier, and where does it go?"

> **The retro's output is a change to the system, or it didn't happen.**

---

## 8. AI agents as force multipliers — inside the same guardrails

Canopy is itself an agentic product: an MCP server, skills, and subagents that let Claude plan,
sync, assess risk, and detect drift on the architect's behalf. As agents do more — increasingly
*writing the code*, not just the plan — the philosophy doesn't change; it *intensifies*. Agents make
small batches and short loops cheap, which is exactly the regime where this model wins. Three
disciplines:

- **Agents must be able to *act*, not just *report*.** An agent that can see everything and change
  nothing is a very expensive dashboard. Canopy's MCP surface is 45 tools but write-poor — no
  `update_task`, no `assign_task`, a skill that calls a non-existent `list_adrs` (`PF C4, L-R1`).
  Close that gap or the agentic promise is hollow.
- **Agent output is subject to the *same* guardrails as human output — automatically.** An
  agent-authored PR should auto-run the PR-to-ADR linker and the fitness functions *before* a human
  looks (`PF L-R3`). The whole point of guardrails (§4) is that they don't care *who* wrote the
  change. As the author increasingly becomes an agent, executable coherence checks stop being nice
  and become load-bearing.
- **Keep the human on the irreversible decisions.** One-way doors (§3) stay human-gated; two-way
  doors are exactly where agents should run with a long leash. The reversibility distinction *is*
  the human-in-the-loop policy for AI-driven development.
- **A daily synthesis is the architect's highest-leverage agent surface.** A "morning standup" skill
  — what moved, what's blocked, what needs deciding, what drifted overnight, what's most likely to
  slip — turns the architect's whole cockpit into one proactive briefing (`PF L-R2`). This is where
  agentic and decentralized reinforce each other: the agent watches the breadth so the architect can
  spend attention on the depth.

---

## 9. Metrics that matter (and anti-metrics to refuse)

Measure the system so you manage flow and loop-length, not proxies that invite gaming.

**Lead with these (mostly leading indicators):**
- **DORA:** deploy frequency, lead time for change, change-fail rate, MTTR. The most validated
  delivery metrics in existence; Canopy has the §J8 inputs to compute them (`PF S`).
- **Flow:** WIP, cycle time, throughput, **flow efficiency** (active ÷ total elapsed — usually
  shockingly low, and the biggest hidden opportunity).
- **Blocked time** and **aging WIP** — the earliest, truest predictors of a slip (`PF D-R2, Q-R2`).
- **Decision latency** — time-in-state for decisions; the silent tax on decentralized teams
  (`PF G-R4`).
- **Architectural fitness pass-rate & open drift** — coherence, continuously verified (`PF N`).
- **Forecast confidence band** — honest delivery prediction (`PF C-R1`).

**Refuse these as targets (Goodhart's Law — they become useless the moment they're a goal):**
- **Resource utilization %** — punishes the slack that enables flow (§1).
- **Velocity / story points as a *target*** — invites estimate inflation; fine as an *internal
  forecasting input*, toxic as a goal or a cross-team comparison.
- **Lines of code, commit count, PR count** — measure motion, not progress.
- **Test coverage % as a *target*** — produces assertion-free tests that exist to color a number.

> **The meta-rule:** a metric is for *seeing*, not for *squeezing*. The instant a metric becomes a
> target handed down as a quota, it stops measuring reality and starts measuring compliance theater.

---

## 10. The operating model in one picture — the *intent spine*

All of the above composes into a single thin thread that should run, traceably, top to bottom — and
which Canopy *almost* has the pieces for but doesn't yet connect (`PF C1, C6, T`):

```
Initiative (outcome + hypothesis)          ── why, and how we'll know it worked
   └─ Project (a bet toward the outcome)    ── the slice a team owns
        └─ Decision / ADR (reversibility)   ── the architectural choices, with explicit doors
             ├─ Fitness function            ── the decision, made continuously verifiable
             └─ Work (tasks / PRs)          ── small batches that implement the decision
                  └─ Verification           ── tests + fitness + telemetry prove it's done & honored
                       └─ Outcome / metrics ── DORA + flow feed back into forecast & retro
                            └────────────── learning loop closes to the top
```

Each downward link is *intent*; each upward link is *verification and learning*. **Velocity is how
fast intent flows down; quality is how reliably verification flows up.** They are the same spine.

The architect's job is to keep that spine **thin** (no ceremony that doesn't shorten a loop),
**explicit** (decision rights, DoD, fitness functions written down as data and code), and
**decentralized** (most links made by the teams, the architect owning coherence and the
irreversible doors). Canopy's mission — and the thrust of `PROPOSED_FLOWS.md` — is to make that
spine *visible, traceable, and continuously verified*, so a small team can execute a large
initiative concurrently, adapt with maximum agility, and find out what's wrong while it's still
cheap to fix.

---

## Appendix — anti-patterns this model exists to prevent

- **The dashboard trap.** A beautiful read-only cockpit nobody can *act* from. (Canopy's write-poor
  MCP surface, `PF C4`, is the early symptom.) Visibility without agency is theater.
- **The baseline-as-stick.** Treating every replan as failure; punishing the agility you asked for
  (`PF C-R4`). Plans are for learning, not for blame.
- **Utilization maximization.** 100%-busy teams with infinite queues and zero flow (§1).
- **Coherence by heroics.** Architecture kept consistent by one person reviewing everything — until
  they're on vacation, or the team triples (§4). Encode it or lose it.
- **Silence mistaken for safety.** No alerts, no observability, no drift signal → "looks green."
  Absence of signal is *risk*, not health (`PF Q-R1`). The most dangerous project is the quiet one.
- **The big-bang batch.** The 3,000-line PR, the six-month branch, the quarterly release — each a
  long loop hiding compounding risk that surfaces all at once, at the worst time (§2).
- **Decision paralysis on two-way doors / recklessness on one-way doors.** Applying the same ceremony
  to reversible and irreversible decisions; the reversibility model exists precisely to avoid both
  (§3).
