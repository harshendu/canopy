# canopy

**An architecture + delivery cockpit for software architects.** Plan with a real critical path, keep
architecture decisions honest with fitness functions and drift detection, and see delivery risk
before it lands — synced from Jira, reading GitHub and Google Drive, and driven from a web dashboard
or conversationally from Claude.

[![CI](https://github.com/harshendu/canopy/actions/workflows/ci.yml/badge.svg)](https://github.com/harshendu/canopy/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776ab)
![Node.js 22+](https://img.shields.io/badge/node.js-22%2B-5fa04e)

![The canopy portfolio dashboard: every project with completion, critical-task count, risk and drift badges](docs/images/screenshots/portfolio.png)

> *Like a forest canopy — the interconnected upper layer that shelters the ecosystem beneath it and
> the one vantage point from which you see all of it at once — canopy gives an architect a single
> overhead view of the projects, teams, decisions and dependencies growing underneath.*

**Status:** pre-1.0 and under active development. Expect API and schema changes between versions;
database migrations are always provided.

## Contents

- [Why canopy](#why-canopy)
- [Features](#features)
- [Quickstart](#quickstart)
- [Configuration](#configuration)
- [Connecting Jira, GitHub and Google Drive](#connecting-jira-github-and-google-drive)
- [Claude Code plugin](#claude-code-plugin)
- [Production deployment](#production-deployment)
- [Architecture](#architecture)
- [Development](#development)
- [Documentation](#documentation)
- [Contributing, security and license](#contributing-security-and-license)

## Why canopy

Most tooling makes you choose: a Gantt tool that knows nothing about your architecture, an ADR repo
that knows nothing about your schedule, and a Jira board that knows nothing about either. The
expensive failures live in the seams between them — a cross-team hand-off discovered at integration,
a decision made implicitly in a PR and found months later as drift, a decision stuck "under
discussion" quietly blocking five people.

canopy keeps one traceable spine from **intent** (initiatives → projects → decisions → work) to
**verification** (schedule, fitness functions, drift, risk, outcomes), so a team can run a large
initiative concurrently and find out what's wrong while it's still cheap to fix. It is deliberately
*not* another system of record: Jira keeps owning tickets and their status, GitHub keeps owning
code, Drive keeps owning design docs — canopy mirrors and reads them, and adds the architecture and
delivery layer on top.

There are two front doors over one FastAPI backend: a **React dashboard**, and a **Claude Code
plugin** (an MCP server plus skills and subagents) that lets Claude do the same work conversationally,
under the same permissions.

## Features

| Area | What you get |
| --- | --- |
| **Plan & schedule** | WBS + Gantt with typed dependencies (FS/SS/FF/SF with lag); **critical path (CPM)** computed server-side on a working calendar (weekends + holidays); baselines with schedule variance; what-if duration overrides; initiative-level **scenarios** you can compare and apply; **Monte-Carlo P50/P85 forecasts** from your team's real throughput. |
| **Execute & track** | Kanban flow board with WIP and aging; blockers; burndown; per-project and org-wide **capacity heatmaps** with engineer availability; team-level **DORA + flow delivery metrics**; a *My work* / *Today* workspace for engineers. |
| **Architecture & decisions** | Component map; **ADRs** with a full lifecycle, reviews, alternatives and one-way/two-way-door reversibility; decision queue; blast-radius analysis; **fitness functions** on ADRs and an architecture **drift** queue; **specs** with checkable acceptance criteria; a document graph that links (never copies) docs in Jira, Drive, Figma and GitHub. |
| **Programs & leadership** | **Initiatives** that roll up project health, a cross-project critical path with hand-offs, and a weekly digest; a 0–100 **risk score** across schedule/capacity/architecture/quality with a nightly timeline, a RAID register and alerts; **outcomes** tracked as measurable bets; teams, pods and owners with ownership-scoped editing; leadership notes and a business-review roll-up; **PDF/CSV export** snapshots (download or save to Drive). |
| **Integrations** | **Jira** idempotent sync (epics → phases, stories → tasks, sprints, status history, assignee → owner), plus pushing an architect-reviewed draft plan as tickets; **GitHub** and **Google Drive** reads (repos, PRs, design docs, ADR import from markdown); HMAC-verified webhooks with a polling backstop; OAuth 2.0 (3LO) or API tokens, encrypted at rest. |
| **AI-native** | A **Claude Code plugin** with 120+ curated MCP tools, 14 skills and 7 subagents; **review-first change proposals** — agents stage updates inferred from Slack, email, meetings or docs for a human to review and apply; **bounded agent tokens** that can't take one-way-door actions (accepting an irreversible ADR, pushing to Jira, applying a scenario). |
| **Admin & operations** | Roles (admin, architect, engineering manager, engineer, viewer) plus cross-functional personas that pick each user's landing page; per-feature on/off gates; per-integration read/write policy; admin impersonation; **demo mode** with a seeded dataset and offline-mocked connectors; live updates over SSE; PostgreSQL or MySQL/MariaDB in production, SQLite for local dev. |

| Initiative cockpit | Gantt with critical path | Risk score |
| --- | --- | --- |
| [![Initiative cockpit: attention list, progress, worst risk and drift, CPM end date vs P85 forecast, and the cross-project critical path](docs/images/screenshots/initiative.png)](docs/images/screenshots/initiative.png) | [![Gantt chart with the critical path in red, phases, owners, today's line and schedule variance against the baseline](docs/images/screenshots/gantt.png)](docs/images/screenshots/gantt.png) | [![Risk score of 44 broken into schedule, capacity, architecture and quality families](docs/images/screenshots/risk.png)](docs/images/screenshots/risk.png) |

*Screenshots show the demo dataset: a fictional online retailer (checkout, search, delivery, a marketplace and holiday-peak readiness).*

## Quickstart

### Option A — Docker (recommended)

Requires Docker with Compose v2, plus Python 3 for the setup script.

```bash
git clone https://github.com/harshendu/canopy.git && cd canopy
python3 scripts/init.py --defaults --no-start   # writes .env: generated secrets + admin password
echo "DEMO_MODE=true" >> .env                    # optional: unlock the demo dataset (local only!)
docker compose up --build
```

Then open **http://localhost:5173** and sign in as `architect@example.com` with the password
`init.py` printed (it's also `FIRST_SUPERUSER_PASSWORD` in `.env`). With demo mode on, open
**Demo data** in the sidebar and load the demo dataset — a fictional online retailer — to explore
every screen with realistic data; the login page then lists demo accounts for each role (password
`canopy-demo`).

The stack runs PostgreSQL, Redis, the API (http://localhost:8000, OpenAPI docs at `/docs`), the
background worker and the Vite dev server. Migrations and the first admin are applied automatically
on start. Run `python3 scripts/init.py` without flags for an interactive setup that asks about the
database, the admin account and integrations, and can start the stack for you.

### Option B — Local processes (no Docker)

Requires Python 3.11+ and Node.js 22+ (20.19+ works, but Node 20 is end-of-life).

```bash
git clone https://github.com/harshendu/canopy.git && cd canopy
./scripts/setup.sh                              # backend/.venv + frontend/node_modules
python3 scripts/init.py --defaults --no-start   # .env with SQLite + generated secrets

# terminal 1 — API on http://localhost:8000
cd backend && . .venv/bin/activate
alembic upgrade head
uvicorn app.main:app --reload

# terminal 2 — web app on http://localhost:5173 (proxies /api to :8000)
cd frontend && npm run dev
```

The background worker (Jira polling and nightly risk snapshots) needs Redis; start it with
`arq app.workers.worker.WorkerSettings` from `backend/` when you need it.

## Configuration

All settings are environment variables, read from `.env` at the repo root (or `backend/.env`).
[`.env.example`](.env.example) documents every one; `scripts/init.py` generates a working file.

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql+asyncpg://canopy:canopy@localhost:5432/canopy` | Async SQLAlchemy URL: `postgresql+asyncpg://…`, `mysql+aiomysql://…` (install the `[mysql]` extra), or `sqlite+aiosqlite:///…` (local dev only) |
| `REDIS_URL` | `redis://localhost:6379/0` | Queue for the arq background worker |
| `SECRET_KEY` | — | **Required.** Signs access tokens and OAuth state. The API and worker refuse to start while it's empty, a published placeholder, or shorter than 32 characters |
| `TOKEN_ENCRYPTION_KEY` | derived from `SECRET_KEY` | Fernet key that encrypts connector credentials at rest; set it explicitly in production |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `480` | Access-token lifetime |
| `FIRST_SUPERUSER_EMAIL` / `FIRST_SUPERUSER_PASSWORD` | unset | Admin account created on startup if it doesn't exist. Startup refuses to create it with a password under 8 characters or a placeholder such as `changeme` |
| `BACKEND_CORS_ORIGINS` | `http://localhost:5173,http://localhost:4173` | Comma-separated origins allowed to call the API |
| `DEMO_MODE` / `DEMO_DATASET` | `false` / `ecommerce` | Unlocks the demo seed/reset endpoints and offline connector mocks. Dataset: `ecommerce` (a fictional online retailer). **Never enable in production.** |
| `OAUTH_REDIRECT_BASE_URL` / `FRONTEND_BASE_URL` | `http://localhost:8000` / `http://localhost:5173` | Public URLs for OAuth callbacks and the post-consent redirect |
| `JIRA_OAUTH_CLIENT_ID` / `…_SECRET`, `GITHUB_…`, `GOOGLE_…` | unset | OAuth 2.0 app credentials (only needed for the OAuth flow) |
| `GITHUB_WEBHOOK_SECRET`, `JIRA_WEBHOOK_SECRET`, `EVENTS_WEBHOOK_SECRET` | unset | HMAC secrets for `/webhooks/*`. Each endpoint **rejects every request** (403) until its secret is set |
| `JIRA_POLL_MINUTES` | `10` | Cadence of the worker's Jira reconciliation poll |
| `FILE_DROP_BACKEND` (+ `FILE_DROP_*`) | disabled | Poll a local directory or S3 bucket for JSON/CSV exports to ingest (S3 needs the `[s3]` extra) |
| `PLUGIN_MARKETPLACE_REF`, `PLUGIN_REPO_URL`, `PLUGIN_MCP_SERVER_PATH` | this repo | What the in-app *Agent Setup* page tells users to install — point them at your fork |

The production compose file adds `POSTGRES_PASSWORD`, `PUBLIC_BASE_URL`, `CANOPY_DOMAIN`/`CANOPY_TLS`
(Let's Encrypt), `NGROK_AUTHTOKEN` and the MCP variables below — see
[`docs/PRODUCTION.md`](docs/PRODUCTION.md).

## Connecting Jira, GitHub and Google Drive

Add connections on the **Connectors** page (`/connectors`), then either paste an API token or click
**Connect** to authorize with OAuth. Credentials are stored encrypted.

| Provider | Token setup | OAuth 2.0 (3LO) scopes canopy requests |
| --- | --- | --- |
| Jira Cloud | Site URL (`https://you.atlassian.net`), account email, [API token](https://id.atlassian.com/manage-profile/security/api-tokens), Jira project key, and the canopy project to sync into | `read:jira-work write:jira-work read:jira-user offline_access` |
| GitHub | Owner/org, repository, a token with read access to it, and the canopy project | `repo read:org` |
| Google Drive | Use **Connect** (OAuth) | `drive.readonly` (read design docs), `drive.file` (save exports) |

For OAuth, register an app with each provider using the callback URL
`<OAUTH_REDIRECT_BASE_URL>/api/v1/connectors/oauth/callback` and set the matching `*_OAUTH_CLIENT_ID`
and `*_OAUTH_CLIENT_SECRET`. For push updates, point GitHub at `<public URL>/webhooks/github` and Jira
at `<public URL>/webhooks/jira`, using the webhook secrets above. Without webhooks, the worker's poll
keeps Jira in sync.

> **Source-of-truth boundaries.** canopy syncs *from* Jira and **never writes ticket status back**.
> Its only Jira writes are creating and updating ticket *content* from a draft plan an architect has
> reviewed. GitHub and Drive are read-only, except for saving export snapshots to Drive.

## Claude Code plugin

The [`plugin/`](plugin) directory is a [Claude Code](https://claude.com/claude-code) plugin: an MCP
server with **120+ curated tools** (one per architect intent, not a mirror of the REST API), **14
skills** (runbooks such as `planning-roadmaps`, `writing-adrs`, `syncing-jira`,
`spec-driven-development` and `updating-canopy`, the session operating guide) and **7 subagents**
(`gantt-planner`, `jira-sync`, `risk-analyst`, `drift-sentinel`, `scenario-architect`,
`delivery-enricher`, `signal-harvester`).

**1. Mint a token.** In the dashboard, open **Agent Setup** (`/agent-setup`) and generate an *agent
token*. It acts with your permissions, minus one-way-door actions, and can be revoked at any time.
The page also renders these steps with your URL and token filled in.

**2. Install the plugin** from Claude Code:

```text
/plugin marketplace add harshendu/canopy
/plugin install canopy@canopy
```

(On Claude Code 2.1.275 or later, one step works: `/plugin install canopy --marketplace harshendu/canopy`.)
The install dialog asks for `api_base_url` (for example `http://localhost:8000`) and `api_token`.

**3. Provide the server's Python dependencies.** The plugin launches its MCP server with the `python`
on your `PATH` (3.11+), which needs `fastmcp` and `httpx`. For example, create a venv and start
Claude Code from a shell where it's active:

```bash
python3 -m venv ~/.venvs/canopy-mcp && . ~/.venvs/canopy-mcp/bin/activate
pip install "fastmcp>=2.3,<5" "httpx>=0.27"
```

Then ask things like *"what's my riskiest project and why?"*, *"sync Jira and tell me what
slipped"*, or *"draft an ADR for moving the scheduler to a queue"*. Writes an agent infers from
external sources are staged as **change proposals** in the dashboard's **Reviews** queue, not applied
directly.

**MCP only, without the plugin:** clone the repo, install `plugin/mcp_server/requirements.txt` into a
venv, and register the server in your project's `.mcp.json`. Use the venv's interpreter as `command`
and set `CANOPY_API_BASE_URL` and `CANOPY_API_TOKEN` in `env`; Agent Setup's *MCP only* tab generates
the snippet. **Hosted / cloud Claude sessions** can connect to the server over streamable HTTP
instead; see [`docs/PRODUCTION.md`](docs/PRODUCTION.md#4-connect-claude-over-mcp-streamable-http).

| MCP server variable | Purpose | Default |
| --- | --- | --- |
| `CANOPY_API_BASE_URL` | canopy API the tools call | `http://localhost:8000` |
| `CANOPY_API_TOKEN` | Agent token or JWT for the API | — |
| `CANOPY_API_EMAIL` / `CANOPY_API_PASSWORD` | Service account to log in as instead of a token (refreshes its own JWT) | — |
| `CANOPY_DASHBOARD_URL` | Dashboard origin used in review links | API base URL |
| `CANOPY_MCP_TRANSPORT` | `stdio`, `http` (streamable HTTP) or `sse` (legacy) | `stdio` |
| `CANOPY_MCP_HOST` / `CANOPY_MCP_PORT` / `CANOPY_MCP_PATH` | Bind address and path for the network transports | `127.0.0.1` / `8765` / `/mcp` |
| `CANOPY_MCP_AUTH_TOKEN` | Require `Authorization: Bearer …` on the HTTP endpoint. Mandatory unless bound to loopback: the server refuses to start without it | — |

## Production deployment

[`compose.prod.yml`](compose.prod.yml) runs the whole stack on one machine behind **Caddy**, which
terminates TLS, serves the built React app, and routes `/api` and `/webhooks` to the API and `/mcp`
to the MCP server. An optional **ngrok** profile provides public access without opening ports.

```bash
cp .env.example .env   # then set SECRET_KEY, TOKEN_ENCRYPTION_KEY, POSTGRES_PASSWORD, the first
                       # admin, CANOPY_MCP_AUTH_TOKEN and the webhook secrets
docker compose -f compose.prod.yml up -d --build
```

Production runs on **PostgreSQL** or **MySQL/MariaDB**; SQLite is for local development only. To run
without Docker, apply `alembic upgrade head` against your database and run uvicorn, the arq worker,
and the MCP server as services. The [production guide](docs/PRODUCTION.md) covers both, plus
backups, upgrades, health checks and a security checklist.

## Architecture

![Architecture: the React dashboard and the Claude Code plugin both call one FastAPI REST API, backed by pure scheduling, risk, forecast, capacity and connector services, a SQL database, and an arq worker with Redis; Jira, GitHub and Google Drive are external systems of record](docs/images/architecture.png)

- **Backend** — FastAPI, SQLModel/SQLAlchemy (async), Alembic, arq + Redis. Business logic lives in
  mostly pure, unit-tested services under `backend/app/services/`; the CPM scheduler is a
  forward/backward pass over a `networkx` DAG.
- **Frontend** — React 18, TypeScript, Vite, Tailwind CSS v4, TanStack Query; a custom SVG Gantt,
  React Flow graphs and Recharts charts.
- **Plugin** — a FastMCP server that is a thin client of the REST API, plus markdown skills and
  subagents, so Claude gets exactly the permissions of the token it holds.
- **Integrations** — connectors share one interface; sync is idempotent through an external-reference
  table; all outbound HTTP retries with backoff.
- **Portability** — every migration and query runs on PostgreSQL, MySQL/MariaDB and SQLite, and CI
  verifies the migration chain on all of them.

```text
backend/    FastAPI app: api/v1 (routers), models, schemas, services, connectors, webhooks, workers
            alembic/ migrations · tests/ pytest suite
frontend/   React app: pages, components, api (typed client), lib (pure, unit-tested helpers)
plugin/     Claude Code plugin: mcp_server/ (FastMCP), skills/, agents/
e2e/        Browser end-to-end tests (Selenium)
deploy/     Caddy front door for compose.prod.yml
docs/       User flows, production guide, design notes, diagrams
scripts/    setup.sh · ci.sh · init.py (guided setup) · install-hooks.sh
```

[`CLAUDE.md`](CLAUDE.md) is the detailed engineering guide covering conventions, where each concern
lives, and the decisions behind them. It is written for AI coding agents, and is just as useful for
humans.

## Development

```bash
./scripts/setup.sh          # bootstrap: backend venv + deps, frontend deps (idempotent)
./scripts/install-hooks.sh  # pre-commit: checks the layers you touched · pre-push: full gate
./scripts/ci.sh             # the local quality gate
```

| Check | Command (from the package directory) |
| --- | --- |
| Backend lint | `ruff check .` (strict ruleset; every `def` is typed) |
| Backend types | `mypy app` |
| Backend tests | `pytest -q` |
| Frontend lint | `npm run lint` (ESLint, zero warnings) |
| Frontend tests | `npm run test` (Vitest) |
| Frontend build | `npm run build` (`tsc` + Vite) |
| End-to-end | `e2e/run_e2e.sh` (boots the stack and drives Chrome; see [`e2e/README.md`](e2e/README.md)) |

GitHub Actions runs the backend suite on Python 3.11–3.13, the frontend gate, a smoke test of the MCP
server, and the migration chain (with a model↔migration drift check) on real PostgreSQL, MySQL and
MariaDB. Dependabot keeps dependencies current. Schema changes are autogenerated Alembic revisions
that must stay portable; see [CONTRIBUTING.md](CONTRIBUTING.md#database-changes).

## Documentation

| Document | What's in it |
| --- | --- |
| [`docs/WIKI.md`](docs/WIKI.md) | Product tour: personas, the two front doors, every feature, roles and permissions |
| [`docs/USER_FLOWS.md`](docs/USER_FLOWS.md) | Every user-facing flow with its UI path, REST endpoint and MCP tool, plus known gaps |
| [`docs/PRODUCTION.md`](docs/PRODUCTION.md) | Single-machine production setup, operations and the security checklist |
| [`docs/EXECUTION_PHILOSOPHY.md`](docs/EXECUTION_PHILOSOPHY.md) | The operating model behind canopy |
| [`docs/AI_NATIVE_EXECUTION.md`](docs/AI_NATIVE_EXECUTION.md) | The AI-native vision and roadmap |
| [`docs/PROPOSED_FLOWS.md`](docs/PROPOSED_FLOWS.md) | Proposed revisions and extensions to the user flows (not yet built) |
| [`e2e/README.md`](e2e/README.md) | Running and writing browser end-to-end tests |
| `http://localhost:8000/docs` | Live OpenAPI reference for the REST API |

## Contributing, security and license

- **Contributing:** issues and pull requests are welcome. [CONTRIBUTING.md](CONTRIBUTING.md) covers
  setup, the quality bar and project conventions.
- **Security:** please report vulnerabilities privately; see [SECURITY.md](SECURITY.md).
- **Code of Conduct:** this project follows the [Contributor Covenant](CODE_OF_CONDUCT.md).
- **License:** [Apache License 2.0](LICENSE). See [NOTICE](NOTICE).
