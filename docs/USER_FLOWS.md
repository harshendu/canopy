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
  status back**. Mirrored status on canopy tasks is read-only. **Scoped exception (§C10):** from
  an architect-reviewed **draft plan**, canopy can **create** new tickets and **update ticket
  content** (summary / description / story points + the epic→story parent link) — but **status is
  still never written**; the new issues flow back in via the normal Jira sync.
- **GitHub** owns code + some architecture docs. **Google Drive** holds design docs. Canopy reads
  these on demand and caches lightly. **Scoped write (§S):** canopy can *upload an export snapshot*
  (a generated PDF/CSV) into a connected Drive — it stores its own artifacts there but still does
  not own the design docs it reads.

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

### A6. Bounded agency — scoped agent tokens **[new]**
As agents do more of the writing, their authority should be **intentionally constrained** (Team
Topologies / "bounded agency"; the reversibility distinction *is* the human-in-the-loop policy —
see [`AI_NATIVE_EXECUTION.md`](./AI_NATIVE_EXECUTION.md) §3/§8, roadmap gap #4). An access token
carries a **scope** claim: `full` (a human login — does anything its role allows) or `agent` (a
bounded token an architect hands to Claude). An `agent` token acts **as its issuer** but is
forbidden from **one-way-door / external-write** actions; **two-way-door** actions run freely
(bias to action on reversible work).
- **Mint:** `POST /api/v1/auth/agent-token` (planner) → an `agent`-scoped JWT for the current
  user (`{expires_minutes?}`, default 7 days, max 30). Configure the plugin's `CANOPY_API_TOKEN`
  with this instead of a full login token.
- **What an agent token is blocked from (403):** accepting a **one-way-door** decision
  (`PATCH /architecture/adrs/{id}` → `accepted` when `reversibility=one_way`, §G2); **pushing a
  draft plan to Jira** (`POST /draft-plans/{id}/push-to-jira`, §C10 — an external write);
  **applying a scenario** to the live plan (`POST /scenarios/{id}/apply`, §T5). Everything else
  (creating/updating tasks, proposing/refining decisions, accepting *two-way* doors, specs,
  blockers, risks, draft authoring) stays open. Enforced in `app/api/deps.py`
  (`require_human` / `HumanOnly`); the scope rides in the JWT (`app/core/security.py`).
- **Not built:** auto-running the coherence guardrails (drift + PR-to-ADR + fitness) on an
  agent-authored PR via webhook — the server can't crawl code itself (§N4), so that scan stays
  agent-driven; the webhook→agent trigger is the remaining piece of roadmap gap #4.

---

## R. Initiatives (the program layer above projects) **[new — v2 §R / C1]**

The architect's unit of work is usually an **initiative** (a.k.a. program) spanning several
projects executed concurrently and decentrally — not a single project. An `Initiative` groups
projects and rolls up their health.

### R1. List / create initiatives
- **UI:** `/initiatives` (sidebar) — list initiatives and (architect) create one (KEY + name +
  optional outcome statement + target date). Each row opens its cockpit.
- **API:** `GET /api/v1/initiatives`, `POST /api/v1/initiatives` (architect, also accepts `tags`),
  `GET/PATCH/DELETE /api/v1/initiatives/{id}` (PATCH also accepts `tags`, `health`, `status_note` —
  stamping `status_updated_at`; delete **unlinks** sub-projects, never deletes them) · **MCP:**
  `list_initiatives`, `create_initiative`, `set_initiative_health`, `set_tags`/`add_tags`/`remove_tags`.

### R2. Link a project to an initiative
- **UI:** `/projects` → per-project **initiative** select (architect). A project carries
  `initiative_id`.
- **API:** `PATCH /api/v1/projects/{id}` (`initiative_id`; `null` unlinks); `POST /api/v1/projects`
  also accepts `initiative_id` · **MCP:** `set_project_initiative`, `create_project(initiative_id=)`.

### R3. Initiative cockpit (rolled-up health)
- **UI:** `/initiatives/:id` — outcome statement, a **delivery meta bar** (manual health + status
  note + tags, editable by architects — §B4), an **on track / behind target** badge, aggregate
  cards (progress, **worst** sub-project risk, **worst** drift, open-decision backlog, latest end
  vs target, **P85 forecast** §C8), the **cross-project critical path** (§R4), an initiative-scoped
  **risk register** (RAID, §Q3a), the sub-project cards (each with its own risk/drift, linking
  into the project), and a **Linked Jira tickets** panel (link Jira tickets into the initiative —
  §J9). An **Export ▾** control exports the initiative as a PDF/CSV snapshot (§S).
- **API:** `GET /api/v1/initiatives/{id}/rollup` (per-project summaries + aggregates: total/completed
  tasks, avg %, latest `project_end`, max `risk_score`/`drift_score` with the owning level,
  `open_decisions` = ADRs proposed/under-discussion, `on_track`) · **MCP:** `get_initiative_rollup`.
  The per-project summary is the same `summarize_project` the portfolio (§B1) uses.

### R4. Cross-project dependencies & critical path **[new]**
- **Cross-project hand-offs:** a dependency may link tasks in **different projects of the same
  initiative** (a between-team hand-off). `POST /api/v1/dependencies` now validates this: a
  cross-project edge is rejected (400) unless both projects share one initiative. Per-project Gantt
  / replan stay project-local (they ignore cross-project edges); the hand-offs surface at the
  initiative level.
- **Cross-project critical path:** the **initiative cockpit** shows the longest chain of dependent
  work across sub-projects, in working days, with cross-project hand-offs highlighted (amber). Built
  over the union of the initiative's tasks + dependencies with the same CPM as per-project
  scheduling (structural, calendar-independent).
- **API:** `GET /api/v1/initiatives/{id}/critical-path` (ordered critical chain with each task's
  project, total working days, `spans_projects`, and the `handoffs`; cyclic cross-project deps →
  409) · **MCP:** `get_initiative_critical_path`.

---

## B. Projects & portfolio

### B1. View the portfolio dashboard
- **UI:** `/portfolio` (landing page). Shows a completion bar chart and a card per project
  (avg % complete, completed/total tasks, critical-task count, end date, and **risk + drift score
  badges** — see §Q / §N). Clicking a card opens it. An **Export ▾** control exports the whole
  portfolio as a PDF/CSV snapshot (§S).
- **API:** `GET /api/v1/projects/portfolio` (each `ProjectSummary` includes `risk_score`/`risk_level`
  and `drift_score`/`drift_level`, computed by the same scorers as the Risk/Drift tabs) · **MCP:**
  `list_projects`.
- **Not built (v2 §B1):** last-decision recency and sortable columns.

### B2. Create a project
- **UI:** `/projects` → enter KEY + name → "Add".
- **API:** `POST /api/v1/projects` (`key`, `name`, optional `initiative_id`, `start_date`,
  `target_date`) · **MCP:** `create_project`.
- **Notes:** `key` is a unique slug (e.g. `PLATFORM`). A project can belong to an **initiative**
  (§R) via `initiative_id`.

### B3. Open a project (the cockpit)
- **UI:** `/projects/:id` — a tabbed workspace: **Gantt · Board · Specs · Dependencies · Capacity ·
  Decisions · Docs · Architecture · Drift · Roadmap · Plan → Jira · Jira Links · Burndown ·
  Delivery · Risk · Retros · Activity** (the **Specs** tab is §W, **Docs** is §V, **Delivery** is
  §X, and the **Jira Links** tab links Jira tickets into the project — §J9).
  The header has an **Export ▾** menu (PDF/CSV snapshot, §S), a **5-day week** toggle, **Set
  baseline**, and **Schedule (CPM)** (the planning controls and the add-task/dependency forms are
  hidden for roles that can't use them — §A3a). A tab can be deep-linked with `?tab=` (e.g.
  `/projects/:id?tab=drift`).

### B4. Edit / archive a project · toggle working week · status & tags
- **UI:** the "5-day week" checkbox in the project header toggles weekend-aware scheduling. A
  **delivery meta bar** under the title shows the manual **health** (on_track / at_risk / off_track,
  RAG badge) + a weekly **status note** headline + **tags**, all inline-editable ("edit status").
- **API:** `PATCH /api/v1/projects/{id}` (`name`, `description`, dates, `archived`, `skip_weekends`,
  `tags`, `health`, `status_note` — setting health/status_note stamps `status_updated_at`),
  `DELETE /api/v1/projects/{id}` · **MCP:** `set_project_health`, `set_tags`/`add_tags`/`remove_tags`.
- **Notes:** `health` is the architect's narrative status that sits **alongside** the computed risk
  score (it doesn't override the score); `health=null` means "use the computed on-track signal".
  The portfolio card (§B1) shows the health badge, status note, tags, and open-risk count.
- **UI gap:** renaming/archiving/date edits are API-only today (the header has the weekend toggle +
  the health/status/tags meta bar).

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

### C1a. Task detail panel — estimates, tags, progress, blockers, risks **[new]**
- **UI:** click a task bar in the **Gantt** (or a card on the **Board**) to open a right-side
  **detail panel**. It edits the task's **progress** + **duration**, a **3-point estimate**
  (aggressive / practical / buffered, with the computed PERT mean + spread + a confidence badge),
  **tags**, the task's **blockers** (raise/resolve with category + severity + needed-by), and the
  task-scoped **risk register** (RAID).
- **API:** `PATCH /api/v1/tasks/{id}` (`tags`, `estimate_optimistic`/`estimate_likely`/
  `estimate_pessimistic`; `TaskRead` returns computed `pert_mean` + `estimate_spread`) ·
  `GET/POST /api/v1/tasks/{id}/blockers` · `GET/POST /api/v1/risks?scope_level=task&scope_id=…` ·
  **MCP:** `set_task_estimates`, `set_tags`/`add_tags`/`remove_tags`, `raise_blocker`, `add_risk`.
- **Notes:** the 3-point estimate is **advisory** — it never moves the scheduling `duration`; a wide
  optimistic→pessimistic spread instead raises the schedule-risk "estimate uncertainty" indicator
  (§Q1). There is deliberately **no** "apply estimate to duration" action.

### C2. Add a dependency
- **UI:** Gantt tab → "Add dependency (finish → start)" form: pick predecessor + successor → "Link".
- **API:** `POST /api/v1/dependencies` (supports `type` FS/SS/FF/SF and `lag`) · **MCP:**
  `link_dependency`.
- **Notes:** the UI creates finish-to-start links; other types + lag are via API/MCP. A
  **cross-project** dependency (a hand-off between teams) is allowed only when both tasks' projects
  share an **initiative** (§R4); it appears on the initiative critical path, not the per-project Gantt.

### C3. Schedule (Critical Path Method)
- **UI:** project header → **Schedule (CPM)**. A banner reports scheduled task count, the critical
  path, the project end date, and any **deadline violations** (also flagged red on the Gantt).
- **API:** `POST /api/v1/projects/{id}/replan` · **MCP:** `replan_schedule`.
- **Result:** computes start/end dates, `is_critical`, and float for every task, honoring the
  project's working calendar (weekends + holidays) and any task's set start date (treated as
  start-no-earlier-than). Cycles return a 409 error.

### C4. Set / view a baseline (schedule variance)
- **UI:** project header → **Set baseline** opens a note field ("Why re-baseline?") and snapshots
  current start/end as the plan-of-record. The Gantt draws a faint gray "planned" strip under each
  bar so **schedule variance** (current-vs-baseline) is visible. Re-baselining is a deliberate,
  *reasoned* reset — re-planning is a feature, not a failure — so each one is logged and shown in a
  **Baseline history** panel under the Gantt (date · reason · task count · planned end). The word
  **"drift" is reserved for architecture drift** (§N); the schedule's plan-vs-actual is *variance*.
- **API:** `POST /api/v1/projects/{id}/baseline` (optional `{note}`, returns the logged
  `Baseline`), `GET /api/v1/projects/{id}/baselines` (the history, newest first) · **MCP:**
  `set_baseline` (accepts a `note`).

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

### C8. Probabilistic forecast (Monte-Carlo) **[new — v2 §C-R1]**
- **UI:** Gantt tab → a **Probabilistic forecast** card shows **P50 (likely)** and **P85 (safe)**
  completion dates next to the deterministic CPM date — the honest "when will it ship?" for
  knowledge work. If there isn't enough completed-work history yet, it says so (no fake precision).
  The initiative cockpit (§R) shows the same P50/P85 for the whole program.
- **API:** `GET /api/v1/projects/{id}/forecast`, `GET /api/v1/initiatives/{id}/forecast` · **MCP:**
  `get_forecast` (pass `project_id` *or* `initiative_id`).
- **How:** `app/services/forecast.py` (pure) runs a Monte-Carlo simulation — repeatedly burning down
  the remaining items by sampling the team's **historical weekly throughput** (completed items/week,
  including stall weeks, from `TaskStatusHistory` — the same source as burndown §H). Needs no
  per-task estimates; reports a distribution, not a single date. Insufficient until ~3 weeks of
  throughput exist.

---

## C9. Flow board (Kanban + WIP + aging) **[new — v2 §C-R2]**
- **UI:** project → **Board** tab → leaf tasks grouped into **status lanes** (from the Jira-mirrored
  `status`; done lanes sort last). Each lane shows **WIP** (count of not-done tasks); set a **WIP
  limit** (client-side) and lanes over it turn red. Cards show **age in status**; a card **aging**
  beyond the team's **cycle-time P85** is highlighted amber (the leading "this is stuck" signal).
- **API:** `GET /api/v1/projects/{id}/board` (lanes with per-task `age_days`/`aging`, `wip`, plus
  `cycle_time_p85_days` and `aging_count`) · **MCP:** `get_board`. Logic is pure in
  `app/services/flow.py` (grouping + P85 + aging); age/cycle dates come from `TaskStatusHistory`.
- **Not built:** **persisted** per-lane / per-engineer WIP limits (the limit is a client-side knob
  for now); drag-to-change status (status is Jira-owned, read-only).

---

## C10. Draft plans → create/update Jira tickets **[new]**

The architect's "plan first, then make the tickets" flow. A **draft plan** is a staging area
(its own tables — kept out of the live Gantt/CPM/board) where the architect proposes phases,
tasks, estimates, and story points, reviews them, then **creates the Jira tickets** from the
draft. This is the only place canopy writes *to* Jira, and it writes **content only** — status
stays Jira-owned (§Source-of-truth boundaries).

### C10.1 Create & review a draft plan
- **UI:** project → **Plan → Jira** tab → "New draft plan" (title + optional **source** note, e.g.
  the design-doc/PRD url). Select a plan to expand it: add proposed tasks (name, **type** —
  story/task · epic/phase · milestone, **estimate (days)**, **story points**, and a **parent**
  epic to nest under), and remove tasks. Drafts carry a status: **draft → synced → archived**.
- **API:** `GET/POST /api/v1/projects/{id}/draft-plans`, `GET/PATCH/DELETE
  /api/v1/draft-plans/{plan_id}`, `POST /api/v1/draft-plans/{plan_id}/tasks`,
  `PATCH/DELETE /api/v1/draft-tasks/{task_id}` (writes are planner-gated) · **MCP:**
  `list_draft_plans`, `create_draft_plan`, `get_draft_plan`, `add_draft_task`,
  `update_draft_task`, `delete_draft_task`.

### C10.2 Push the draft to Jira (create / update tickets)
- **UI:** expand a draft → **Create Jira tickets** (becomes **Update Jira tickets** once synced).
  Picks the project's Jira connection automatically (or choose one when several match). Reports
  per-task created/updated/failed with the new Jira keys; a partial failure doesn't abort the rest.
- **API:** `POST /api/v1/draft-plans/{plan_id}/push-to-jira` (optional `connection_id`) · **MCP:**
  `push_draft_to_jira`. Logic is in `app/services/draft_sync.py`; the Jira write methods are
  `JiraConnector.create_issue` / `update_issue` (`POST/PUT /rest/api/3/issue`, description as ADF).
  Epics (summary tasks) are created before their stories so the parent link resolves; each pushed
  draft task is stamped with its Jira id/key, so a **re-push updates** rather than duplicates.
- **Then sync back:** canopy does **not** create local tasks on push — run a Jira sync (§J3) to
  pull the new issues in as canopy tasks (then `replan_schedule`). This keeps Jira the source of
  truth for the materialized tickets.
- **Jira config (per connection, §J1):** `story_point_field` (e.g. `customfield_10016`; without it
  points are skipped), and optional `epic_issue_type` / `story_issue_type` (default `Epic` / `Story`).

### C10.3 Not built (deliberate limits)
- **No status writes** (by design — the source-of-truth rule holds).
- **Draft dependencies** aren't modeled — the draft captures the WBS (epic→story via `parent_id`)
  and estimates; sequencing/dependencies are added on the live tasks after sync-back.
- No **diff/preview** of "what will change in Jira" before a push, and no automatic
  `replan_schedule` after sync-back (run it from the project header).

---

## D0. Blockers (flagged impediments) **[new — v2 §D-R2]**

The leading signal that work has stalled: an engineer flags an impediment on a task, and it
surfaces where decisions get made — the engineer workspace and the project alerts digest.

### D0.1 Raise / resolve a blocker
- **UI:** `/me` → **Blockers** section → "Flag a blocker on…" (pick one of your tasks + a reason);
  open blockers list with a **resolve** action. Also raisable from the **task detail panel** (§C1a)
  with the enrichment fields below.
- **API:** `POST /api/v1/tasks/{task_id}/blockers` (`reason`, optional `blocking_task_id`,
  `category` [dependency|resource|decision|external|technical], `severity`
  [low|medium|high|critical], `owner_engineer_id`, `needed_by`; `raised_by_engineer_id` defaults to
  the caller's engineer), `GET /api/v1/tasks/{task_id}/blockers`,
  `GET /api/v1/blockers?project_id=&open_only=`, `PATCH /api/v1/blockers/{id}` (`resolved` + the
  enrichment fields), `DELETE /api/v1/blockers/{id}` (planner) · **MCP:** `raise_blocker` (now takes
  category/severity/owner/needed_by), `list_blockers`, `resolve_blocker`. Raise/resolve = any
  contributor; delete = planner.

### D0.2 Where blockers surface
- **`/me` workspace (§M):** open blockers on your tasks or raised by you (`MyWorkspaceResponse.blockers`).
- **Alerts digest (§I/Q):** each open blocker is a `blocked` alert in the project's alerts list
  (shown in the Risk tab). **high/critical** `severity` escalates it from a warning to an **error**,
  and a `needed_by` date is appended to the message.
- **Not yet:** blocked-time folded into the composite **risk score** (Q-R2) and a red marker on the
  Gantt/dependency-graph nodes — follow-ups.

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
  capacity, and skill-task fit scores — allocation is still percent-based. **Engineer availability
  now exists (§F4)** but informs the capacity/over-allocation views only, **not** CPM dates.

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
  `project_id` is `null` in the response and each row carries `projects` = contributing keys, and
  `availability` = week→factor for any week below full capacity) ·
  **MCP:** `get_capacity` (`project_id` now optional). Closes the v2 §F cross-project blind spot.

### F4. Engineer availability (PTO / leave / ramp-up) **[new]**
- **UI:** `/team` → an engineer's **availability** editor — add date ranges with a **capacity
  factor** (0 = fully out, 0.5 = half). Reduced-capacity weeks are shaded on the capacity heatmap.
- **API:** `GET /api/v1/team/availability?engineer_id=`, `POST /api/v1/team/availability`,
  `PATCH/DELETE /api/v1/team/availability/{id}` (`EngineerAvailability`: engineer, date range,
  `capacity_factor`, note). Reads are open; writes are planner-gated.
- **Effect:** the capacity heatmap, the **risk** over-allocation indicator, and the **alerts**
  digest now flag a week as over-allocated when summed allocation exceeds **100% × the worst
  availability factor that week** (so 60% allocation during half-time PTO is already "over").
- **Deliberately not built:** availability does **not** push CPM/schedule dates (that is
  resource-constrained scheduling/leveling — a separate, harder problem); it adjusts the
  capacity/over-allocation *views* only. Per-person time-off does not yet sync from any calendar.

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

### G7. Fitness functions (machine-checkable decisions) **[new — v2 §G-R1]**
- **What:** a decision can carry **fitness functions** — dependency rules over the component graph
  the drift scan enforces. `forbid`: source must NOT depend on target; `require`: it MUST. When the
  ADR is **accepted**, a violation appears in the drift queue as a `fitness_violation` (the heaviest
  drift signal — an accepted decision isn't being honored), and **auto-resolves** when the code is
  fixed. This is the decision→verification spine: a decision that defends itself.
- **UI:** Decisions tab → expand an ADR → **Fitness functions** (list + add `forbid`/`require` rule
  picking source/target components). Violations show on the **Drift** tab (§N).
- **API:** `GET/POST /api/v1/architecture/adrs/{id}/fitness`, `DELETE /api/v1/architecture/fitness/{id}`
  (components must be in the ADR's project) · **MCP:** `add_adr_fitness`. The ADR detail
  (`GET .../adrs/{id}`) includes `fitness_functions`.
- **Not built:** `Task.implements_adr_id` (decision→task traceability) and a full **traceability
  ledger** joining decision → tasks → PRs → fitness status (v2 §T) — the next slice.

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
  over-allocations / **open blockers** (warning), unscheduled work (info).
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
    float consumption, **estimate uncertainty** (count of tasks whose 3-point estimate spread is
    wide — see §C1a; stays inside the schedule weight, no new family).
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
- **UI:** Risk tab → a sparkline of recent risk **snapshots** next to the score; planners can also
  **Capture snapshot** on demand.
- **API:** `GET /api/v1/projects/{id}/risk/timeline`, `POST /api/v1/projects/{id}/risk/snapshot`.
  Snapshots persist score + level; the trend matters more than any single value.
- **Auto-capture (v2 §Q-R3):** the arq **worker** runs a nightly cron (`capture_risk_snapshots`,
  03:00) that snapshots **every** project, so the trend is real without anyone clicking. The job is
  `run_risk_snapshots` in `app/api/v1/risk.py`.

### Q3. Mitigation log
- **UI:** Risk tab → **Acknowledge** any indicator with a note, an owner, and a check-in date; open
  mitigations show inline under their indicator and in the **Mitigation log** (resolve / reopen /
  delete).
- **API:** `GET` (embedded in the risk response), `POST/PATCH/DELETE
  /api/v1/projects/{id}/risk/mitigations[/{mid}]` · **MCP:** `log_risk_mitigation`.
- **Note:** the mitigation log **acknowledges a computed indicator**. It is distinct from the **risk
  register** (Q3a), which tracks human-identified qualitative risks.

### Q3a. Risk register (RAID) **[new]**
- A **human-tracked** risk register, kept **separate from the computed risk score** (it does not feed
  the 0–100 score). Each entry hangs off a **task / project / initiative**, graded by **probability ×
  impact** (low/medium/high each → an exposure of 1–9, banded to low/moderate/high/critical), with an
  owner, a **mitigation** (lower the probability), a **contingency** (if it occurs anyway), and a
  target resolution date. Status: open | mitigating | accepted | resolved | occurred (terminal
  statuses stamp `resolved_at`).
- **UI:** a **"Risk register (RAID)"** section in the project **Risk** tab, on the **initiative**
  cockpit, and in the **task detail panel** (§C1a) — list with exposure/status badges + add / status /
  delete. Writes are planner-gated.
- **API:** `GET /api/v1/risks?scope_level=&scope_id=&status=`, `POST /api/v1/risks`,
  `GET/PATCH/DELETE /api/v1/risks/{id}`, `POST /api/v1/risks/{id}/close` · **MCP:** `list_risks`,
  `add_risk`, `update_risk`, `close_risk`.
- **Where it surfaces:** the portfolio card shows a project's **open-risk count** (§B1/B4); an open
  register risk **past its target_resolution_date** appears in the alerts digest (§I) as a
  `risk_overdue` alert (error when high-exposure) — reporting only, the **computed score is
  unchanged**.

### Q4. Not built (v2 §Q)
- Automated **check-in follow-ups** / notifications on mitigations past their date.
- PR-latency / churn **quality** metrics (need GitHub PR-metrics, §J6). *(The nightly risk-snapshot
  schedule is now built — the arq worker captures it; see Q2.)*
- Folding the **risk register** into the computed score (deliberately kept separate for now), and the
  full RAID set (assumptions / issues) — the register is risks-only today.

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
- **API:** `GET /api/v1/projects/{id}/drift` (score + events + **`last_scanned_at`** and
  **`scan_due`**) · `POST /api/v1/projects/{id}/drift/scan`
  (architect-gated) accepts the Sentinel's observations (`actual_edges`, `inactive_component_ids`,
  `implicit_signals`), runs detection (applying learned suppressions), and upserts events — new
  findings open, resolved ones disappear, triaged ones persist. **MCP:** `get_drift`, `scan_drift`.
- **Scan staleness (v2 §N-R1):** every scan is logged (`DriftScan`), so the Drift tab shows
  **last scanned** and a **scan due** badge when code bindings exist but the scan is missing or
  older than ~7 days — prompting a Sentinel re-scan. (The server can't crawl code itself, so the
  loop is: staleness surfaced here → the Drift Sentinel re-scans. A push-webhook that *enqueues* the
  Sentinel is the remaining piece — N4.)

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
  `jira_project_key`; GitHub: `owner`, `repo`). Jira also accepts optional **ticket-creation** keys
  used by §C10: `story_point_field` (e.g. `customfield_10016`), `epic_issue_type` (default `Epic`),
  `story_issue_type` (default `Story`).
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
- **Drive uploads (write):** the Drive connector also has `upload_file` (multipart) used by export
  snapshots (§S) to store a generated PDF/CSV in Drive — the one place canopy writes to Drive.
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

### J9. Link Jira tickets to a project / initiative **[new]**
- **What:** instead of mirroring a whole Jira project (§J3), the architect links one or more
  **specific** Jira tickets (initiative / epic / story) to a canopy **Project** or **Initiative**.
  canopy reads the linked ticket **plus its full descendant subtree** (BFS over Jira `parent`
  links) and maps it idempotently (via `ExternalRef`):
  - **target = project:** every issue becomes a Task in that project (epics → summary tasks,
    stories → leaf tasks, parented within the project). Auto-replans the project when tasks are
    created.
  - **target = initiative:** each descendant **epic becomes a Project** under the initiative and
    its stories become tasks in that project (Jira initiative→epic→story mirrored onto canopy
    initiative→project→task). Existing projects/tasks are re-used (idempotent); the initiative-level
    anchor ticket is associated by the link, not turned into a task.
  Status stays **Jira-owned** (never written back). Re-linking the same ticket is an update, not a
  duplicate. Each Jira issue maps to a single canopy entity regardless of how many links reference it.
- **UI:** the project cockpit's **Jira Links** tab (§B3) and a **Linked Jira tickets** panel on the
  initiative cockpit (§R3): enter a Jira key + (if more than one) pick the Jira connection → **Link
  ticket**; each link row has **Resync** / **Unlink** (writes are planner-gated; unlink keeps the
  already-mapped canopy entities). Shows projects/tasks created/updated/skipped per run.
- **API:** `POST /api/v1/jira-links` (`connection_id`, `jira_key`, `target_type` ∈
  `project|initiative`, `target_id`) → maps the subtree and returns a `JiraLinkSyncResult`;
  `GET /api/v1/jira-links?target_type=&target_id=` (list), `POST /api/v1/jira-links/{id}/resync`,
  `DELETE /api/v1/jira-links/{id}` · **MCP:** `link_jira_ticket`, `list_jira_links`,
  `resync_jira_link`, `unlink_jira_ticket` (skill: `syncing-jira`).
- **Limits:** linking a bare story directly to an *initiative* (no epic in its subtree) maps nothing
  and is reported in the result — link stories to a *project*, or link an epic/initiative-level
  ticket to an initiative. Traversal follows Jira `parent` links (the same hierarchy field §J3 uses),
  not classic "Epic Link"; ancestors are mapped only if you link them too.

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

## S. Export snapshots (PDF / CSV, viewable outside canopy) **[new]**

A point-in-time **snapshot** of a project, initiative, or portfolio as a portable file — so the
architect can store or share it where canopy isn't running. Two formats: **PDF** (the full visual
snapshot: headline stats, a vector **Gantt**, and data tables) and **CSV** (the headline tabular
dataset for that scope). Delivered two ways: **download** in the UI, or **save to a connected
Google Drive**. Snapshots reuse the same aggregation as the live views (`summarize_project`, the
initiative / portfolio rollups), so the numbers match what's on screen.

