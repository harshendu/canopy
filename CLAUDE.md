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
  status back**. Mirrored status on canopy tasks is read-only. **Scoped exception:** from an
  architect-reviewed **draft plan** (see Draft plans below) canopy may *create* tickets and *update
  ticket content* (summary/description/story points + epic→story parent) via
  `JiraConnector.create_issue`/`update_issue` — but **status is still never written**, and canopy
  does not create local tasks on push (the normal Jira sync pulls the new issues back).
- **GitHub** owns code + some architecture docs. **Google Drive** holds design docs. canopy reads
  these; it does not own them. **Scoped write:** canopy can upload an *export snapshot* (a generated
  PDF/CSV, see Exports below) into a connected Drive via `GoogleDriveConnector.upload_file`.

## Layout
```
backend/   FastAPI + SQLModel + Alembic + arq. API in app/api/v1, models in app/models,
           business logic in app/services, integrations in app/connectors + app/webhooks.
frontend/  Vite + React + TS + Tailwind v4 + TanStack Query. Pages in src/pages
           (Portfolio dashboard, Initiatives + InitiativeView cockpit, Projects, ProjectView cockpit
           — an Overview entry + Schedule/Execution/Architecture/Governance/Integrations workspaces
           that group the detail views; two-level nav model in lib/projectNav.ts, Connectors). Views in
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
pip install -e ".[dev]"           # add ".[dev,mysql]" to include the MySQL/MariaDB driver
# Prod runs on Postgres or MySQL/MariaDB; SQLite is dev/local only. All three must work.
export DATABASE_URL="sqlite+aiosqlite:///./canopy.db"   # postgresql+asyncpg://… | mysql+aiomysql://…
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
Production (single machine): `docker compose -f compose.prod.yml up -d --build` — Caddy terminates
TLS and serves the built frontend + routes `/api`+`/webhooks`→backend and `/mcp`→MCP server
(streamable HTTP); optional `--profile ngrok` adds a public tunnel. Guide: `docs/PRODUCTION.md`.

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
- **Draft plans (plan → Jira):** `DraftPlan`/`DraftTask` (`app/models/draft.py`) are a staging area
  the architect reviews **before** any real work exists — kept out of the live Gantt/CPM/board.
  CRUD + push live in `app/api/v1/drafts.py` (planner-gated); the push orchestration is
  `app/services/draft_sync.py` (creates epics before stories, stamps each draft task with its Jira
  id/key so a re-push updates not duplicates, flips the plan to `synced`). It writes **content only**
  via `JiraConnector.create_issue`/`update_issue` (story points use the connection's
  `story_point_field`). MCP: `create_draft_plan`/`add_draft_task`/`push_draft_to_jira` (skill:
  `drafting-jira-tickets`). USER_FLOWS §C10.
- **Change proposals (agent → human review queue):** `Proposal`/`ProposalItem`
  (`app/models/proposal.py`) stage **inbound canopy writes** an agent inferred (from
  Slack/email/meetings/docs) for a human to review and apply in the UI — the inbound twin of
  draft plans. Items are whitelisted per entity×action (task/dependency/milestone/blocker/
  risk/outcome/decision/doc_reference; Jira-mirrored `status` never stageable), scope-contained
  to one project/initiative, may reference each other via `ref`/`*_ref` handles, and carry
  provenance (`source_kind/label/url`) + a stage-time `before` snapshot. Apply is
  **all-or-nothing** + auto-replan (`app/services/proposals.py`); staging/withdraw are open to
  agent tokens, review/apply/reject are planner + `HumanOnly` (`app/api/v1/proposals.py`, gate
  `ai.proposals`). UI: `/reviews` (+ nav badge, project-cockpit banner). MCP:
  `propose_changes`/`list_proposals`/`get_proposal`/`withdraw_proposal` +
  `get_workspace_context` (session orientation: persona, token scope, features, open
  proposals). Skills: `updating-canopy` (the write-ladder contract), `harvesting-signals`,
  `persona-playbooks`; subagent `signal-harvester`. USER_FLOWS §AA.
- **Flow board:** `GET /projects/{id}/board` groups leaf tasks into status lanes with WIP per lane,
  and flags **aging** tasks (in-status age > the team's cycle-time P85) — pure logic in
  `app/services/flow.py`; age/cycle dates derived from `TaskStatusHistory`. WIP limits are a
  client-side knob (not persisted). MCP: `get_board`.
- **Probabilistic forecast:** `GET /projects/{id}/forecast` and `GET /initiatives/{id}/forecast`
  run a Monte-Carlo simulation (`app/services/forecast.py`, pure) — burn down the remaining items by
  sampling historical weekly throughput (from `TaskStatusHistory`, incl. zero weeks) to report
  P50/P85 completion dates next to the deterministic CPM date. Needs ~3 weeks of throughput;
  reports `sufficient=false` with a reason otherwise. MCP: `get_forecast`.
- **Alerts/digest:** `GET /projects/{id}/alerts` turns project state into actionable alerts
  (deadline misses, overdue milestones, over-allocations, open blockers, unscheduled work) via
  `app/services/alerts.py` (pure). Slack/email *delivery* is a future hook over this output.
- **Blockers** (`app/api/v1/blockers.py`, `Blocker` model) are flagged impediments on a task — the
  leading "work has stalled" signal. Any contributor raises one (`POST /tasks/{id}/blockers`);
  open blockers surface in the `/me` workspace and the alerts digest. Folding blocked-time into the
  composite risk score is a follow-up.
- **Live refresh (SSE):** web-process mutations (replan/baseline) `publish()` to an in-process
  broker (`app/core/events.py`); `GET /api/v1/events/stream?token=` streams them; the frontend
  `useEventStream` invalidates query caches. Single-process only (worker syncs don't propagate) —
  Redis pub/sub is the multi-process upgrade.
- **Initiatives** (`app/api/v1/initiatives.py`) are the program layer above projects: a `Project`
  carries `initiative_id`, and `GET /initiatives/{id}/rollup` aggregates health across sub-projects
  (worst risk/drift, progress, open-decision backlog, on-track vs target). The per-project summary
  is `app/api/v1/projects.py:summarize_project`, shared with `GET /projects/portfolio` so a
  project's headline numbers are computed in exactly one place. **Cross-project dependencies** (a
  hand-off between teams) are allowed only within one initiative (enforced in
  `app/api/v1/dependencies.py`); `GET /initiatives/{id}/critical-path` runs the same `compute_cpm`
  over the union of the initiative's tasks + deps (`app/services/cross_project.py`, pure) to find
  the cross-project critical path + hand-offs. Per-project replan stays project-local (ignores
  cross-project edges).
- Aggregation for the visibility views is also backend-side and pure-where-possible:
  `GET /projects/portfolio` (per-project rollups), `GET /team/capacity?project_id=` (engineer×week
  allocation via `app/services/capacity.py:weekly_capacity`), and `GET /projects/{id}/burndown`
  (remaining/completed per week from `TaskStatusHistory` via `app/services/burndown.py`). Architecture
  topology is `ArchitectureComponent` + `ComponentLink` (system-map edges) + ADRs. Keep new
  aggregations pure and unit-tested.
- **Export snapshots (view outside canopy):** `app/api/v1/exports.py` assembles a point-in-time
  snapshot of a project / initiative / portfolio by **reusing** `summarize_project` + the rollups
  (so numbers match the live views), then renders it to **PDF** (`app/services/export_pdf.py` —
  reportlab, pure Python, no headless browser; includes a vector Gantt `Flowable`) or **CSV**
  (`app/services/export_csv.py`). Snapshot shapes are in `app/services/snapshot.py` (pure holders).
  Delivered as a download (`GET …/export?fmt=pdf|csv`) or saved to Drive
  (`POST …/export/to-drive` → `GoogleDriveConnector.upload_file`). UI: a reusable `ExportMenu`
  in the project / initiative / portfolio headers. USER_FLOWS §S.
- **Document graph (link, don't store):** `DocReference` (`app/models/doc.py`) holds typed *links*
  to docs that live elsewhere (Jira epic fields/remote-links, Drive, Figma, repo) — canopy never
  stores the bytes. Scope is polymorphic (project/initiative/task, like the risk register); dedup
  is in the service (no DB unique on the `url` TEXT column — not portable to MySQL). The AI-driven
  one-time setup samples a Jira connection's epics, an agent proposes a field→kind mapping (stored
  in the connection's `config["doc_field_mappings"]`), and `app/services/doc_graph.py` (pure
  URL/ADF extraction + harvest + coverage roll-up) attaches references to the entity each epic maps
  to. MCP: `sample_epic_doc_fields`/`set_epic_doc_field_mapping`/`harvest_epic_docs`/`get_doc_coverage`
  (skill: `mapping-epic-docs`). USER_FLOWS §V.
- **Specs (spec-driven development):** `Spec` + `SpecCriterion` (`app/models/spec.py`) capture
  *intent as the source of truth* — a problem statement + explicit, checkable **acceptance
  criteria** — before work begins. Tasks implement a spec via `Task.spec_id`; an agent self-audits
  each criterion (met|unmet|waived) against the implementation. `GET /specs/{id}` returns the
  audit bundle (criteria + linked tasks + readiness from pure `app/services/specs.py`). Criterion
  verdicts are contributor-writable (the engineer/agent records them); spec CRUD is planner-gated.
  MCP: `create_spec`/`add_spec_criterion`/`get_spec`/`update_spec_criterion`/`link_task_to_spec`
  (skill: `spec-driven-development`). Vision + roadmap in `docs/AI_NATIVE_EXECUTION.md`; USER_FLOWS §W.
- **Delivery metrics (DORA + flow):** `GET /projects|initiatives/{id}/delivery` computes DORA
  (deploy freq, change-fail rate, recovery time from the §J8 activity feed) + flow (throughput,
  cycle time, WIP, aging from `TaskStatusHistory` + the board) — pure in
  `app/services/flow_metrics.py`, reusing `build_board`/`weekly_throughput`/`is_done_status`.
  **Team-level only — never per-engineer** (Goodhart); reports `sufficient=false`/`null` instead of
  faking thin data. MCP: `get_delivery_metrics`. USER_FLOWS §X; roadmap gap #3 in AI_NATIVE_EXECUTION.md.
- **Outcomes (outcomes over output):** `Outcome` (`app/models/outcome.py`) makes a project/
  initiative a measurable **bet** — a hypothesis + success metric tracked baseline→target→current
  with a verdict (pending|on_track|at_risk|validated|invalidated). Polymorphic scope
  (project|initiative, like the risk register); `current_value` is a manual signal (no KPI
  pipeline). `progress_ratio` is computed (pure `app/services/outcomes.py`); the retro seeder opens
  with an outcomes section so retros evaluate the bet. MCP: `list_outcomes`/`add_outcome`/
  `update_outcome`. USER_FLOWS §Y; roadmap gap #2 in AI_NATIVE_EXECUTION.md.
- **Cross-functional persona + initiative digest:** `User.function` (engineering | product |
  design | architecture | management | leadership) is **orthogonal to `role`** — it makes
  PM/UX/staff/director/exec first-class and drives the **default landing** (`frontend/src/lib/persona.ts`),
  not CRUD (reads stay open; writes gated by `role`). `GET /initiatives/{id}/digest` synthesizes a
  **manage-by-exception** weekly roll-up (pure `app/services/digest.py`, reusing the rollup +
  forecast + blockers + outcomes; leads with the `attention` exception list) — MCP
  `get_initiative_digest`, skill `daily-standup`. Slack/email **delivery is a hook** over the digest
  (not built, like the alerts digest §I). USER_FLOWS §A7/§R5; roadmap gap #6 in AI_NATIVE_EXECUTION.md.
- **Bounded agency (scoped tokens):** access tokens carry a `scope` claim — `full` (human) or
  `agent`. An `agent` token (minted via `POST /auth/agent-token` by **any signed-in user** — it
  only carries the issuer's own permissions; `HumanOnly` blocks an agent token from minting another;
  gated by `ai.agent_tokens`) acts as its issuer but is blocked (403) from **one-way-door /
  external-write** actions: accepting a `one_way` ADR, `push-to-jira`, `apply_scenario`.
  Two-way-door actions stay open — the reversibility distinction is the human-in-the-loop policy.
  Enforced via `require_human`/`HumanOnly` in `app/api/deps.py` (scope in `app/core/security.py`).
  Minted tokens are **persisted as metadata** (`AgentTokenRecord`, `app/services/agent_tokens.py` —
  never the secret) so they can be listed (`GET /auth/agent-tokens`) and revoked
  (`DELETE /auth/agent-tokens/{id}`): the JWT carries a `jti` and `get_current_user` rejects it once
  revoked. UI: the **Agent Setup** tab (`/agent-setup`, all users — mint/list/revoke + plugin & MCP
  setup instructions). USER_FLOWS §A6/§A11; roadmap gap #4 in AI_NATIVE_EXECUTION.md (the
  webhook that auto-runs guardrails on agent PRs stays agent-driven — the server can't crawl code, §N).
- **Feature gates (admin on/off per surface):** two-level catalog (group → feature, e.g.
  `tracking` → `tracking.board`) in `app/services/features.py`; overrides are `FeatureFlag` rows
  (missing row = enabled; effective = own AND group). Enforced via `require_feature`/`FeatureGate`
  (`app/api/deps.py`) attached per-router in `app/api/v1/__init__.py` or per-endpoint
  (gantt/team/auth) → 403 `{code:"feature_disabled", feature}`; webhook intake ACKs-but-ignores
  when `integrations.webhooks` is off. Clients read `GET /features` (admin CRUD `/admin/features`);
  each toggle publishes an SSE `features` event so the React nav/tabs (`useFeatures`,
  `TAB_FEATURES` in `lib/projectNav`) update live. Core flows (auth/projects/tasks/gantt/team/me) are
  deliberately ungated. **When adding a feature, pick its gate (or call it core)** and gate new
  routers at include time. USER_FLOWS §A10.
- Connectors implement the ABC in `app/connectors/base.py` and self-register via `@register`. Sync is
  idempotent through the `ExternalRef` table (`app/services/mapping.py`). Connector tokens are
  encrypted at rest with Fernet (`app/core/crypto.py`). All outbound HTTP goes through
  `app/connectors/http.py:request_with_retry` (Retry-After + backoff/jitter on 429/5xx).
- Jira (`app/connectors/jira.py`): enhanced JQL search + Agile API (`sync_active_sprints` tags tasks
  with their sprint when `board_id` is configured) + changelog → `TaskStatusHistory`
  (`sync_status_history`). Jira status stays read-only. **Assignee → ownership:** sync maps the
  issue assignee to an `Engineer` (match `jira_account_id`, then exact name + back-fill, else
  auto-create — `resolve_assignee_engineer` in `app/services/ingest.py`) and sets
  `Task.assignee_engineer_id`; an issue unassigned in Jira leaves a locally-set owner alone.
- **Decision fitness functions:** an ADR can carry machine-checkable dependency rules
  (`ADRFitnessFunction`: forbid|require between two components). The drift scan evaluates accepted
  ADRs' rules against the observed edges (`FitnessRule` in `app/services/drift.py`); a violation is a
  `fitness_violation` drift event (heaviest weight) that auto-resolves when fixed. MCP:
  `add_adr_fitness`. (`Task.implements_adr_id` + a full traceability ledger are a planned follow-up.)
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
- **Three dialects must stay supported: PostgreSQL and MySQL/MariaDB (production) + SQLite
  (dev/local).** Every schema patch (migration) and query must run forward on all three — validate
  against real Postgres and MySQL, not just SQLite. Keep these portability rules intact:
  - **No forced table rebuilds on the server DBs.** Use `op.batch_alter_table(...)` with the default
    `recreate='auto'` (SQLite rebuilds; Postgres/MySQL get a native `ALTER`). `recreate='always'`
    breaks Postgres (drops a PK that FKs depend on) and MySQL (duplicate FK constraint names in the
    temp table).
  - **Enum changes are dialect-branched** (see `_alter_enum_column` in the migrations): recreate the
    native TYPE on Postgres, `MODIFY` the column on MySQL, CHECK-swap via batch on SQLite. Adding an
    enum *column* via `ALTER` needs the Postgres TYPE created first (`enum.create(bind, checkfirst=True)`).
  - **Naive UTC datetimes only** (`utcnow()` in `models/base.py` is tz-naive) — asyncpg rejects
    tz-aware values for `TIMESTAMP WITHOUT TIME ZONE`. MySQL keeps sub-second precision via the
    `DATETIME(6)` compiler hook in `models/_dialects.py`.
  - **Long free-text columns use `Text`, not bare `str`** — unbounded `str` becomes `VARCHAR(255)` on
    MySQL and truncates/errors. Short/identifier/indexed columns stay `str` (VARCHAR).
  - **Postgres/MySQL enforce foreign keys; SQLite does not by default.** Don't rely on SQLite's lax
    enforcement — handle cascade/ordering explicitly (e.g. clear self-references before bulk-deleting).
    Deleting a `Task`/`Project` goes through `app/services/cascade.py` (`delete_task_cascade` /
    `delete_project_cascade`), which clears FK-referencing rows in child→parent order — a bare
    `session.delete()` 500s on PG/MySQL and silently orphans on SQLite. `tests/test_cascade_delete.py`
    verifies it under `PRAGMA foreign_keys=ON` over the full demo graph, so a missed table fails CI.
- MCP tools (`plugin/mcp_server/tools/`) are curated — one per architect intent, not a 1:1 mirror of
  REST routes (~125 across projects/planning/proposals/connectors/team/architecture/scenarios/
  specs/docs/delivery/outcomes). Skills are runbooks (`updating-canopy` — the session operating
  guide every canopy session starts from, `harvesting-signals`, `persona-playbooks`,
  `planning-roadmaps`, `writing-adrs`, `syncing-jira`, `mcp-ingest`, `capacity-planning`,
  `decision-deadline-nudger`, `pr-to-adr-linker`, `drafting-jira-tickets`, `mapping-epic-docs`,
  `spec-driven-development`, `daily-standup`); subagents do isolated multi-step work
  (`jira-sync`, `gantt-planner`, `risk-analyst`, `drift-sentinel`, `scenario-architect`,
  `delivery-enricher`, `signal-harvester`). Add a tool when Claude needs a new verb; register it
  in `mcp_server/server.py`.
- **Background schedules (arq worker):** `app/workers/worker.py` runs cron jobs — the Jira
  reconciliation poll and a **nightly risk-snapshot sweep** (`capture_risk_snapshots` → `run_risk_snapshots`)
  so the risk timeline is a real trend. Drift carries a **scan log** (`DriftScan`): `GET .../drift`
  returns `last_scanned_at` + `scan_due` (true when code bindings exist but the scan is missing or
  >7 days old), surfacing staleness so the Drift Sentinel re-scans (the server can't crawl code).
- **Observability:** `GET /api/v1/health` (liveness, also reports `demo_mode`) and
  `/api/v1/health/ready` (DB check) for orchestration; structured logging via `app/core/logging.py`.
- **Demo / seeded-data mode (`DEMO_MODE`, local/dev only):** a repo-resident dataset in
  `app/services/seed/` (`catalog.py` = declarative data, `loader.py` = build/reset engine) that fills
  every UI surface; an admin loads/resets it from the UI (`/admin/demo`, `app/api/v1/admin_demo.py`,
  double-gated on admin **and** `DEMO_MODE` via `require_demo_mode`). `clear_all_data` wipes by
  iterating `SQLModel.metadata.sorted_tables` in reverse (nulling self-FKs first — portability rule),
  keeping the acting admin + superuser. Demo connectors (`config.demo=true`) are served by an offline
  HTTP mock (`app/connectors/demo.py`) injected at `Connector.open_client`, so Jira/GitHub/Drive
  sync + reads work without credentials. Extend the seed as features grow (it backs e2e). USER_FLOWS §Z.
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
