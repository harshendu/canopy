# Canopy — User Flows

> **This document is the source of truth for user-facing flows and must be kept in sync with the
> code.** When a flow is added, changed, or removed, update this file in the same change. If a flow
> exists only via the API or the Claude plugin (no UI yet), it is still documented here and flagged.

Canopy is a tool for a **software/technical architect** to manage the architecture and delivery of a
codebase. It has two front doors over one FastAPI backend:

- **React dashboard** (`frontend/`) — the visual cockpit the architect clicks through.
- **Claude plugin** (`plugin/`) — an MCP server + skills + subagents that let the architect drive
  canopy conversationally, and let Claude run multi-step work.

Both call the same REST API (`/api/v1/...`). Throughout, **API** = REST endpoint and
**MCP** = the equivalent Claude plugin tool.

> **Looking ahead:** a critique of these flows and a proposed revision/extension live in
> [`PROPOSED_FLOWS.md`](./PROPOSED_FLOWS.md); the delivery philosophy behind those proposals is in
> [`EXECUTION_PHILOSOPHY.md`](./EXECUTION_PHILOSOPHY.md). This file remains the source of truth for
> what is *built*; those are the source of intent for what *should change*.

## Actors
- **Architect** (primary) — plans, schedules, manages the team, records decisions.
- **Admin** — an architect with `admin` role; the only one who can create new users.
- **Claude** — acts on the architect's behalf through the plugin's MCP tools / skills / subagents.

## Source-of-truth boundaries (affect every sync flow)
- **Jira** owns epics/stories and ticket **status**. Canopy syncs *from* Jira and **never writes
  status back**. Mirrored status on canopy tasks is read-only.
- **GitHub** owns code + some architecture docs. **Google Drive** holds design docs. Canopy reads
  these on demand and caches lightly.

---

## A. Authentication & access

### A1. Log in
- **Actor:** any user · **UI:** `/login`
- **Steps:** enter email + password → submit. On success a JWT is stored in the browser
  (`localStorage`) and the app routes to `/portfolio`. On failure an "Invalid email or password"
  message is shown.
- **API:** `POST /api/v1/auth/login` (form-encoded `username`/`password`) → `{access_token}`.
- **Notes:** the first admin is seeded at backend startup from `FIRST_SUPERUSER_EMAIL` /
  `FIRST_SUPERUSER_PASSWORD`. The token is sent as `Authorization: Bearer <jwt>` on every request.

### A2. Sign out
- **UI:** sidebar "Sign out" clears the stored token and returns to `/login`.

### A3. User & role management *(admin)*
- **Roles:** `admin`, `architect`, `engineering_manager`, `engineer`, `viewer` (plus a legacy
  `member` ≈ architect, kept for back-compat and not offered in the UI).
- **UI:** `/admin/users` (admin only, shown in the sidebar only for admins) — invite by email
  (email + temp password + role + name), change a user's role, and deactivate / reactivate.
  Closes v1's API-only registration gap.
- **API:** `POST /api/v1/auth/register` (admin), `GET /api/v1/auth/users` (admin),
  `PATCH /api/v1/auth/users/{id}` (admin; role / is_active / full_name — you can't deactivate
  yourself).
### A3a. Role enforcement (Roles × flows) **[new]**
Write access is now enforced server-side per the v2 matrix; **reads stay open to any
authenticated user** (viewers included). Enforced via role-group dependencies in
`app/api/deps.py` (`ArchitectWriter` / `PlannerWriter` / `ContributorWriter`; admin always
allowed; legacy `member` ≈ architect):

|Domain                                   |admin|architect|eng-manager|engineer|viewer|
|-----------------------------------------|-----|---------|-----------|--------|------|
|Users (register / role / active)         |rw   |r        |r          |r       |r     |
|Project create / settings / holidays (B) |rw   |rw       |r          |r       |r     |
|Plan: tasks / deps / milestones / replan |rw   |rw       |rw         |own task|r     |
|Capacity: engineers / roles / alloc (F)  |rw   |rw       |rw         |r       |r     |
|ADR propose / comment (G2/G6)            |rw   |rw       |rw         |rw      |r     |
|ADR status transition / components       |rw   |rw       |rw         |r       |r     |
|Risk mitigations (Q)                     |rw   |rw       |rw         |r       |r     |

- **Engineer "own task":** an engineer (linked via `Engineer.user_id`) may `PATCH` only a task
  whose `assignee_engineer_id` is theirs (e.g. update progress); creating/deleting tasks, editing
  the dependency graph, and replanning stay planner-only.
- **The web app hides** write controls the current role can't use (a pure `src/lib/permissions.ts`
  mirrors the matrix); the server is the real gate and returns `403` regardless.
- **Not enforced yet:** connector writes (still any authenticated user) and the engineer
  "own-allocation / availability" carve-out (that self-service flow is §F4, not built) — capacity
  writes are planner-only for now. Decision **rules/approval gates** (G3) remain advisory.

