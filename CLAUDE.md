# CLAUDE.md

Guidance for Claude Code working in this repo.

## Keeping USER_FLOWS.md in sync (required)
`docs/USER_FLOWS.md` documents every user-facing flow and **must be updated in the same change** that
adds, changes, or removes a flow. When you add/modify an endpoint, page, tab, MCP tool, skill, or
subagent that a user (architect or Claude) interacts with: add or revise the matching flow there,
note the UI path + API endpoint + MCP tool, and keep its "Known UI gaps" / "Not built" sections
honest. Treat a flow change without a USER_FLOWS.md update as incomplete.

## What canopy is
A tool for a **software architect** to manage architecture + delivery of a codebase: projects,
milestones, WBS/Gantt scheduling (critical path), teams, ADRs — with **sync from Jira** and reads
from **GitHub** and **Google Drive**. One FastAPI backend with two front doors: a React dashboard
and a Claude Code plugin (FastMCP server + skills + subagents).

## Source-of-truth boundaries (do not violate)
- **Jira** owns epics/stories and ticket **status**. canopy syncs *from* Jira and **never writes
  status back**. Mirrored status on canopy tasks is read-only.
- **GitHub** owns code + some architecture docs. **Google Drive** holds design docs. canopy reads
  these; it does not own them.

## Layout
```
backend/   FastAPI + SQLModel + Alembic + arq. API in app/api/v1, models in app/models,
           business logic in app/services, integrations in app/connectors + app/webhooks.
frontend/  Vite + React + TS + Tailwind v4 + TanStack Query. Pages in src/pages
           (Portfolio dashboard, Initiatives + InitiativeView cockpit, Projects, ProjectView with
           Gantt/Dependencies/Capacity/Architecture/Roadmap/Burndown tabs, Connectors). Views in
           src/components:
           GanttChart (custom SVG, with zoom + baseline/variance overlay), DependencyGraph +
           ArchitectureView (React Flow), CapacityHeatmap + RoadmapView (custom),
           BurndownChart + Portfolio (Recharts). Heavy libs (React Flow / Recharts) are
           React.lazy code-split. API client + types in src/api.
plugin/    Claude Code plugin. FastMCP server in mcp_server/ (thin client of the REST API),
           skills/, agents/. Manifests: plugin/.claude-plugin/plugin.json, plugin/.mcp.json,
           and .claude-plugin/marketplace.json at repo root.
```

## Commands
Backend (run from `backend/`, venv at `backend/.venv`):
```bash
pip install -e ".[dev]"
export DATABASE_URL="sqlite+aiosqlite:///./canopy.db"   # or a Postgres URL
alembic upgrade head
uvicorn app.main:app --reload
ruff check .         # lint (strict ruleset incl. ANN — every def must be typed)
ruff check --fix .   # autofix
mypy app             # static type check (must pass clean)
pytest -q
```
Frontend (run from `frontend/`):
```bash
npm install
npm run dev          # proxies /api -> :8000
npm run lint         # eslint (typescript-eslint + react-hooks), --max-warnings 0
npm run test         # vitest unit tests
npm run build        # tsc typecheck + vite build
```
Plugin (run from `plugin/`, venv at `plugin/.venv`):
```bash
pip install -r mcp_server/requirements.txt
```
Whole stack: `docker compose up --build` (postgres, redis, backend, worker, frontend).

## Conventions / where logic lives
- A `Task` is the Gantt unit; a `summary` task is a phase/workstream (WBS tree via `parent_id`).
  Dependencies are typed FS/SS/FF/SF with `lag`.
- **CPM is computed backend-side** in `app/services/scheduling.py` (pure forward/backward pass over
  a `networkx` DAG). The CPM works in working-day offsets; a `WorkingCalendar` maps them to dates
  (skips weekends when `Project.skip_weekends` + project `Holiday`s). `app/services/planner.py`
  `reschedule_project` loads the graph, runs CPM with the calendar, optionally applies duration
  overrides (what-if) and/or persists, and reports `deadline` violations. Endpoints:
  `POST /projects/{id}/replan` (persist), `POST /projects/{id}/whatif` (no persist, duration overrides),
  `POST /projects/{id}/baseline` (snapshot start/end → `baseline_*`; logs a reasoned `Baseline`
  event — `GET .../baselines`; the Gantt overlays current-vs-baseline as **schedule variance**, and
  "drift" is reserved for architecture drift §N). A Jira sync that creates tasks auto-replans the
  project. Keep the scheduler/planner pure-ish and unit-tested.