### S1. Download a snapshot
- **UI:** an **Export ▾** menu in the project header (§B3), the initiative cockpit (§R3), and the
  portfolio page (§B1) → **PDF** / **CSV** download. Open to any authenticated user (it's a read).
- **API:** `GET /api/v1/projects/{id}/export?fmt=pdf|csv`,
  `GET /api/v1/initiatives/{id}/export?fmt=`, `GET /api/v1/portfolio/export?fmt=` — returns the file
  with a `Content-Disposition` attachment. Rendering is `app/services/export_pdf.py` (reportlab —
  pure Python, no headless browser, CI-safe) + `app/services/export_csv.py`; the snapshot data is
  assembled in `app/api/v1/exports.py`.

### S2. Save a snapshot to Google Drive
- **UI:** the same Export menu → **Save to Google Drive** (pick a connection when more than one is
  authorized; shows the resulting Drive link).
- **API:** `POST /api/v1/projects/{id}/export/to-drive` (plus the `initiatives/{id}` and
  `/portfolio` variants) with `{connection_id, fmt}` → uploads the rendered file via the Drive
  connector's new `upload_file` (multipart) and returns `{file_id, name, link}`. An optional
  `folder_id` in the Drive connection config targets a folder.

### S3. What a snapshot contains / limits
- **PDF (project):** summary stats (tasks / completed / critical / end / risk / drift), a vector
  **Gantt** (critical bars red, % progress shaded, milestones marked; the chart is capped to ~26
  scheduled tasks — the full set is in the table), and tables for tasks, milestones, and decisions.
- **PDF (initiative / portfolio):** rollup stats + the sub-project / project table.
- **CSV:** the headline table per scope — a project's **tasks**, or the initiative / portfolio
  **rollup** (one row per project).
- **Not built:** capacity / burndown charts in the PDF, JSON / HTML formats, multi-table CSV
  bundles, and scheduled/automatic exports (snapshots are on-demand). No MCP tool — UI + API only.

---

## T. Scenario simulation (initiative what-if) **[new]**

A durable, named **what-if branch of an initiative**: change team composition, per-engineer
availability, milestones, deadlines, and scope (add/remove/resize tasks + dependencies), then
regenerate **every** analysis view and compare to the live plan before committing. Conceptually
the draft-plan pattern (§C10) raised to the whole initiative, and the only multi-dimensional
what-if (the Gantt's §C5 covers task durations only).

### T1. Create a scenario (snapshot)
- **UI:** initiative cockpit (`/initiatives/:id`) → **Scenarios** → "New scenario". Opens the
  scenario workspace at `/initiatives/:id/scenarios/:scenarioId`.
- **API:** `GET/POST /api/v1/initiatives/{id}/scenarios`, `GET/PATCH/DELETE /api/v1/scenarios/{id}`.
  Creating one **snapshots** the initiative's tasks, dependencies, milestones, allocations,
  availability, and per-project scheduling knobs into editable scenario tables (live data is
  untouched). `base_captured_at` records the snapshot moment. Status: draft | ready | applied |
  archived. · **MCP:** `list_scenarios`, `create_scenario`, `get_scenario`.

### T2. Edit the scenario (team / availability / milestones / deadlines / scope)
- **UI:** the workspace **Edit** tab — sub-panels for team & availability, milestones & deadlines,
  scope (tasks + dependencies), and per-project knobs (start/target/skip-weekends).
- **API (all planner-gated, scenario must be draft/ready):**
  `POST /api/v1/scenarios/{id}/tasks` + `PATCH/DELETE /api/v1/scenario-tasks/{tid}`, and the same
  shape for `dependencies`, `milestones`, `allocations`, `availability`; plus
  `PATCH /api/v1/scenarios/{id}/projects/{project_id}` for project knobs. Deleting a cloned row
  tombstones it (apply then deletes the live row); deleting an added row hard-deletes it.
  · **MCP:** `add_scenario_task`, `update_scenario_task`, `remove_scenario_task`,
  `add_scenario_dependency`, `set_scenario_availability`, `set_scenario_allocation`.

### T3. Regenerate all views over the scenario
- **UI:** the workspace mirrors the project cockpit's tabs (Gantt · Dependencies · Capacity ·
  Board · Burndown · Forecast · Critical path · Alerts), reusing the same view components against
  scenario data. Cross-project critical path + capacity are initiative-wide; the rest take a
  project picker.
- **API:** `GET /api/v1/scenarios/{id}/{gantt|capacity|board|burndown|forecast|alerts}`
  (`?project_id=` where relevant) and `GET /api/v1/scenarios/{id}/critical-path`. Each returns the
  **same schema as the live endpoint**, recomputed over the snapshot — never persisted. Cloned
  tasks pin at their live start (so an unedited scenario reproduces live); added tasks have no
  history (they count as remaining for forecast/burndown). · **MCP:** `scenario_critical_path`,
  `scenario_capacity`.

### T4. Compare to live
- **UI:** a persistent "Compare to live" panel — counts added/removed/changed, project-end delta,
  and critical-path working-day delta.
- **API:** `GET /api/v1/scenarios/{id}/compare` → the diff (by `live_*_id`/`removed` provenance) +
  any **staleness conflicts**. · **MCP:** `compare_scenario` (the key read before applying).

### T5. Apply (commit to canopy's planning layer)
- **UI:** "Apply scenario" (planner only). On a staleness conflict, offer force-apply.
- **API:** `POST /api/v1/scenarios/{id}/apply` (`{force}`). In one transaction: create/update/
  delete the live tasks/dependencies/milestones/allocations/availability (remapping new scenario
  task ids), then replan each affected project, then flip status to `applied`. Returns
  created/updated/deleted + replanned projects. **409** with the conflict list when live drifted
  since the snapshot and `force` is false. · **MCP:** `apply_scenario`.
- **Source-of-truth boundary:** apply writes **canopy planning rows only — never Jira** (Jira
  stays the owner of tickets/status; use the draft-plan flow §C10 for plan→Jira). Replans publish
  live-refresh events (§K).

### T6. Not built (deliberate limits)
- **No resource-leveling / capacity-constrained scheduling:** availability informs the
  capacity/over-allocation views, **not** CPM dates.
- **No scenario → Jira**, **no scenario-vs-scenario diff/branch/merge**, and **no concurrent-edit
  locks** beyond the snapshot watermark conflict check. **Resync** (re-snapshotting after live
  drift) is API-pending.

---

## V. Document graph & coverage (link, don't store) **[new]**

Canopy is a document **graph**, not a document store. PRDs, Figma designs, tech-design docs,
architecture docs, release notes, and QA plans live where they already are (most often
attached to a **Jira epic**, plus Confluence/Drive/Figma URLs); canopy holds typed **links**
to them, deduplicated and attached to the right entity, so the same docs are discoverable for
everyone in context. It never copies the bytes (Source-of-truth boundaries hold). The
`DocReference` model (`app/models/doc.py`) is polymorphic by scope (project / initiative /
task, mirroring the risk register) with a `kind` (prd | design | tech_design | architecture |
release | qa | runbook | other), a `source` (jira_epic | manual | repo | drive), and a
`link_health` (unchecked | ok | stale | broken — checking is a follow-up).

### V1. List / add / manage references + coverage
- **API:** `GET /api/v1/docs?scope_level=&scope_id=&kind=` (open read), `POST /api/v1/docs`
  (planner; validates the scope exists, no FK), `PATCH/DELETE /api/v1/docs/{id}` (planner),
  `GET /api/v1/docs/coverage?scope_level=&scope_id=` (which **expected** kinds — prd / design /
  tech_design / architecture — are present vs **missing**, rolled up so a project includes its
  tasks and an initiative includes its projects + their tasks; absence of a doc is a signal,
  not neutral) · **MCP:** `list_doc_references`, `add_doc_reference`, `get_doc_coverage`.

### V2. AI-driven epic→doc field mapping (one-time setup)
- Teaches canopy which Jira epic field holds which kind of doc, with the AI doing the work.
  Stored on the **Jira connection's config** (`doc_field_mappings`, same JSON home as
  `story_point_field`) — `{mappings: [{jira_field, field_name, doc_kind}],
  parse_description_links, parse_remote_links}`.