### A4. Get current user
- **API:** `GET /api/v1/auth/me`. The web app caches this to gate admin-only nav.

### A5. Engineer ↔ login link & workspace **[new]**
- A team **Engineer** record can be linked to a login via `Engineer.user_id` (set on the **Team**
  page's per-engineer "link to a login" select, or `PATCH /api/v1/team/engineers/{id}`). That link
  powers the engineer **workspace** (§M): a logged-in user sees the tasks and decisions tied to
  their engineer record.
- **Not built (v2 §A5):** self-service `/onboarding` (engineers confirming their own
  timezone/skills/hours) — an admin sets these on the Team page for now. **OIDC/SSO** and the
  `HttpOnly`-cookie token model (v2 §A1) are also not built; auth remains a `Bearer` JWT.

---

## B. Projects & portfolio

### B1. View the portfolio dashboard
- **UI:** `/portfolio` (landing page). Shows a completion bar chart and a card per project
  (avg % complete, completed/total tasks, critical-task count, end date, and **risk + drift score
  badges** — see §Q / §N). Clicking a card opens it.
- **API:** `GET /api/v1/projects/portfolio` (each `ProjectSummary` includes `risk_score`/`risk_level`
  and `drift_score`/`drift_level`, computed by the same scorers as the Risk/Drift tabs) · **MCP:**
  `list_projects`.
- **Not built (v2 §B1):** last-decision recency and sortable columns.

### B2. Create a project
- **UI:** `/projects` → enter KEY + name → "Add".
- **API:** `POST /api/v1/projects` (`key`, `name`, optional `start_date`/`target_date`) · **MCP:**
  `create_project`.
- **Notes:** `key` is a unique slug (e.g. `PLATFORM`).

### B3. Open a project (the cockpit)
- **UI:** `/projects/:id` — a tabbed workspace: **Gantt · Dependencies · Capacity · Decisions ·
  Architecture · Drift · Roadmap · Burndown · Risk · Retros · Activity**. The header has a **5-day week** toggle, **Set
  baseline**, and **Schedule (CPM)** (the planning controls and the add-task/dependency forms are
  hidden for roles that can't use them — §A3a). A tab can be deep-linked with `?tab=` (e.g.
  `/projects/:id?tab=drift`).

### B4. Edit / archive a project · toggle working week
- **UI:** the "5-day week" checkbox in the project header toggles weekend-aware scheduling.
- **API:** `PATCH /api/v1/projects/{id}` (`name`, `description`, dates, `archived`, `skip_weekends`),
  `DELETE /api/v1/projects/{id}`.
- **UI gap:** renaming/archiving/date edits are API-only today (only the weekend toggle is in the UI).

---

## C. Work breakdown & scheduling (Gantt tab)

### C1. Add a task / milestone / phase
- **UI:** Gantt tab → "Add task" form: name, duration (working days), type
  (**task** / **milestone** / **summary**), optional deadline → "Add".
- **API:** `POST /api/v1/tasks` · **MCP:** `create_task`.
- **Notes:** a **summary** task is a phase/workstream; build the WBS by setting `parent_id`
  (API/MCP — the UI form creates top-level tasks).
- **Edit / assign:** `PATCH /api/v1/tasks/{id}` (a planner edits any task; an engineer only one
  assigned to them — §A3a) · **MCP:** `update_task` (planning fields: name/duration/start/end/
  deadline/percent_complete/parent — **status stays Jira-mirrored, read-only**) and `assign_task`
  (set/clear `assignee_engineer_id`). Re-run `replan_schedule` after duration/structure changes.

### C2. Add a dependency
- **UI:** Gantt tab → "Add dependency (finish → start)" form: pick predecessor + successor → "Link".
- **API:** `POST /api/v1/dependencies` (supports `type` FS/SS/FF/SF and `lag`) · **MCP:**
  `link_dependency`.
- **Notes:** the UI creates finish-to-start links; other types + lag are via API/MCP.

### C3. Schedule (Critical Path Method)
- **UI:** project header → **Schedule (CPM)**. A banner reports scheduled task count, the critical
  path, the project end date, and any **deadline violations** (also flagged red on the Gantt).
- **API:** `POST /api/v1/projects/{id}/replan` · **MCP:** `replan_schedule`.
- **Result:** computes start/end dates, `is_critical`, and float for every task, honoring the
  project's working calendar (weekends + holidays) and any task's set start date (treated as
  start-no-earlier-than). Cycles return a 409 error.

### C4. Set / view a baseline (drift)
- **UI:** project header → **Set baseline** snapshots current start/end. The Gantt then draws a faint
  gray "planned" strip under each bar so plan-vs-actual drift is visible.
- **API:** `POST /api/v1/projects/{id}/baseline` · **MCP:** `set_baseline`.

### C5. What-if scheduling
- **Actor:** architect via Claude (or API) · **MCP:** `whatif_schedule` · **API:**
  `POST /api/v1/projects/{id}/whatif` with `duration_overrides` (`{task_id: working_days}`).
- **Result:** returns a *projected* end date / critical path / deadline violations **without
  persisting** — for "what if we add an engineer / cut scope" analysis.
- **UI gap:** no what-if screen yet; it's driven through Claude or the API.

### C6. Zoom the Gantt
- **UI:** Gantt tab → the `−` / `+` controls change the day-width.

### C7. Working calendar (weekends + holidays)
- **UI:** "5-day week" toggle (weekends). **Holidays** are API-only:
  `GET/POST/DELETE /api/v1/projects/{id}/holidays`. Both feed the CPM scheduler.

---

## D. Dependencies tab
- **UI:** Dependencies tab → a graph (React Flow) of tasks as nodes and dependencies as arrows,
  laid out left-to-right by topological level; critical-path nodes/edges are red.
- **Data:** same `GET /api/v1/projects/{id}/gantt` payload as the Gantt.

---

## E. Milestones & roadmap

### E1. Define a milestone
- **UI:** Roadmap tab → "Add milestone" form (name, target date) → "Add milestone".
- **API:** `POST /api/v1/milestones` · **MCP:** `create_milestone`.

### E2. Roadmap (now / next / later)
- **UI:** Roadmap tab groups the project's milestones into **Now** (≤30 days / overdue),
  **Next** (31–90 days), **Later** (90+ days / undated).
- **API:** `GET /api/v1/milestones?project_id=`.

---

## F. Team & capacity

### F1. Manage engineers and roles
- **UI:** `/team` — add engineers (name, title, **GitHub login**, **timezone**, **committed
  hours/week**, **skill tags**), link an engineer to a **login** (per-row select, admins only),
  add functional roles, and remove engineers. Engineer rows show skills / GitHub / committed hours.
- **API:** `GET/POST /api/v1/team/engineers`, `PATCH/DELETE /api/v1/team/engineers/{id}`
  (engineer payload now includes `user_id`, `skill_tags`, `github_login`, `timezone`,
  `committed_hours_per_week`), `GET/POST /api/v1/team/roles` · **MCP:** `list_engineers`,
  `add_engineer` (extended).
- **Not built (v2 §F1):** on-call schedule (needs the PagerDuty connector §J7).
- **Not built (v2 §F2–F5):** committed-hours/interrupt-budget *allocation*, planned-vs-realized
  capacity, engineer PTO feeding CPM, and skill-task fit scores — allocation is still percent-based.

### F2. Allocate engineers (capacity)
- **UI:** project → Capacity tab → "Allocate" form (engineer, percent, date range) → "Add".
- **API:** `GET/POST /api/v1/team/allocations`, `DELETE /api/v1/team/allocations/{id}`
  (engineer, project, percent allocation, capacity hours, date range) · **MCP:** `allocate_engineer`.

### F3. Capacity heatmap (per-project **and** org-wide)
- **UI:** project → Capacity tab → an engineer × ISO-week grid shaded by total allocation %;
  over-allocation (>100%) is red. The **Team** page (`/team`) shows the same grid **summed across
  every project** ("Capacity across all projects") — so cross-project overload (someone at 50% on
  three projects = 150%) is visible where per-project views hide it; rows split across >1 project
  are flagged with their contributing project keys.
- **API:** `GET /api/v1/team/capacity?project_id=` (omit `project_id` for the org-wide grid;
  `project_id` is `null` in the response and each row carries `projects` = contributing keys) ·
  **MCP:** `get_capacity` (`project_id` now optional). Closes the v2 §F cross-project blind spot.

---

## G. Architecture & decisions (Architecture + Decisions tabs)

Components and the system map live on the **Architecture** tab (G1). ADRs are now first-class
**decisions** on their own **Decisions** tab (G2–G6) plus a team-wide **`/decisions`** page — the
architect's unit of work is the decision, so it carries a lifecycle, an owner, stakeholders who
review it, alternatives, reversibility, and a discussion thread.

> **Identity note:** decision **owner**, **proposer**, **stakeholders**, and **comment authors**
> reference **Engineer** records (the team model). An Engineer can now be **linked to a login**
> (`Engineer.user_id`, §A5), which powers the `/me` workspace (§M). Role enforcement now applies
> (§A3a): **engineers can propose and comment** on decisions and edit ADR fields, but **only
> planners (admin / architect / engineering-manager) can change a decision's status** (e.g. accept);
> viewers are read-only.

### G1. Map components (Architecture tab)
- **UI:** Architecture tab → add components (name + kind: service/module/datastore/external/ui) and
  relationships (source → target, kind: depends_on/calls/publishes_to/reads_from). The system map
  (React Flow) shows components colored by kind with relationship edges.
- **API:** `GET/POST /api/v1/architecture/components`, `GET/POST/DELETE
  /api/v1/architecture/component-links` · **MCP:** `list_components`, `create_component`,
  `link_components`.
- **Code bindings** (drift linchpin): the Architecture tab has a **Code bindings** section to tie a
  component to where it lives (`path_glob` + Python `module_prefix`, optional connection/repo) —
  `GET /api/v1/architecture/code-bindings?project_id=`, `POST/DELETE
  /api/v1/architecture/code-bindings[/{id}]` (planner-gated) · **MCP:** `list_code_bindings`,
  `add_code_binding`. These feed drift detection (§N).
- **Component metadata (v2 §G1):** components carry an **owner** (engineer), **criticality**
  (low/med/high), **tier** (presentation/business/data/infra), and an **observability URL** — set on
  the Add-component form (criticality also shown on the map node label).

### G2. Record / propose a decision (ADR) — Decisions tab
- **UI:** Decisions tab → "Propose / record a decision": title, context, decision, consequences,
  **alternatives** (one per line), **reversibility** (one-way / two-way door), **decision owner**,
  **proposed by**, **stakeholders** (must review), supersedes, affected components → "Save". The
  team-wide `/decisions` page has a lighter "Propose a decision" form (engineer flow).
- **API:** `POST /api/v1/architecture/adrs` (now also accepts `alternatives`, `reversibility`,
  `decision_owner_id`, `proposed_by_id`, `decide_by`, `rfc_url`, `stakeholder_ids`) · **MCP:**
  `create_adr` (architect records) / `propose_adr` (engineer proposes — sets `proposed_by_id`,
  status `proposed`).
- **List:** `GET /api/v1/architecture/adrs?project_id=` backs the Decisions-tab list (omit
  `project_id` for org-wide) · **MCP:** `list_adrs`.
- **Lifecycle:** `proposed → under_discussion → accepted | rejected → superseded | deprecated`,
  plus **`deferred`** (a conscious postponement — **requires a `decide_by` date**, enforced 400).
  Illegal jumps (e.g. `deprecated → proposed`) are rejected 409. The legal map is in
  `app/services/decisions.py:valid_transition` (mirrored client-side in `src/lib/decisions.ts`).

### G3. Discuss & review a decision
- **UI:** Decisions tab → click an ADR to expand: full context/decision/consequences/alternatives,
  a **status control** (only legal transitions; a `decide_by` date appears when deferring), a
  **review summary** (approved / changes-requested / rejected / pending + whether the project's
  decision rule is met to accept), a **blast-radius** button (G5), and the **discussion thread**.
  Post a comment with a **kind**: `comment` | `approve` | `request_changes` | `reject` (a
  non-comment kind is a formal review action, attributable to an engineer).
- **API:** `GET /api/v1/architecture/adrs/{id}` (detail: fields + comments + review summary),
  `POST /api/v1/architecture/adrs/{id}/comments`, `PATCH /api/v1/architecture/adrs/{id}`
  (status transitions, stakeholders, all fields) · **MCP:** `get_adr`, `comment_adr`,
  `transition_adr`.
- **Decision rule** (per project, `PATCH /api/v1/projects/{id}` → `decision_rule` =
  `owner_decides` | `consensus` | `lazy_consensus`, `decision_sla_hours`): drives the advisory
  `can_accept` in the review summary. It is surfaced, **not hard-enforced** — the owner can still
  decide. Per-stakeholder approval *gates* and SLA *notifications* are **not built** yet.

### G4. Decision queue
- **UI:** the **`/decisions`** page (team-wide, also in the sidebar) and the top of each project's
  Decisions tab show the queue, grouped by bucket: **needs_triage** (proposed, with the owner's
  SLA), **stuck** (under discussion > 14 days), **deferred_soon** (`decide_by` within 14 days /
  past), **discussing**. Overdue items sort first; rows link into the owning project's Decisions tab.
- **API:** `GET /api/v1/decisions/queue?project_id=` (omit `project_id` for org-wide) · **MCP:**
  `decision_queue`. Logic is pure in `app/services/decisions.py:build_decision_queue`.
- **Not built:** **implicit decisions** (architectural choices made in code without an ADR) require
  drift detection (v2 §N) and are not surfaced here yet.

### G5. Decision-impact analysis (blast radius)
- **UI:** Decisions tab → expand an ADR → **Blast radius**: the components it directly affects plus
  everything that transitively depends on them. (v2 §G4: now in the UI, no longer Claude/API-only.)
- **API:** `GET /api/v1/architecture/adrs/{id}/impact` · **MCP:** `adr_impact`.
- **Not built:** `whatif_supersede` preview (v2 §G4).

### G6. Import an ADR from a doc
- **UI:** Decisions tab → "Import an ADR from a doc" (planner): pick a GitHub/Drive connection + a
  path/file id → the markdown is parsed (title + context/decision/consequences) into an ADR.
- **API:** `POST /api/v1/architecture/adrs/import` · **MCP:** `import_adr`.

---

## H. Progress: burndown
- **UI:** project → Burndown tab → a line chart of remaining vs completed work per week. (v2 §H
  folds burndown into Risk and adds cumulative flow / cycle time / throughput / PR latency — those
  extra charts are **not built**, and burndown stays its own tab for now.)
- **API:** `GET /api/v1/projects/{id}/burndown` · **MCP:** `get_burndown`.
- **Notes:** burndown is driven by task **status history**, which is populated from Jira (see J5).
  Without synced status transitions the chart is flat at the total.

---

## I. Alerts / digest
- **UI:** the old standalone **Alerts** tab is **gone** — alerts now live as the *lagging-indicator*
  section inside the **Risk** tab (§Q). Same content: deadline misses (error), overdue milestones /
  over-allocations (warning), unscheduled work (info).
- **API:** `GET /api/v1/projects/{id}/alerts` (unchanged) · **MCP:** `list_alerts`.
- **Notes:** delivery to Slack/email is **not built** — alerts are computed and shown/queried; a
  delivery integration is a future hook over this output.

---

## Q. Risk dashboard (Risk tab) — leading indicators

Replaces Alerts as the primary risk surface (v2 §Q). A per-project, opinionated **risk score**
(0–100, higher = riskier) with a drillable breakdown, plus a mitigation log; the lagging Alerts
digest (§I) sits underneath.

### Q1. Risk score & breakdown
- **UI:** project → **Risk** tab → the overall score + level (low/moderate/high/critical) and four
  **families**, each with a score bar and drillable **indicators**:
  - **Schedule** — deadline misses, schedule variance vs baseline (drifted tasks), critical-path
    float consumption.
  - **Capacity** — engineer-week over-allocation (from the capacity grid).
  - **Architecture** — deferred decisions past `decide_by` + decisions stuck in `under_discussion`
    > 14 days (both from §G) **+ the drift score (§N)** as a third indicator.
  - **Quality** — **build failures + open incidents** from §J8 activity events. When a project has
    **no** observability events the family doesn't drop out; it scores an explicit **observability
    coverage** gap and the response carries `confidence: "low"` with a note — so a blind project is
    flagged ("flying blind"), never silently scored as *safer* (the old behaviour excluded the
    family and renormalised). (PR-latency / churn metrics, v2 §J6, would enrich it further.)
- Each indicator carries a 0–100 sub-score and drill-down **details** (the offending tasks /
  decisions / engineer-weeks). Scoring weights/thresholds live in `app/services/risk.py` (pure).
- **API:** `GET /api/v1/projects/{id}/risk` · **MCP:** `get_risk`. The same scorer feeds the
  portfolio card's `risk_score` (§B1).

### Q2. Risk timeline
- **UI:** Risk tab → a sparkline of recent risk **snapshots** next to the score; planners can
  **Capture snapshot** on demand (run nightly via the plugin for a real trend).
- **API:** `GET /api/v1/projects/{id}/risk/timeline`, `POST /api/v1/projects/{id}/risk/snapshot`.
  Snapshots persist score + level; the trend matters more than any single value.

### Q3. Mitigation log
- **UI:** Risk tab → **Acknowledge** any indicator with a note, an owner, and a check-in date; open
  mitigations show inline under their indicator and in the **Mitigation log** (resolve / reopen /
  delete).
- **API:** `GET` (embedded in the risk response), `POST/PATCH/DELETE
  /api/v1/projects/{id}/risk/mitigations[/{mid}]` · **MCP:** `log_risk_mitigation`.

### Q4. Not built (v2 §Q)
- Automated **check-in follow-ups** / notifications on mitigations past their date.
- PR-latency / churn **quality** metrics (need GitHub PR-metrics, §J6); the timeline is captured on
  demand rather than on an automatic nightly schedule (wire the plugin/cron for that).

---

## N. Architecture drift detection (Drift tab)

The central value prop: catch where the code has diverged from the declared architecture. Detection
is **pure** (`app/services/drift.py` + `app/services/code_analysis.py`); the **Drift Sentinel**
subagent (§L7) reads code and reports observations, and the server compares them to the declared
component map + ADRs and maintains the queue.

### N1. Drift score
- A per-project 0–100 score (higher = more drift), derived from the currently **open** drift events
  by kind, shown on the **Drift** tab and on every portfolio card (§B1). Computed by the same scorer
  in both places.
- Signals: **declared-vs-actual dependencies** (unexpected edges in code / declared edges absent
  from code = dead architecture), **unimplemented ADRs** (accepted ADRs whose affected components
  show no activity), and **implicit decisions** (new package / dependency / service / datastore with
  no ADR).
- **Code analysis:** Python imports are parsed with the stdlib `ast` and mapped back to components
  via their code-binding `module_prefix` (`app/services/code_analysis.py`, pure + unit-tested). Other
  languages can plug in later; the edge-mapping is language-agnostic.

### N2. Drift queue & scan
- **UI:** Drift tab → the score + the **drift queue** (open events first, then triaged): each event
  shows its kind, summary, affected components, and suspected cause.
- **API:** `GET /api/v1/projects/{id}/drift` (score + events) · `POST /api/v1/projects/{id}/drift/scan`
  (architect-gated) accepts the Sentinel's observations (`actual_edges`, `inactive_component_ids`,
  `implicit_signals`), runs detection (applying learned suppressions), and upserts events — new
  findings open, resolved ones disappear, triaged ones persist. **MCP:** `get_drift`, `scan_drift`.