- **Alerts/digest:** `GET /projects/{id}/alerts` turns project state into actionable alerts
  (deadline misses, overdue milestones, over-allocations, unscheduled work) via
  `app/services/alerts.py` (pure). Slack/email *delivery* is a future hook over this output.
- **Live refresh (SSE):** web-process mutations (replan/baseline) `publish()` to an in-process
  broker (`app/core/events.py`); `GET /api/v1/events/stream?token=` streams them; the frontend
  `useEventStream` invalidates query caches. Single-process only (worker syncs don't propagate) —
  Redis pub/sub is the multi-process upgrade.
- **Initiatives** (`app/api/v1/initiatives.py`) are the program layer above projects: a `Project`
  carries `initiative_id`, and `GET /initiatives/{id}/rollup` aggregates health across sub-projects
  (worst risk/drift, progress, open-decision backlog, on-track vs target). The per-project summary
  is `app/api/v1/projects.py:summarize_project`, shared with `GET /projects/portfolio` so a
  project's headline numbers are computed in exactly one place. (Cross-project dependencies + a
  cross-project critical path are a planned follow-up, not built.)
- Aggregation for the visibility views is also backend-side and pure-where-possible:
  `GET /projects/portfolio` (per-project rollups), `GET /team/capacity?project_id=` (engineer×week
  allocation via `app/services/capacity.py:weekly_capacity`), and `GET /projects/{id}/burndown`
  (remaining/completed per week from `TaskStatusHistory` via `app/services/burndown.py`). Architecture
  topology is `ArchitectureComponent` + `ComponentLink` (system-map edges) + ADRs. Keep new
  aggregations pure and unit-tested.
- Connectors implement the ABC in `app/connectors/base.py` and self-register via `@register`. Sync is
  idempotent through the `ExternalRef` table (`app/services/mapping.py`). Connector tokens are
  encrypted at rest with Fernet (`app/core/crypto.py`). All outbound HTTP goes through
  `app/connectors/http.py:request_with_retry` (Retry-After + backoff/jitter on 429/5xx).
- Jira (`app/connectors/jira.py`): enhanced JQL search + Agile API (`sync_active_sprints` tags tasks
  with their sprint when `board_id` is configured) + changelog → `TaskStatusHistory`
  (`sync_status_history`). Jira status stays read-only.
- **Architecture depth:** `POST /architecture/adrs/import` reads a markdown doc from a GitHub/Drive
  connection and parses it into an ADR (`app/services/markdown_adr.py`, pure). `GET /architecture/adrs/{id}/impact`
  returns directly-affected components plus everything that transitively depends on them
  (`app/services/impact.py` reverse-walks `ComponentLink` edges, pure).
- Webhooks (`app/webhooks/`) verify HMAC **before** parsing, match the repo/project to active
  connections, then enqueue `process_webhook` (arq) — never process inline. `GitHubConnector.handle_webhook`
  upserts the `PullRequest` cache; `JiraConnector.handle_webhook` upserts the task.
- **OAuth 2.0 (3LO)** lives in `app/connectors/oauth.py` (provider configs, authorize-URL, code
  exchange, refresh). Flow: create a `Connection` (no token) → `GET /connectors/oauth/{id}/authorize`
  returns the provider URL (CSRF `state` is a signed short-lived JWT carrying the connection id) →
  provider redirects to `GET /connectors/oauth/callback` (unauthenticated; trust comes from `state`)
  → tokens are exchanged, encrypted, and stored; for Jira the cloudId is resolved and `base_url` set
  to `https://api.atlassian.com/ex/jira/{cloudId}` with `auth_type=oauth`. `Connector.ensure_fresh_token`
  (called by `open_client`) refreshes expired access tokens and persists rotated refresh tokens.
  Set client creds via `*_OAUTH_CLIENT_ID/SECRET` env vars (see `.env.example`).
