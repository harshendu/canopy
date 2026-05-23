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

### A3. Add a user *(admin, API-only)*
- **Actor:** admin · **API:** `POST /api/v1/auth/register` (admin token required).
- **UI gap:** no registration screen yet; admins add users via the API.

### A4. Get current user
- **API:** `GET /api/v1/auth/me`.

---

## B. Projects & portfolio

### B1. View the portfolio dashboard
- **UI:** `/portfolio` (landing page). Shows a completion bar chart and a card per project
  (avg % complete, completed/total tasks, critical-task count, end date). Clicking a card opens it.
- **API:** `GET /api/v1/projects/portfolio` · **MCP:** `list_projects`.

### B2. Create a project
- **UI:** `/projects` → enter KEY + name → "Add".
- **API:** `POST /api/v1/projects` (`key`, `name`, optional `start_date`/`target_date`).
- **Notes:** `key` is a unique slug (e.g. `PLATFORM`).

### B3. Open a project (the cockpit)
- **UI:** `/projects/:id` — a tabbed workspace: **Gantt · Dependencies · Capacity · Decisions ·
  Architecture · Roadmap · Burndown · Alerts**. The header has a **5-day week** toggle, **Set
  baseline**, and **Schedule (CPM)**. A tab can be deep-linked with `?tab=` (e.g.
  `/projects/:id?tab=decisions`).

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
- **UI:** `/team` — add engineers (name, optional title) and roles; remove engineers.
- **API:** `GET/POST /api/v1/team/engineers`, `PATCH/DELETE /api/v1/team/engineers/{id}`,
  `GET/POST /api/v1/team/roles` · **MCP:** `list_engineers`, `add_engineer`.

### F2. Allocate engineers (capacity)
- **UI:** project → Capacity tab → "Allocate" form (engineer, percent, date range) → "Add".
- **API:** `GET/POST /api/v1/team/allocations`, `DELETE /api/v1/team/allocations/{id}`
  (engineer, project, percent allocation, capacity hours, date range).

### F3. Capacity heatmap
- **UI:** project → Capacity tab → an engineer × ISO-week grid shaded by total allocation %;
  over-allocation (>100%) is red.
- **API:** `GET /api/v1/team/capacity?project_id=` · **MCP:** `get_capacity`.

---

## G. Architecture & decisions (Architecture + Decisions tabs)

Components and the system map live on the **Architecture** tab (G1). ADRs are now first-class
**decisions** on their own **Decisions** tab (G2–G6) plus a team-wide **`/decisions`** page — the
architect's unit of work is the decision, so it carries a lifecycle, an owner, stakeholders who
review it, alternatives, reversibility, and a discussion thread.

> **Identity note (current slice):** decision **owner**, **proposer**, **stakeholders**, and
> **comment authors** all reference **Engineer** records (the existing team model). Role-based
> *enforcement* (engineer vs architect vs owner) and engineer↔user unification are **not built**
> yet — any authenticated user can currently perform any of these actions. The roles matrix in the
> v2 spec (§"Roles × flows") is aspirational until the auth/roles slice lands.

### G1. Map components (Architecture tab)
- **UI:** Architecture tab → add components (name + kind: service/module/datastore/external/ui) and
  relationships (source → target, kind: depends_on/calls/publishes_to/reads_from). The system map
  (React Flow) shows components colored by kind with relationship edges.
- **API:** `GET/POST /api/v1/architecture/components`, `GET/POST/DELETE
  /api/v1/architecture/component-links` · **MCP:** `list_components`, `create_component`,
  `link_components`.
- **Not built:** component **code bindings** + **owner/criticality/tier** (v2 §G1).

### G2. Record / propose a decision (ADR) — Decisions tab
- **UI:** Decisions tab → "Propose / record a decision": title, context, decision, consequences,
  **alternatives** (one per line), **reversibility** (one-way / two-way door), **decision owner**,
  **proposed by**, **stakeholders** (must review), supersedes, affected components → "Save". The
  team-wide `/decisions` page has a lighter "Propose a decision" form (engineer flow).
- **API:** `POST /api/v1/architecture/adrs` (now also accepts `alternatives`, `reversibility`,
  `decision_owner_id`, `proposed_by_id`, `decide_by`, `rfc_url`, `stakeholder_ids`) · **MCP:**
  `create_adr` (architect records) / `propose_adr` (engineer proposes — sets `proposed_by_id`,
  status `proposed`).
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
- **API:** `POST /api/v1/architecture/adrs/import` · **MCP:** `import_adr`. The markdown is parsed
  (title + context/decision/consequences) into an ADR.
- **UI gap:** the import form was on the old Architecture tab and was dropped when ADRs moved to the
  Decisions tab — re-adding it there is a small follow-up.

---

## H. Progress: burndown
- **UI:** project → Burndown tab → a line chart of remaining vs completed work per week.
- **API:** `GET /api/v1/projects/{id}/burndown` · **MCP:** `get_burndown`.
- **Notes:** burndown is driven by task **status history**, which is populated from Jira (see J5).
  Without synced status transitions the chart is flat at the total.

---

## I. Alerts / digest
- **UI:** project → Alerts tab → a severity-colored list: deadline misses (error), overdue
  milestones / over-allocations (warning), unscheduled work (info).
- **API:** `GET /api/v1/projects/{id}/alerts` · **MCP:** `list_alerts`.
- **Notes:** delivery to Slack/email is **not built** — alerts are computed and shown/queried; a
  delivery integration is a future hook over this output.

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
  MCP server then exposes ~30 curated tools that call the REST API.

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
- **Not built:** the **decision-deadline nudger** skill (v2 §L8) and a `/canopy propose-adr` slash
  command — proposing is available as the `propose_adr` MCP tool today.

### L5. Plan capacity (skill)
- The **`capacity-planning`** skill reads `get_capacity` + `list_alerts`, cross-references the critical
  path, and uses `whatif_schedule` to test staffing/scope changes before committing them.

### L6. Assess risk (subagent)
- The **`risk-analyst`** subagent synthesizes `list_alerts`, `get_burndown`, the critical path, and
  `adr_impact` into a prioritized risk report.

---

## Known UI gaps (currently API/MCP-only)
These flows work via the API and the Claude plugin but have no React form yet — candidates for the UI
backlog:
- **What-if** scheduling (C5).
- ADR **doc-import** (G6) — was dropped from the trimmed Architecture tab; re-add to Decisions.
- Project rename/archive/date edits and **holiday** management (B4, C7).
- **User registration** (A3).
- *(closed in this revision: decision-impact / blast radius (G5) is now in the UI.)*

## Not built (documented as future)
- Slack/email **delivery** of alerts (I) and **decision SLA notifications** (G3).
- Multi-process **real-time** (K) — needs Redis pub/sub.
- **Resource leveling** (auto-resolving over-allocation).
- **Role-based access** for decisions (engineer vs architect vs owner) and engineer↔user
  unification (v2 §A3/§"Roles × flows") — decisions currently model actors as Engineers without
  enforcement.
- Hard-enforced decision **rules/approval gates** (G3) — `can_accept` is advisory today.
- The broader v2 surfaces this slice does **not** touch: architecture **drift detection** (§N),
  the **risk dashboard** (§Q), the **engineer workspace** (§M), **retros/postmortems** (§P), and
  new connectors (PagerDuty §J7, CI/observability §J8).

---

*Maintained alongside the code. See `CLAUDE.md` → "Keeping USER_FLOWS.md in sync".*
