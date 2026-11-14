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
- **The status owner owns status.** Every task has one `status_owner`: `canopy` (a native
  project's tasks, and canopy-only work in a mirrored one) or the tracker it is mirrored from.
  canopy moves only canopy-owned tasks and **never writes status to a tracker**; a mirrored
  task's status is read-only in canopy. **`workflow.record_transition` is the only writer of
  `Task.status`** (moves, proposal apply, draft finalise and every inbound sync end there, so
  history, categories and progress stay consistent — `tests/test_status_single_writer.py`).
- **Jira** owns the epics/stories it mirrors and their **status**. canopy syncs *from* Jira and
  **never writes status back**. Mirrored status on canopy tasks is read-only. **Scoped exception:** from an
  architect-reviewed **draft plan** (see Draft plans below) canopy may *create* tickets and *update
  ticket content* (summary/description/story points + epic→story parent) via
  `JiraConnector.create_item`/`update_item` — but **status is still never written**, and canopy
  does not create local tasks on push (the normal Jira sync pulls the new issues back). The same
  holds for any tracker through `WorkTracker.create_item`/`update_item` (draft finalise, and
  "publish" when a project switches to a tracker — §C12).
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
python3 ../scripts/init.py --defaults --no-start  # once: writes ../.env with a strong SECRET_KEY
                                                  # (startup refuses a missing/placeholder key)
alembic upgrade head
uvicorn app.main:app --reload
ruff check .         # lint (strict ruleset incl. ANN — every def must be typed)
ruff check --fix .   # autofix
mypy app             # static type check (must pass clean)
pytest -q
```
Frontend (run from `frontend/`; Node 22+ — Vite 7 needs >=20.19):
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
  overrides (what-if) and/or persists, and reports `deadline` violations. The CPM pin is a task's
  **`constraint_start`** (a user "start no earlier than" input), kept **separate** from the computed
  `start`/`end` output — never pin from the computed start, or the schedule ratchets forward-only
  and what-if goes inert. Endpoints:
  `POST /projects/{id}/replan` (persist), `POST /projects/{id}/whatif` (no persist, duration overrides),
  `POST /projects/{id}/baseline` (snapshot start/end → `baseline_*`; logs a reasoned `Baseline`
  event — `GET .../baselines`; the Gantt overlays current-vs-baseline as **schedule variance**, and
  "drift" is reserved for architecture drift §N). A Jira sync that creates tasks auto-replans the
  project. Keep the scheduler/planner pure-ish and unit-tested.
- **Draft plans (plan → tickets or tasks):** `DraftPlan`/`DraftTask` (`app/models/draft.py`) are a
  staging area the architect reviews **before** any real work exists — kept out of the live
  Gantt/CPM/board. CRUD + finalise live in `app/api/v1/drafts.py` (planner-gated, finalise
  human-only); the orchestration is `app/services/draft_sync.py`. `POST /draft-plans/{id}/finalize`
  follows the project's tracking mode: a **native** project gets canopy tasks (keys, first statuses,
  parents, replan — `materialize_native`); a **mirrored** one pushes epics before stories to its
  bound tracker through `WorkTracker.create_item`/`update_item`, stamping each draft task with
  `external_provider/_id/_key` so a re-push updates not duplicates — it writes **content only**
  (story points via the binding's estimate field, item types from its mapping); an integration
  policy that routes writes via MCP answers 403 and Claude records what it created
  (`record-push`). MCP: `create_draft_plan`/`add_draft_task`/`finalize_draft_plan`/
  `record_draft_push` (skill: `drafting-tickets`). USER_FLOWS §C10.
- **Change proposals (agent → human review queue):** `Proposal`/`ProposalItem`
  (`app/models/proposal.py`) stage **inbound canopy writes** an agent inferred (from
  Slack/email/meetings/docs) for a human to review and apply in the UI — the inbound twin of
  draft plans. Items are whitelisted per entity×action (task/dependency/milestone/blocker/
  risk/outcome/decision/doc_reference; task `status` stageable only on canopy-owned tasks,
  never on a mirrored one), scope-contained
  to one project/initiative, may reference each other via `ref`/`*_ref` handles, and carry
  provenance (`source_kind/label/url`) + a stage-time `before` snapshot. Apply is
  **all-or-nothing** + auto-replan (`app/services/proposals.py`); staging/withdraw/**revise**
  are open to agent tokens, review/apply/reject are planner + `HumanOnly`
  (`app/api/v1/proposals.py`, gate `ai.proposals`). The review is **plan-first**:
  `GET /proposals/{id}/preview` returns the plan as a whole, current vs proposed —
  `app/services/proposal_preview.py` replays the included items (reviewer overrides applied)
  onto an in-memory copy of the plan and runs the **same scheduler apply uses**
  (`compute_schedule` + the shared `rollup_summaries`/`infer_project_start` in `planner.py`),
  classifying each task `added | edited | shifted`. It is pure and must stay faithful to
  apply — `tests/test_proposal_preview.py` pins preview == post-apply Gantt, so a new
  schedule-affecting field/entity in `_apply_item` needs its twin in `stage_items`. The
  **co-review loop**: `POST /proposals/{id}/revise` amends an open proposal in place
  (merge/add/remove items, bump `revision` + `revision_note`, SSE) under a
  *don't-make-it-worse* validation rule, so a human reviews in the UI while asking Claude
  for changes. To move staged work in time use `duration`/dependencies/`constraint_start`
  (a staged `start` is computed output). UI: `/reviews` queue → `/reviews/:id` workspace
  (`ReviewWorkspace.tsx` + `components/review/`: impact strip, Current ⇄ Proposed Gantt,
  grouped plain-language change cards with typed inline edit; wording/field catalog in the
  pure `lib/proposals.ts`) (+ nav badge, project-cockpit banner). MCP:
  `propose_changes`/`preview_proposal`/`revise_proposal`/`list_proposals`/`get_proposal`/
  `withdraw_proposal` + `get_workspace_context` (session orientation: persona, token scope,
  features, open proposals). Skills: `updating-canopy` (the write-ladder contract + the
  reviewing-together loop), `harvesting-signals`, `persona-playbooks`; subagent
  `signal-harvester`. USER_FLOWS §AA.
- **Kanban board + native tracking:** a project is `tracking_mode` native|mirrored. Board columns
  are a **workflow** (`app/models/workflow.py`: ordered statuses, each with a **category**
  todo|in_progress|done|cancelled + optional WIP limit, enforcement off|warn|block), resolved
  project override → team → workspace template → built-in default (`app/services/workflow.py`,
  nothing written on read); a **mirrored** project whose binding holds the tracker's status map
  shows the tracker's statuses instead (`scope="tracker"`, edits 409
  `workflow_externally_owned`). **Metrics read categories, never status names** (stamped on the task
  and on each `TaskStatusHistory` row). `GET /projects/{id}/board` shows every column (empty ones
  too) with ranked cards, WIP vs limit and **aging** (in-status age > cycle-time P85, cycle =
  first start → last done); pure logic in `app/services/flow.py`, assembly in
  `app/services/board.py`. A column's WIP limit counts its **WIP scope** — every project sharing
  those columns (`wip_scope_project_ids`) — on the board (`scope_wip`) and in the move check alike.
  `POST /tasks/{id}/move` changes a canopy-owned card's status/rank (a planner who may edit the
  project; anyone else contributing moves own cards or pulls an unassigned one *into another
  column*; 409 for a mirrored card), gated by `tracking.native`; workflows: `GET/PUT /teams|projects/{id}/workflow`, `/workflows/template`.
  Native tasks get keys `<prefix>-<n>`. MCP: `get_board`/`move_task`/`get_workflow`/
  `set_workflow`. USER_FLOWS §C9.
- **Delivery methods + sprints (per team):** `Team.delivery_method` kanban|sprint|both (+ sprint
  length, estimate unit points|days|count) applies to every project the team runs (a team-less
  project is Kanban-only; gate `tracking.sprints`, off = everyone Kanban). `Sprint`
  (`app/models/sprint.py`) belongs to a team (optional pod), is canopy-owned or mirrored from a
  tracker (read-only), state planned→active→completed; `Task.sprint_id` is membership, written
  ONLY by `sprint_service.record_membership` (appends `TaskSprintHistory` — commitment, scope
  change, carry-over derive from it). Pure maths (burndown, totals, velocity, per-sprint
  Monte-Carlo, capacity) in `app/services/sprints.py`; DB side in `app/services/sprint_service.py`;
  API `app/api/v1/sprints.py` (`/teams/{id}/delivery|board|sprints|velocity`, `/sprints/{id}/…`).
  Sprints never pin the CPM schedule (`sprint_overrun` alert instead). Team-level only, never
  per engineer. MCP: `get_team_delivery`/`set_team_delivery`/`list_sprints`/`get_sprint`/
  `plan_sprint`/`start_sprint`/`complete_sprint`/`get_velocity`; skill `planning-sprints`.
  USER_FLOWS §C11.
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
  cycle time started→done, lead time, WIP = in-progress category, aging from
  `TaskStatusHistory` + the board) — pure in `app/services/flow_metrics.py`, reusing
  `build_board`/`weekly_throughput` and the stamped status categories.
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
  external-write** actions: accepting a `one_way` ADR, finalising a draft plan, `apply_scenario`.
  Two-way-door actions stay open — the reversibility distinction is the human-in-the-loop policy.
  Enforced via `require_human`/`HumanOnly` in `app/api/deps.py` (scope in `app/core/security.py`).
  Minted tokens are **persisted as metadata** (`AgentTokenRecord`, `app/services/agent_tokens.py` —
  never the secret) so they can be listed (`GET /auth/agent-tokens`) and revoked
  (`DELETE /auth/agent-tokens/{id}`): the JWT carries a `jti` and `get_current_user` rejects it once
  revoked. UI: the **Agent Setup** tab (`/agent-setup`, all users — mint/list/revoke + plugin & MCP
  setup instructions). USER_FLOWS §A6/§A11; roadmap gap #4 in AI_NATIVE_EXECUTION.md (the
  webhook that auto-runs guardrails on agent PRs stays agent-driven — the server can't crawl code, §N).
- **Teams, pods, owners + leadership notes:** a **team** owns a product/platform and holds
  **pods**; directors/managers sit in `TeamMember` seats (`app/models/org.py`). An initiative
  belongs to a team and has **one or more owners** (`InitiativeLead`: technical / product /
  design / manager; one person may own several); every **project has exactly one owner**
  (`Project.owner_engineer_id`) and a pod; an initiative spans its projects' pods (derived).
  Ownership scopes *planning writes* for planner roles — initiative owners plan the initiative,
  team directors plan their team's initiatives, a project owner plans their project; everyone
  else reads; admins exempt; no owners + no team = plain role rules — enforced centrally in
  `app/services/access.py` (`ensure_initiative_editable` / `ensure_project_editable`, called from
  the initiative/project/task/milestone/dependency/ADR/draft/scenario writes; 403
  `{code:"not_initiative_lead"}`). `GET /teams`, `/initiatives/access`, `/projects/{id}/access`,
  rollup `can_edit`/`leads`/`team_name`/`pods`. **Leadership notes** (`LeadershipNote`,
  polymorphic initiative|project scope + optional decision/risk/outcome/milestone target, kind
  watch|priority|feedback) are leadership's one write (`function=leadership`, team directors, or
  admin); owners acknowledge/resolve with a response; `GET /leadership/review` is the
  business-review roll-up grouped by team (gate `portfolio.leadership`, UI `/review`, the
  leadership persona's landing). USER_FLOWS §R6 / §BR.
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
  idempotent through the `ExternalRef` table (`app/services/mapping.py`; a ref names its
  `connection_id` — legacy NULL rows still match any connection — and a `detached_at`). Connector
  tokens are encrypted at rest with Fernet (`app/core/crypto.py`). All outbound HTTP goes through
  `app/connectors/http.py:request_with_retry` (Retry-After + backoff/jitter on 429/5xx).
- **Work trackers are pluggable** (USER_FLOWS §J0): a tracker is a `WorkTracker`
  (`app/connectors/tracker.py`, `@register_tracker`) that declares `capabilities` +
  `config_schema`/`scope_schema` and only **fetches/normalizes** into
  `app/services/tracker_types.py` and writes item **content** — it has **no status write**. The
  engine `app/services/tracker_sync.py` is its only caller (upsert, parents, epic → project,
  watermarks, status map, changelog backfill, sprints, replan) and never imports a concrete
  tracker (`tests/test_tracker_layer.py` pins this + a per-tracker contract). What a connection
  feeds is a **`TrackerBinding`** (project | subtree = a tracker link | query scope, with its
  watermark, mapping, status map, backfill cursor) — a tracker connection created with a
  `project_id` (beside its config; `config.project_id` is refused) binds that project.
  `EngineerIdentity` maps tracker accounts onto engineers. Provider columns are VARCHAR(32), so a new tracker is an enum member + one module
  (CONTRIBUTING "Adding a work tracker"). Shipped: **Jira**, **Linear** (`connectors/linear.py`,
  GraphQL; cycles → sprints; `Linear-Signature` webhooks) and a **generic** ingest/webhook-only
  tracker (`connectors/generic.py`, `direct_read=False`); Linear/generic are opt-in via
  `TRACKERS_ENABLED`, and the admin integration policy lists only trackers in use.
  Neutral surfaces: `/tracker-links`, ingest/file ingest for any
  tracker connection, `/webhooks/{provider}`, `GET /meta/trackers`, `TaskExternalLinksRead.tracker`,
  PR → task matching by any key (`ingest.issue_keys`). Config: `TRACKERS_ENABLED`,
  `TRACKING_DEFAULT_MODE`, `TRACKER_POLL_MINUTES`, `<PROVIDER>_WEBHOOK_SECRET`.
  A project's tracking (`/projects/{id}/tracking`, `app/services/tracking.py`, USER_FLOWS §C12)
  is read/adjusted in place and **switched** native ⇄ mirrored ⇄ another tracker through a plan:
  `plan_switch` (read-only, per-task keep|adopt|publish|release|remap) → `apply_switch` (one
  transaction: detach old binding keeping refs as history, release + remap, new binding, adopt,
  flip mode) → publish (content only, idempotent) → first sync. Preview == apply is pinned by
  `tests/test_tracking_switch.py`; applying is human-only.
- Jira (`app/connectors/jira.py`) is a `WorkTracker`: enhanced JQL search + Agile API (sprints
  mirrored when the binding syncs iterations) + changelog → `TaskStatusHistory`, project statuses →
  the binding's status map. Jira status stays read-only. **Assignee → ownership:** sync maps the
  issue assignee to an `Engineer` (match the tracker identity, then email, then exact name,
  recording the identity, else auto-create — `resolve_assignee_engineer` in
  `app/services/ingest.py`) and sets `Task.assignee_engineer_id`; an issue unassigned in the
  tracker leaves a locally-set owner alone.
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
  connections (trackers: the payload's scope hint against each connection's bindings —
  `app/webhooks/trackers.py`), then enqueue `process_webhook` (arq) — never process inline. Intake
  **fails closed**: `require_valid_signature` (or the tracker's `verify_webhook` on the generic
  `/webhooks/{provider}`) answers 403 while the endpoint's `*_WEBHOOK_SECRET` is unset and 401 on a
  missing/forged signature — never accept an unsigned payload. `GitHubConnector.handle_webhook`
  upserts the `PullRequest` cache; a tracker's `handle_webhook` upserts the task via the engine.
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
  REST routes (~140 across projects/planning/proposals/connectors/tracking/team/architecture/
  scenarios/specs/docs/delivery/outcomes/sprints; tracker tools are neutral — `sync_tracker`,
  `link_tracker_item`, `ingest_work_items`, `finalize_draft_plan`, `*_project_tracking`). Skills
  are runbooks (`updating-canopy` — the
  session operating guide every canopy session starts from, `harvesting-signals`,
  `persona-playbooks`, `planning-roadmaps`, `writing-adrs`, `syncing-trackers`, `mcp-ingest`,
  `capacity-planning`, `decision-deadline-nudger`, `pr-to-adr-linker`, `drafting-tickets`,
  `mapping-epic-docs`, `planning-sprints`, `working-the-board`, `spec-driven-development`,
  `daily-standup`); subagents
  do isolated multi-step work (`tracker-sync`, `gantt-planner`, `risk-analyst`, `drift-sentinel`,
  `scenario-architect`, `delivery-enricher`, `signal-harvester`). Add a tool when Claude needs a new verb; register it
  in `mcp_server/server.py`.
- **Background schedules (arq worker):** `app/workers/worker.py` runs cron jobs — the tracker
  reconciliation poll (`tracker_incremental_sync` over every enabled direct-read tracker), a
  **nightly changelog backfill**
  (`tracker_history_backfill`, bounded per binding via its cursor) and a **nightly risk-snapshot sweep** (`capture_risk_snapshots` → `run_risk_snapshots`)
  so the risk timeline is a real trend. Drift carries a **scan log** (`DriftScan`): `GET .../drift`
  returns `last_scanned_at` + `scan_due` (true when code bindings exist but the scan is missing or
  >7 days old), surfacing staleness so the Drift Sentinel re-scans (the server can't crawl code).
- **Startup refuses guessable secrets** (`app/core/startup_checks.py`): the API lifespan and the
  worker's `on_startup` stop on an empty, published-placeholder or <32-byte `SECRET_KEY`; seeding
  refuses to create the first admin with a placeholder or <8-char password; the MCP server refuses
  HTTP beyond loopback without `CANOPY_MCP_AUTH_TOKEN`. The checks run at startup, not import, so
  tests/Alembic/scripts are unaffected — keep it that way, and don't add an "allow insecure" switch.
- **Observability:** `GET /api/v1/health` (liveness, also reports `demo_mode`) and
  `/api/v1/health/ready` (DB check) for orchestration; structured logging via `app/core/logging.py`.
- **Demo / seeded-data mode (`DEMO_MODE`, local/dev only):** a repo-resident dataset in
  `app/services/seed/` (`catalog.py` = declarative schema, `ecommerce.py` +
  `ecommerce_projects.py` = data, `loader.py` = build/reset engine) that fills
  every UI surface; an admin loads/resets it from the UI (`/admin/demo`, `app/api/v1/admin_demo.py`,
  double-gated on admin **and** `DEMO_MODE` via `require_demo_mode`). `clear_all_data` wipes by
  iterating `SQLModel.metadata.sorted_tables` in reverse (nulling self-FKs first — portability rule),
  keeping the acting admin + superuser. Demo connectors (`config.demo=true`) are served by an offline
  HTTP mock (`app/connectors/demo.py`) injected at `Connector.open_client`, so Jira/GitHub/Drive
  sync + reads work without credentials. Extend the seed as features grow (it backs e2e). The
  narrative is a fictional **online retailer** (generic e-commerce, `example.com` placeholders):
  Checkout Modernization / Search & Discovery / Delivery Promise / Marketplace Launch / Holiday
  Peak Readiness over 10 projects, organised into two teams with pods, directors and managers,
  owned via `InitiativeLead` seats, every project with one owner, and a CTO / CPO with seeded
  leadership notes. The loader is generic: datasets are `Dataset` holders registered in
  `seed/__init__.py:DATASETS`, picked by `DEMO_DATASET` (default `ecommerce`; an unknown value
  falls back to the default) or per reseed (`?dataset=`). The loader silently skips unresolvable
  names, so `tests/test_demo_seed.py` pins every cross-reference. USER_FLOWS §Z/§Z1a.
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
- **`sqlmodel` is capped `<0.0.45`**: 0.0.45 maps `datetime` to a tz-aware `UTCDateTime` that rejects
  the naive UTC datetimes canopy stores (see the portability rules) — lifting the cap means migrating
  every datetime field, not bumping a version. **`fastmcp` is capped below its next major**, and
  **`ruff`/`mypy` are pinned exactly**, so a fresh clone's CI can't go red on an upstream release;
  bump them deliberately (Dependabot opens the PRs).

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
- **GitHub Actions** (`.github/workflows/ci.yml`) runs the same gate on every PR and push to `main`,
  plus what the hooks can't: backend tests on Python 3.11/3.12/3.13, `alembic upgrade head` on SQLite +
  real PostgreSQL/MySQL/MariaDB with an `alembic check` drift test (skipped on SQLite, where the
  VARCHAR→TEXT widenings are deliberate no-ops), and an MCP-server import smoke test.
  `.github/dependabot.yml` proposes weekly dependency PRs.
- Open-source hygiene: Apache-2.0 (`LICENSE` + `NOTICE`); `CONTRIBUTING.md`, `SECURITY.md`
  (private vulnerability reporting) and `CODE_OF_CONDUCT.md` at the root; issue/PR templates in
  `.github/`. Demo/seed data must stay fictional.