### N3. Reconciliation
- **UI:** Drift tab → per open event (architect): **Accept → ADR** (auto-proposes an ADR for the
  change, linking the affected components), **Reject → task** (opens a "Revert drift: …" task), or
  **False positive** (records a per-project suppression so the rule won't re-fire). The detector
  "learns" from false positives.
- **API:** `POST /api/v1/projects/{id}/drift/{event_id}/reconcile` (`accepted|rejected|false_positive`)
  · **MCP:** `reconcile_drift`.

### N4. Not built / honest limits
- **No server-side code crawl:** the server doesn't fetch + parse a whole repo itself — the **Drift
  Sentinel** subagent does the reading (via its tools) and posts observations to the scan endpoint.
  So the Drift tab is populated by the Sentinel (or the API/plugin), not by a UI button.
- Only **Python** import analysis is implemented. Per-project **suppression UI** (events are kept as
  `false_positive`); folding drift into **Risk** (§Q1) — both follow-ups.

---

## P. Retrospectives & postmortems (Retros tab)

### P1. Project retrospective
- **UI:** project → **Retros** tab → **New retrospective** (planner) opens a retro whose body is
  **auto-seeded** from project state: completed milestones, schedule variance (tasks ended off
  baseline), open drift (§N), and ADR churn (superseded/total). It's editable markdown; engineers
  **comment**; planners can **close** it.
- **Follow-ups:** from a retro, mint a **task** or **propose an ADR** (linked to the retro's
  affected components) — turning lessons into tracked work.
- **API:** `GET/POST /api/v1/projects/{id}/retrospectives`, `GET/PATCH
  /api/v1/projects/{id}/retrospectives/{rid}`, `POST .../comments`, `POST .../follow-up`
  (`task|adr`) · **MCP:** `list_retrospectives`, `create_retrospective`, `comment_retrospective`,
  `retrospective_follow_up`. The seeder is pure (`app/services/retro.py`).
- **Roles (§A3a):** create / edit / close / follow-up = planners (admin/architect/eng-manager);
  comment = any non-viewer; read = anyone.

### P2. Incident postmortem
- **UI:** **New postmortem** opens a templated postmortem (timeline / impact / root cause / action
  items) that can record affected components and mint the same follow-ups.
- **Not built (v2 §P2):** **auto-open from an incident webhook** — that needs the CI/observability
  connector (§J8); for now a postmortem is opened manually.

---

## J. Connectors & integrations (Connectors page)

### J1. Add a connection
- **UI:** `/connectors` → choose provider (Jira / GitHub / Google Drive), name it, optionally paste an
  API token, and provide provider config JSON (e.g. Jira: `base_url`, `email`, `project_id`,
  `jira_project_key`; GitHub: `owner`, `repo`).
- **API:** `POST /api/v1/connectors/connections` (token is encrypted at rest) · **MCP:**
  `list_connections`.

### J2. Connect via OAuth
- **UI:** on a connection row → **Connect** (or **Reconnect**). The browser is redirected to the
  provider's consent screen; after approval the provider redirects back and the connection shows
  **authorized**.
- **API:** `GET /api/v1/connectors/oauth/{connection_id}/authorize` → provider URL (CSRF `state` is a
  signed JWT); provider redirects to `GET /api/v1/connectors/oauth/callback`, which exchanges the
  code, stores encrypted access + refresh tokens, and (for Jira) resolves the cloud id.
- **Setup:** requires registered OAuth apps + `*_OAUTH_CLIENT_ID/SECRET` env vars.

### J3. Sync from Jira
- **UI:** on a Jira connection → **Sync now** (full sync). Imports epics→summary tasks and
  stories→leaf tasks (idempotently, via `ExternalRef`), tags tasks with their active sprint, and
  **auto-replans** the project when new tasks are created. The result shows created/updated/skipped.
- **API:** `POST /api/v1/connectors/connections/{id}/sync` (full) and `.../sync/incremental` ·
  **MCP:** `trigger_jira_sync`.
- **Background:** an arq worker runs an incremental reconciliation poll on a cron as the correctness
  backstop behind webhooks.

### J4. Receive provider webhooks (live updates)
- **Flow:** Jira/GitHub POST to `/webhooks/jira` / `/webhooks/github`. The receiver verifies the HMAC
  signature, matches the event to active connection(s), and enqueues an arq job (never processes
  inline). Jira issue events upsert the task; GitHub `pull_request` events upsert the PR cache.
- **Setup:** `JIRA_WEBHOOK_SECRET` / `GITHUB_WEBHOOK_SECRET`.

### J5. Jira sprints & status history
- **API:** `GET /api/v1/connectors/jira/{id}/boards`, `.../sprints?board_id=`, and
  `POST /api/v1/connectors/jira/{id}/history?issue_key=` (pulls the issue changelog into
  `TaskStatusHistory`, which feeds the burndown).

### J6. Read GitHub / Google Drive content
- **API:** `GET /api/v1/connectors/github/{id}/file?path=`, `.../github/{id}/pulls`,
  `.../github/cached-prs`; `GET /api/v1/connectors/gdrive/{id}/docs`, `.../gdrive/{id}/docs/{file_id}`
  · **MCP:** `read_repo_file`, `list_open_prs`, `read_design_doc`.
- **Not built (v2 §J6):** PR **review metrics** (time-to-review, churn, test status) and commit
  attribution to components — these would feed a PR-latency quality-risk indicator (the quality
  family is currently fed by §J8 build failures / incidents instead).

### J8. CI / observability events **[new — minimal viable]**
- A generic event substrate: `kind` ∈ `deploy | build_failure | incident_open | incident_close`,
  optionally tagged to a component. Events appear in the **Activity** feed (§B3) and feed the
  **quality-risk** family (§Q1); an `incident_open` **auto-opens a postmortem** (§P2).
- **Webhook:** `POST /webhooks/events` (HMAC via `EVENTS_WEBHOOK_SECRET`; recorded inline — it's a
  light write). **API/UI:** `GET /api/v1/projects/{id}/activity` (feed) and
  `POST /api/v1/projects/{id}/activity` (planner-gated manual ingest, used by the Activity tab and
  the plugin) · **MCP:** `get_activity`, `record_activity`. Datadog / Sentry / GitHub Actions can be
  layered on this substrate.

### J7. PagerDuty / on-call **[not built]**
- Deferred: an optional connector to pull on-call schedules into capacity (v2 §J7). Needs the
  external PagerDuty integration; the interrupt-budget/on-call capacity model (§F2/§F4) is also not
  built, so there's nothing to feed yet.

---

## K. Real-time live refresh
- **Flow:** while logged in, the frontend opens a Server-Sent Events stream
  (`GET /api/v1/events/stream?token=`). Web-process actions (replan, baseline) publish change events;
  the client invalidates its caches so views refresh without a manual reload.
- **Limitation:** single backend process only — events from the arq worker (e.g. webhook-driven
  syncs) don't propagate here yet (Redis pub/sub is the multi-process upgrade).

---

## L. Claude plugin (agentic flows)

### L1. Install & configure the plugin
- Install the `canopy` plugin (cataloged by `.claude-plugin/marketplace.json`). Configure
  `api_base_url` (e.g. `http://localhost:8000`) and `api_token` (a JWT from `POST /auth/login`). The
  MCP server then exposes ~50 curated tools that call the REST API.

### L2. Plan a roadmap (skill + subagent)
- Ask Claude to plan/break down/sequence work. The **`planning-roadmaps`** skill (and **`gantt-planner`**
  subagent for heavier work) create projects/phases/tasks/dependencies and run `replan_schedule`,
  reporting the critical path and end date.

### L3. Sync from Jira (skill + subagent)
- Ask Claude to "sync Jira". The **`syncing-jira`** skill / **`jira-sync`** subagent find the Jira
  connection, run an incremental (or full) sync, then reconcile the plan (`replan_schedule`).

### L4. Write, propose & shepherd decisions (skill)
- The **`writing-adrs`** skill drafts an ADR with a consistent template and records it (`create_adr`),
  proposes one on an engineer's behalf (`propose_adr`), runs it through the review lifecycle
  (`transition_adr`), discusses/reviews it (`comment_adr`, `get_adr`), or imports one from a
  repo/Drive doc (`import_adr`). It also reads the **decision queue** (`decision_queue`) as a
  morning surface.
- **Not built:** a `/canopy propose-adr` slash command — proposing is available as the
  `propose_adr` MCP tool today.

### L5. Plan capacity (skill)
- The **`capacity-planning`** skill reads `get_capacity` + `list_alerts`, cross-references the critical
  path, and uses `whatif_schedule` to test staffing/scope changes before committing them.

### L6. Assess risk (subagent)
- The **`risk-analyst`** subagent leads with `get_risk` (score + breakdown), then drills with
  `list_alerts`, `get_burndown`, the critical path, `decision_queue`, and `adr_impact` into a
  prioritized risk report — and can record agreed mitigations via `log_risk_mitigation`.

### L7. Inspect the current user's workspace (tool)
- `my_workspace` returns the caller's linked engineer profile, assigned open tasks, and the
  decisions they own / must review (the API behind §M).

### L8. Detect architecture drift (subagent) **[new — v2 §L7]**
- The **`drift-sentinel`** subagent reads code via its tools, maps imports back to components using
  their code-binding `module_prefix`es, flags implicit decisions, and calls `scan_drift` — then
  reports the refreshed drift score + queue and can `reconcile_drift` with the architect's go-ahead.
  Tools: `list_components`, `list_code_bindings`, `read_repo_file`, `scan_drift`, `get_drift`,
  `reconcile_drift`, `adr_impact`. This is the producer behind the Drift tab (§N).
### L9. Decision-deadline nudger (skill) **[new — v2 §L8]**
- The **`decision-deadline-nudger`** skill reads the `decision_queue`, finds `deferred` ADRs whose
  `decide_by` is approaching/overdue, and posts a nudge (alternatives + the open question) to the
  owner via `comment_adr`.

### L10. PR-to-ADR linker (skill) **[new — v2 §L9]**
- The **`pr-to-adr-linker`** skill maps a PR's changed paths to components (via code bindings),
  finds the ADRs governing them (`adr_impact`), and judges whether the PR implements / contradicts /
  is unrelated to each — building implementation traceability.

---

## M. Engineer workspace (`/me`)

Makes engineers first-class (v1 had no engineer-facing surface). A logged-in user is mapped to a
team member via `Engineer.user_id` (§A5).

### M1. My work
- **UI:** `/me` (also "My work" at the top of the sidebar) → the user's profile (role + linked
  engineer's GitHub / timezone / committed hours / skill tags), their **assigned open tasks**
  (most-critical first, then soonest due), and the **decisions they own** and **decisions to
  review** — each linking into the owning project's Gantt / Decisions tab.
- **API:** `GET /api/v1/me/workspace` · **MCP:** `my_workspace`.
- **Note:** if no engineer is linked to the account, the page prompts to have an admin link one on
  the Team page; tasks/decisions are empty until then.

### M2. Today (daily focus)
- **UI:** `/me/today` (linked from `/me`) → today's focus: assigned open tasks that are **critical
  or due within 7 days**, and the decisions to push (owned ADRs in `proposed`/`under_discussion`).
- **API:** `GET /api/v1/me/today`.
- **Not built (v2 §M):** PRs awaiting the user's review (needs GitHub PR-metrics, §J6) and
  decision-queue items filtered to the user's components.

---

## Known UI gaps (currently API/MCP-only)
These flows work via the API and the Claude plugin but have no React form yet — candidates for the UI
backlog:
- **What-if** scheduling (C5).
- Project rename/archive/date edits and **holiday** management (B4, C7).
- *(closed previously: G5 blast radius; Risk (§Q) + portfolio scores (§B1); user/role mgmt (A3) +
  engineer workspace (§M); per-role enforcement (§A3a); drift detection (§N); retros/postmortems
  (§P). Closed this revision: **CI/observability events + Activity feed** (§J8) with incident
  postmortem auto-open (§P2); the **quality** risk family + **drift-into-risk** + **risk timeline**
  (§Q); **ADR doc-import** UI (G6); **component owner/criticality/tier** (§G1); **`/me/today`** (§M);
  the **decision-deadline nudger** + **PR-to-ADR linker** skills (§L8/§L9).)*

## Not built (deliberately deferred — with rationale)
- **OIDC/SSO + `HttpOnly`-cookie tokens** (§A1): a substantial auth overhaul; the `Bearer` JWT path
  works and is the safe default. Deferred rather than half-built.
- **Multi-process real-time** (§K): Redis pub/sub — an infra change that can't be verified in this
  single-process setup; SSE works in-process today.
- **Capacity overhaul** (§F2–F5): hours-based allocation, interrupt budget, planned-vs-realized,
  PTO→CPM, skill-task fit — a large model change; allocation stays percent-based.
- **PagerDuty / on-call** (§J7): an external connector with nothing to feed until the capacity
  overhaul lands.
- **GitHub PR-latency metrics** (§J6): needs deep repo crawling (like drift's live path); the
  quality-risk family is fed by §J8 events instead.
- Smaller follow-ups: Slack/email **alert delivery** (I) + **decision SLA notifications** (G3);
  hard-enforced decision **approval gates** (G3, `can_accept` is advisory); connector **RBAC**;
  resource **leveling**; drift **suppression-management UI** + non-Python analysis; nightly
  **schedulers** for drift scans / risk snapshots (run via the plugin today).

---

*Maintained alongside the code. See `CLAUDE.md` → "Keeping USER_FLOWS.md in sync".*
