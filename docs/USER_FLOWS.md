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
- **UI:** `/projects/:id` — a tabbed workspace: **Gantt · Dependencies · Capacity · Architecture ·
  Roadmap · Burndown · Alerts**. The header has a **5-day week** toggle, **Set baseline**, and
  **Schedule (CPM)**.

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

### E1. Define a milestone *(API/MCP-only)*
- **API:** `POST /api/v1/milestones` · **MCP:** `create_milestone` (name, target date).
- **UI gap:** there is no milestone-creation form yet; milestones are created via API/MCP and
  displayed on the Roadmap.

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

### F2. Allocate engineers (capacity) *(API/MCP-only)*
- **API:** `GET/POST /api/v1/team/allocations`, `DELETE /api/v1/team/allocations/{id}`
  (engineer, project, percent allocation, capacity hours, date range).
- **UI gap:** no allocation form yet; allocations are created via API/MCP and then visualized.

### F3. Capacity heatmap
- **UI:** project → Capacity tab → an engineer × ISO-week grid shaded by total allocation %;
  over-allocation (>100%) is red.
- **API:** `GET /api/v1/team/capacity?project_id=` · **MCP:** `get_capacity`.

---

## G. Architecture & decisions (Architecture tab)

### G1. Map components
- **UI:** Architecture tab → add components (name + kind: service/module/datastore/external/ui) and
  relationships (source → target, kind: depends_on/calls/publishes_to/reads_from). The system map
  (React Flow) shows components colored by kind with relationship edges.
- **API:** `GET/POST /api/v1/architecture/components`, `GET/POST/DELETE
  /api/v1/architecture/component-links` · **MCP:** `list_components`, `create_component`,
  `link_components`.

### G2. Record an ADR
- **UI:** Architecture tab → "Record an ADR": title, context, decision, status (proposed/accepted/
  superseded/deprecated), supersedes (another ADR), affected components → "Add ADR". The ADR list
  shows each decision with an editable status, supersession reference, and component chips.
- **API:** `POST /api/v1/architecture/adrs`, `PATCH /api/v1/architecture/adrs/{id}` · **MCP:**
  `create_adr`.

### G3. Import an ADR from a doc
- **UI:** Architecture tab → "Or import from a doc": pick a GitHub/Drive connection + path/file id →
  "Import". The markdown is parsed (title + context/decision/consequences sections) into an ADR.
- **API:** `POST /api/v1/architecture/adrs/import` · **MCP:** `import_adr`.

### G4. Decision-impact analysis
- **Actor:** architect via Claude (or API) · **MCP:** `adr_impact` · **API:**
  `GET /api/v1/architecture/adrs/{id}/impact`.
- **Result:** the components an ADR directly affects, plus everything that transitively depends on
  them (the blast radius).
- **UI gap:** surfaced via Claude / API; not yet drawn on the map.

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
  MCP server then exposes ~26 curated tools that call the REST API.

### L2. Plan a roadmap (skill + subagent)
- Ask Claude to plan/break down/sequence work. The **`planning-roadmaps`** skill (and **`gantt-planner`**
  subagent for heavier work) create projects/phases/tasks/dependencies and run `replan_schedule`,
  reporting the critical path and end date.

### L3. Sync from Jira (skill + subagent)
- Ask Claude to "sync Jira". The **`syncing-jira`** skill / **`jira-sync`** subagent find the Jira
  connection, run an incremental (or full) sync, then reconcile the plan (`replan_schedule`).

### L4. Write / import ADRs (skill)
- The **`writing-adrs`** skill drafts an ADR with a consistent template and records it (`create_adr`),
  or imports one from a repo/Drive doc (`import_adr`).

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
- Creating **milestones** (E1), **allocations** (F2).
- **What-if** scheduling (C5) and **decision-impact** visualization (G4).
- Project rename/archive/date edits and **holiday** management (B4, C7).
- **User registration** (A3).

## Not built (documented as future)
- Slack/email **delivery** of alerts (I).
- Multi-process **real-time** (K) — needs Redis pub/sub.
- **Resource leveling** (auto-resolving over-allocation).

---

*Maintained alongside the code. See `CLAUDE.md` → "Keeping USER_FLOWS.md in sync".*