- **Migrations are real autogenerated Alembic revisions** (no more `create_all` baseline). To change
  schema: edit models, then `alembic revision --autogenerate -m "..."`, review the file, commit.
  Generated files under `alembic/versions/` are excluded from ruff.
- MCP tools (`plugin/mcp_server/tools/`) are curated — one per architect intent, not a 1:1 mirror of
  REST routes (~50 across projects/planning/connectors/team/architecture). Skills are runbooks
  (`planning-roadmaps`, `writing-adrs`, `syncing-jira`, `capacity-planning`, `decision-deadline-nudger`,
  `pr-to-adr-linker`); subagents do isolated multi-step work (`jira-sync`, `gantt-planner`,
  `risk-analyst`, `drift-sentinel`). Add a tool when Claude needs a new verb; register it in
  `mcp_server/server.py`.
- **Observability:** `GET /api/v1/health` (liveness) and `/api/v1/health/ready` (DB check) for
  orchestration; structured logging via `app/core/logging.py`.
- **Frontend tests:** Vitest (`npm run test`) covers pure helpers (e.g. `src/lib/horizon.ts`); CI
  runs it between lint and build. Extract pure logic out of components to keep it testable.

## Code standards (enforced by CI — keep them green)
- **Python is strictly typed.** Every function/method is annotated (ruff `ANN`), and `mypy app` must
  pass with no errors (configured in `pyproject.toml`: `disallow_untyped_defs`, `no_implicit_optional`,
  `warn_return_any`, pydantic plugin). New code must keep mypy clean.
- **Use Pydantic models at API boundaries.** Request/response shapes live in `app/schemas/` as Pydantic
  models (DB models are SQLModel). Don't return bare dicts from routes where a schema fits.
- **SQLModel + mypy patterns:** wrap model columns in `col(...)` for `order_by`/`where` so they
  type-check; a model `id` is `int | None`, so guard/assert it's set (it is after `flush`) before
  using it as a non-optional value. Coerce `Any` from `dict`/`resp.json()` with `str(...)`/`list(...)`.
- **Frontend is TypeScript + ESLint** (`typescript-eslint` + `react-hooks`), lint runs with
  `--max-warnings 0`. `tsconfig` is strict (`noUnusedLocals`/`noUnusedParameters`). No `any`.
- Ruff/mypy/eslint configs are the source of truth; tune them in `pyproject.toml` / `eslint.config.js`
  rather than scattering inline ignores.

## Gotchas (decisions already made — don't "fix" these back)
- Auth uses **`bcrypt` directly**, not `passlib` (passlib is unmaintained and breaks with bcrypt 4.x).
- GitHub/Drive connectors use **`httpx`**, not `githubkit`/google SDKs (fewer deps, stable REST).
- The Gantt is a **custom SVG component**, not a third-party Gantt lib (so it builds/typechecks in CI
  without a browser). SVAR/frappe are a possible upgrade.
- The `User` table is named `app_user` (`user` is reserved in Postgres).

## Setup, CI, and git hooks
- `scripts/setup.sh` — idempotent environment bootstrap: creates `backend/.venv`, installs Python +
  Node deps, and only reinstalls when something is missing or a lockfile changed. Works on a vanilla
  VM with just the repo checked out (requires `python3` and `node`/`npm` on PATH).
- `scripts/ci.sh` — basic CI: runs `setup.sh`, then backend `ruff` + `mypy` + `pytest` and frontend
  `eslint` + `test` (vitest) + `build`.
- **pre-commit** hook (`.githooks/pre-commit`): backend `ruff`+`mypy`+`pytest` (if `backend/` changed)
  and frontend `eslint`+`test`+`build` (if `frontend/` changed). `RUN_ALL=1` forces both.
- **pre-push** hook (`.githooks/pre-push`): runs `scripts/ci.sh` (full CI, self-bootstrapping) before
  every push; a failure aborts the push.
- Install both hooks once per clone: `scripts/install-hooks.sh` (sets `core.hooksPath=.githooks`).
- Don't bypass with `--no-verify` — fix the failure.