- **Flow (skill `mapping-epic-docs`):** `sample_epic_doc_fields` returns a sample of epics' URL-
  bearing fields (joined to Jira's field-name registry), description links, and remote links →
  Claude infers a field→kind mapping from field names + URL domains and **asks the admin to
  confirm** → `set_epic_doc_field_mapping` saves it.
- **API:** `GET /api/v1/connectors/jira/{id}/doc-fields/sample?limit=` (read),
  `GET/POST /api/v1/connectors/jira/{id}/doc-field-mapping` (read / planner-set) · **MCP:**
  `sample_epic_doc_fields`, `get_epic_doc_field_mapping`, `set_epic_doc_field_mapping`.

### V3. Harvest docs from epics
- **API:** `POST /api/v1/connectors/jira/{id}/harvest-docs` (planner) — fetches every synced
  epic, extracts URLs per the mapping (custom fields + optional description links + optional
  Jira remote links), and attaches a `DocReference` to whatever canopy entity the epic maps to
  (a **summary task** for a whole-project sync §J3, a **project** for an initiative-linked epic
  §J9, via `ExternalRef`). Idempotent (dedup per scope+url in the service); re-running updates,
  never duplicates. Returns created/updated/skipped/epics_scanned · **MCP:** `harvest_epic_docs`.
- Logic is pure-where-possible in `app/services/doc_graph.py` (URL/ADF extraction, mapping
  application, coverage roll-up — unit-tested); the Jira connector adds `list_fields`,
  `fetch_epics`, and `fetch_remote_links`.

### V4. Not built (deliberate limits)
- **UI:** a **Docs** tab on the project cockpit and a **Documents** panel on the initiative cockpit
  list references grouped by kind with coverage badges + an add-link form (the AI-driven *setup* /
  harvest stays conversational). Built.
- **No link-health checking** (a HEAD/404 sweep to flag broken/stale links — `link_health`
  exists but stays `unchecked`), **no Jira attachments** harvest (only fields + remote/
  description links), and **no write-back** of canopy-added links onto the Jira epic
  (canopy-local for now).
- **AI doc *generation*** (drafting a tech-design from the PRD + ADRs, syncing the architecture
  doc to reality via drift) is a separate future slice, not part of this flow.

---

## W. Specs — spec-driven development **[new]**

**Intent is the source of truth.** A `Spec` (`app/models/spec.py`) captures the *problem* and
explicit, checkable **acceptance criteria** before work begins; tasks implement it
(`Task.spec_id`); and afterward each criterion is **self-audited** (met | unmet | waived) against
the implementation. This is the intent end of the spine in
[`AI_NATIVE_EXECUTION.md`](./AI_NATIVE_EXECUTION.md) (roadmap gap #1) — the artifact that aligns
humans and agents and the thing an agent struggles without. Source docs (PRD/design) link via the
document graph (§V) or `source_url`; the governing decision links via `adr_id`. Status:
`draft → approved → in_progress → verified → archived` (set explicitly; not transition-gated).

### W1. Create / manage a spec
- **API:** `GET /api/v1/specs?project_id=&status=` (open read), `POST /api/v1/specs` (planner;
  validates the project exists), `PATCH/DELETE /api/v1/specs/{id}` (planner; delete unlinks its
  tasks and drops its criteria first — PG/MySQL enforce the FK) · **MCP:** `list_specs`,
  `create_spec`, `set_spec_status`.

### W2. Acceptance criteria
- **API:** `POST /api/v1/specs/{id}/criteria` (planner), `PATCH /api/v1/criteria/{id}`
  (**contributor** — the implementing engineer or the agent records the verdict),
  `DELETE /api/v1/criteria/{id}` (planner). A criterion carries `text`, `status`
  (open|met|unmet|waived), an optional `verification` note (how it was checked), and `sort_order`
  · **MCP:** `add_spec_criterion`, `update_spec_criterion`.

### W3. Link work + self-audit
- A task implements a spec via `Task.spec_id` (`PATCH /api/v1/tasks/{id}` with `spec_id`; planner,
  or an engineer on their own task) · **MCP:** `link_task_to_spec`.
- `GET /api/v1/specs/{id}` returns the **self-audit bundle**: the spec + its criteria + the linked
  tasks (name/status/percent) + computed **readiness** (`criteria_met` / `criteria_total` excluding
  waived, `acceptance_ratio`). Readiness is pure in `app/services/specs.py` · **MCP:** `get_spec`.
- **Skill `spec-driven-development`** scripts the loop: draft the spec from a PRD/ADRs → write
  checkable criteria → approve → plan + link the work (via `drafting-jira-tickets`) → self-audit
  each criterion against the implementation → mark `verified` when all are met.

### W4. Not built (deliberate limits)
- **UI:** a **Specs** tab on the project cockpit lists specs, creates them, and expands each into
  its problem + acceptance criteria (with a readiness bar and contributor-writable verdicts) +
  implementing tasks. Built.
- **No status transition gating** (unlike ADRs §G2) and **no DraftPlan→Spec FK** (link a draft
  plan's `source` to the spec, then link the synced tasks). **No `Task.implements_adr_id`** yet
  (decision→task traceability is roadmap gap #5).

---

## X. Delivery metrics (DORA + flow) **[new]**

The quantitative backbone of [`AI_NATIVE_EXECUTION.md`](./AI_NATIVE_EXECUTION.md) (roadmap gap #3):
DORA + flow metrics computed from canopy's own signal — the §J8 activity substrate (deploys /
incidents) and `TaskStatusHistory` (throughput / cycle time) + the board (WIP / aging). Logic is
pure in `app/services/flow_metrics.py` (unit-tested); the endpoint reuses `build_board`,
`weekly_throughput`, and `is_done_status` so the numbers match the board / forecast / burndown.

- **Team-level by design.** There is deliberately **no per-engineer breakdown** — per-individual
  delivery metrics are a Goodhart trap (velocity / diffs / tokens as a target). The response says
  so in its `notes`.
- **Honest, not falsely precise.** Flow reports `sufficient=false` with a reason under ~3 weeks of
  throughput (same bar as the forecast); change-fail rate is `null` with no deploys; metrics canopy
  can't compute from its data (PR-review latency, decision latency) are absent, not faked.

### X1. Read delivery metrics (project + initiative)
- **API:** `GET /api/v1/projects/{id}/delivery?weeks=` and `GET /api/v1/initiatives/{id}/delivery?weeks=`
  (default 12, max 52; the initiative variant aggregates across its sub-projects) · **MCP:**
  `get_delivery_metrics` (pass `project_id` *or* `initiative_id`). Open read.
- **DORA:** `deploys`, `deploy_frequency_per_week`, `failures` (incidents opened),
  `change_fail_rate` (≈ failures ÷ deploys), `recovered_incidents` + `mean`/`median_recovery_hours`
  (incident_open→close paired FIFO — an MTTR proxy).
- **Flow:** `completed_items`, `throughput_per_week`, `cycle_time_median_days` +
  `cycle_time_p85_days` (created→done over the window), `wip` (current not-done leaves), `aging_wip`
  (WIP over the team's cycle-time P85), `sufficient` + `reason`.

### X2. Not built (deliberate limits)
- **UI:** a **Delivery** tab on the project cockpit and a **Delivery metrics** panel on the
  initiative cockpit show the DORA + flow stat cards with a window selector and the honesty notes.
  Built.
- **No rework rate** (DORA 2025 — needs unplanned/rework tagging canopy doesn't have), **no flow
  efficiency** (needs an active-vs-wait status classification), and **no PR-review / decision
  latency** (need GitHub PR metrics §J6 / ADR status history). Surfaced as `notes`, not faked.

---

## Y. Outcomes — outcomes over output **[new]**

A project/initiative is a **bet**, not just a container of tasks (roadmap gap #2;
[`AI_NATIVE_EXECUTION.md`](./AI_NATIVE_EXECUTION.md) §1/§5). An `Outcome` (`app/models/outcome.py`)
captures the **hypothesis** ("we believe X will yield Y") + a **success metric**, tracked
**baseline → target → current** with a verdict — so the team optimizes for *the result*, not
output. Scope is polymorphic (project | initiative, like the risk register); an entity can carry
several (key results). The observed `current_value` is recorded by hand (canopy has no product-KPI
pipeline — an honest manual signal, like the weekly health note). `status`:
`pending → on_track / at_risk → validated | invalidated`.

### Y1. Define / track / verdict an outcome
- **API:** `GET /api/v1/outcomes?scope_level=&scope_id=&status=` (open read), `POST /api/v1/outcomes`
  (planner; validates the project/initiative exists), `GET /api/v1/outcomes/{id}`,
  `PATCH /api/v1/outcomes/{id}` (planner — record `current_value`, move `status`),
  `DELETE /api/v1/outcomes/{id}` (planner). `OutcomeRead` carries a computed **`progress_ratio`**
  ((current − baseline) / (target − baseline); pure in `app/services/outcomes.py`) ·
  **MCP:** `list_outcomes`, `add_outcome`, `update_outcome`.
- **UI:** an **Outcomes** panel on the project cockpit (below the delivery meta bar) and the
  initiative cockpit — list with a progress bar + status badge, an add form (statement · metric ·
  baseline/target/unit · date), an inline **record-current** input, and a status select.

### Y2. Retros evaluate the bet
- The retrospective seeder (§P1) now opens with an **"Outcomes — did the bet pay off?"** section
  listing each project outcome as `statement — current/target unit (status)`, so a retro evaluates
  the outcome, not just the schedule (`app/services/retro.py`).

### Y3. Not built (deliberate limits)
- **No automatic metric ingestion** — `current_value` is recorded by hand (no analytics/KPI
  connector). **No OKR hierarchy** (objectives → key results as a tree) — outcomes are a flat list
  per entity. **No initiative→project outcome rollup** yet.

---

## L. Claude plugin (agentic flows)

### L1. Install & configure the plugin
- Install the `canopy` plugin (cataloged by `.claude-plugin/marketplace.json`). Configure
  `api_base_url` (e.g. `http://localhost:8000`) and `api_token` (a JWT from `POST /auth/login`). The
  MCP server then exposes ~85 curated tools that call the REST API.
- **Transport.** Locally the plugin launches the MCP server over **stdio** (`plugin/.mcp.json`).
  For production / cloud Claude sessions, run the server as a long-lived service over **SSE**
  (`CANOPY_MCP_TRANSPORT=sse` + `CANOPY_MCP_HOST`/`CANOPY_MCP_PORT`/`CANOPY_MCP_PATH`) and point the
  session at the SSE URL. Backend connection (`CANOPY_API_BASE_URL`, `CANOPY_API_TOKEN`) and transport
  are all read from **environment variables**, so a headless cloud session needs no interactive
  plugin config. See README → *Production deployment*.

### L2. Plan a roadmap (skill + subagent)
- Ask Claude to plan/break down/sequence work. The **`planning-roadmaps`** skill (and **`gantt-planner`**
  subagent for heavier work) create projects/phases/tasks/dependencies and run `replan_schedule`,
  reporting the critical path and end date.

### L3. Sync from Jira (skill + subagent)
- Ask Claude to "sync Jira". The **`syncing-jira`** skill / **`jira-sync`** subagent find the Jira
  connection, run an incremental (or full) sync, then reconcile the plan (`replan_schedule`). The
  skill also covers **linking a specific Jira ticket** (initiative/epic/story) into a project or
  initiative via `link_jira_ticket` / `list_jira_links` / `resync_jira_link` / `unlink_jira_ticket`
  (§J9) — for pulling in just a chosen ticket tree instead of the whole project.

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

### L11. Draft a plan → create Jira tickets (skill) **[new]**
- The **`drafting-jira-tickets`** skill turns inputs (a codebase via `read_repo_file`, a design
  doc/PRD via `read_design_doc`, existing epics via `trigger_jira_sync`) into a reviewable **draft
  plan** (`create_draft_plan` + `add_draft_task` with estimates + story points), refines it with the
  architect (`get_draft_plan` / `update_draft_task` / `delete_draft_task`), then **creates the Jira
  tickets** from it (`push_draft_to_jira`) and syncs them back (`trigger_jira_sync`). Content only —
  status is never written (§C10).

### L12. Explore a what-if scenario (subagent) **[new]**
- The **`scenario-architect`** subagent answers what-if questions on an initiative without touching
  the live plan: it `create_scenario`s a branch, makes the edits (`set_scenario_allocation`,
  `set_scenario_availability`, `add_scenario_task` / `add_scenario_dependency`,
  `update_scenario_task`), then reads `compare_scenario` (+ `scenario_critical_path` /
  `scenario_capacity`) and reports the project-end and critical-path trade-off. It **does not
  `apply_scenario`** unless explicitly told to (apply writes canopy's plan + replans, never Jira).
  This is the agentic surface behind §T.

### L13. Enrich delivery metadata (subagent) **[new]**
- The **`delivery-enricher`** subagent annotates a project the way a PM / eng-leader would: it reads
  the plan (`list_tasks`, `get_gantt`, `get_risk`) then **proposes** 3-point estimates
  (`set_task_estimates`, advisory — never moves `duration`), logs qualitative risks in the register
  (`add_risk` / `update_risk` / `close_risk`, kept separate from the computed score), tags work
  (`add_tags`), flags impediments (`raise_blocker` with category/severity/needed-by), and sets a
  weekly health headline (`set_project_health`). Estimates/risks are proposals the architect
  confirms; Jira status is never written. This is the agentic surface behind §C1a / §Q3a. (The
  read-only **`risk-analyst`** §L6 still owns assessment of the computed score.)

### L14. Map epic documents into the doc graph (skill) **[new]**
- The **`mapping-epic-docs`** skill runs the one-time, AI-driven setup behind §V: it samples a
  Jira connection's epics (`sample_epic_doc_fields`), infers which field holds which kind of doc
  from field names + URL domains, **confirms the mapping with the admin**, saves it
  (`set_epic_doc_field_mapping`), harvests (`harvest_epic_docs`), and reports coverage
  (`get_doc_coverage`). canopy reads only — links are never written back to Jira and documents
  are never stored.

### L15. Spec-driven development (skill) **[new]**
- The **`spec-driven-development`** skill runs the spec loop (§W): draft a `Spec` from a PRD/design
  (doc graph §V) + ADRs (`create_spec`), write explicit checkable acceptance criteria
  (`add_spec_criterion`), approve it, plan + link the implementing work (`link_task_to_spec`, with
  `drafting-jira-tickets`), then **self-audit** each criterion against the implementation
  (`get_spec` → `update_spec_criterion` met/unmet) and mark the spec `verified` when all are met.

---

## M. Engineer workspace (`/me`)

Makes engineers first-class (v1 had no engineer-facing surface). A logged-in user is mapped to a
team member via `Engineer.user_id` (§A5).

### M1. My work
- **UI:** `/me` (also "My work" at the top of the sidebar) → the user's profile (role + linked
  engineer's GitHub / timezone / committed hours / skill tags), their **assigned open tasks**
  (most-critical first, then soonest due), and the **decisions they own** and **decisions to
  review** — each linking into the owning project's Gantt / Decisions tab.
- **API:** `GET /api/v1/me/workspace` · **MCP:** `my_workspace`. The response also includes
  **`blockers`** — open impediments on your tasks or raised by you (§D0), with flag/resolve in the UI.
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
- The **epic doc-field mapping / harvest** setup (§V2/§V3) stays conversational (AI-driven via the
  plugin) — no React wizard (deliberate); the Docs **tab** itself is built (read + add links).
- The **agent-token** mint (§A6) has no UI button yet — mint via `POST /auth/agent-token` (the
  Specs/Docs/Delivery **tabs** themselves are now built).
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
  resource **leveling**; drift **suppression-management UI** + non-Python analysis. *(Nightly
  **risk-snapshot** scheduling is built — arq worker, §Q2. Nightly **drift scans** still need the
  Drift Sentinel agent; a push-webhook that enqueues it is the remaining piece — §N.)*

---

*Maintained alongside the code. See `CLAUDE.md` → "Keeping USER_FLOWS.md in sync".*
