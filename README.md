# canopy

> *Like a **forest canopy** — the interconnected upper layer that shelters the ecosystem beneath it
> and is the one vantage from which you see the whole of it at once.* canopy gives a software
> architect that layer over delivery: a single overhead view tying together the projects, teams, and
> dependencies growing underneath.

**Technical Architect Project Management** — a tool for a software architect to manage the
architecture and delivery of a codebase: projects, milestones, teams, dependencies, ADRs, and
**Gantt scheduling** (critical path), with **sync from Jira** and reads from **GitHub** and
**Google Drive**. Two front doors over one FastAPI backend:

- a **React dashboard** (Vite + Tailwind) for visual views, and
- a **Claude Code plugin** (FastMCP server + skills + subagents) to drive canopy conversationally.

> Source-of-truth boundaries: **Jira** owns epics/stories and ticket status (canopy syncs *from*
> Jira, never writes status back). **GitHub** owns code + some architecture docs. **Drive** holds
> design docs. canopy mirrors and schedules around them.

## Layout

```
backend/   FastAPI + SQLModel + Alembic + arq (CPM scheduler, connectors, REST API)
frontend/  Vite + React + TS + Tailwind v4 + TanStack Query (Projects, Gantt, Connectors)
plugin/    Claude Code plugin: FastMCP server (thin API client) + skills + subagents
compose.yml  postgres + redis + backend + worker + frontend
```

## Quickstart (guided setup)

```bash
python3 scripts/init.py
```

An interactive wizard that collects the inputs it needs (database, admin
account, integrations), generates `.env` for you — auto-creating a random
`SECRET_KEY`, a Fernet `TOKEN_ENCRYPTION_KEY`, and a strong admin password —
then offers to start either the Docker stack or local dev servers. It backs up
any existing `.env` first; pass `--no-start` to only (re)generate the file. For
scripted/CI setup, `--defaults` runs non-interactively (SQLite + generated
secrets and admin password) — add `--start docker` to also launch the stack.

## Run the whole stack (Docker)

```bash
cp .env.example .env
# edit .env: set SECRET_KEY, TOKEN_ENCRYPTION_KEY (see comment in the file), superuser creds
docker compose up --build
```

(or just run `python3 scripts/init.py` and pick the Docker option)

- API: http://localhost:8000 (`/docs` for OpenAPI, `/api/v1/health` for health)
- Web: http://localhost:5173
- Migrations (`alembic upgrade head`) and superuser seeding run automatically on start.

## Production deployment

In production the backend runs against **PostgreSQL** or **MySQL/MariaDB** (SQLite is for
dev/local only), and the Claude MCP server is served over **SSE** so a hosted/cloud Claude
session can reach it. The whole data layer is dialect-portable — the schema migrations and
the ORM queries are validated against Postgres, MySQL/MariaDB **and** SQLite (see
*Database portability* below).

### 1. Database (Postgres or MySQL/MariaDB)

Pick a dialect and set `DATABASE_URL` to its **async** driver URL:

```bash
# PostgreSQL (asyncpg ships in the core deps)
DATABASE_URL="postgresql+asyncpg://USER:PASS@HOST:5432/canopy"

# MySQL / MariaDB (install the optional driver: pip install -e ".[mysql]")
DATABASE_URL="mysql+aiomysql://USER:PASS@HOST:3306/canopy"

# SQLite — dev/local only, NOT for production
DATABASE_URL="sqlite+aiosqlite:///./canopy.db"
```

Then apply the schema and start the API (same flow for either dialect):

```bash
cd backend
pip install -e ".[mysql]"     # only needed for MySQL/MariaDB; omit for Postgres
export DATABASE_URL="…"        # one of the URLs above
export SECRET_KEY="…" TOKEN_ENCRYPTION_KEY="…"   # generate real secrets (see .env.example)
alembic upgrade head           # creates/updates the schema on the target database
uvicorn app.main:app --host 0.0.0.0 --port 8000  # add --workers N behind a process manager
```

Run the worker alongside it for background jobs (Jira poll, nightly risk snapshots):

```bash
arq app.workers.worker.WorkerSettings
```

> **Database portability.** The Alembic migrations are written to run forward on Postgres,
> MySQL/MariaDB and SQLite (enum changes branch per dialect; foreign-key/column patches use
> native `ALTER` on the server DBs and table-rebuild only on SQLite). Timestamps are stored as
> **naive UTC** so they round-trip on every driver (asyncpg rejects tz-aware values for
> `TIMESTAMP WITHOUT TIME ZONE`). Note that **Postgres and MySQL enforce foreign keys** while
> SQLite does not by default — deletes that rely on cascade ordering are handled in the app
> so they behave the same on every dialect.

### 2. MCP server over SSE (for cloud Claude sessions)

Locally the plugin launches the MCP server over stdio. In production, run it as a long-lived
**SSE** service that a hosted Claude session connects to. Everything is configured by
environment variables, so a headless cloud session needs no interactive plugin config:

```bash
cd plugin
pip install -r mcp_server/requirements.txt
# Backend the tools call:
export CANOPY_API_BASE_URL="https://canopy.example.com"
export CANOPY_API_TOKEN="<JWT from POST /api/v1/auth/login>"
# Serve over SSE instead of stdio:
export CANOPY_MCP_TRANSPORT="sse"   # stdio (default) | sse | http | streamable-http
export CANOPY_MCP_HOST="0.0.0.0"
export CANOPY_MCP_PORT="8765"
export CANOPY_MCP_PATH="/sse"
python mcp_server/server.py          # serves SSE at http://HOST:PORT/sse
```

Point the cloud Claude session at that endpoint with an MCP server entry:

```json
{ "mcpServers": { "canopy": { "type": "sse", "url": "https://canopy.example.com:8765/sse" } } }
```

| Env var | Purpose | Default |
| --- | --- | --- |
| `CANOPY_API_BASE_URL` | canopy REST API the MCP tools call | `http://localhost:8000` |
| `CANOPY_API_TOKEN` | JWT for the API (`POST /api/v1/auth/login`) | — |
| `CANOPY_MCP_TRANSPORT` | `stdio` \| `sse` \| `http` \| `streamable-http` | `stdio` |
| `CANOPY_MCP_HOST` / `CANOPY_MCP_PORT` / `CANOPY_MCP_PATH` | SSE/HTTP bind address + path | `127.0.0.1` / `8765` / `/sse` |

For a locally-installed plugin, the same `CANOPY_API_*` values come from the plugin's
`api_base_url` / `api_token` config; for cloud sessions they (and the transport) are read
straight from the environment. Empty config values fall back to the environment, so a blank
plugin config never clobbers an env var the session provides.

## Developer setup & CI (no GitHub Actions)

```bash
./scripts/setup.sh        # bootstrap env on a vanilla VM (venv + pip + npm), idempotent
./scripts/ci.sh           # basic CI: setup + backend pytest + frontend build
./scripts/install-hooks.sh  # enable the git hooks for this clone
```

- CI gate = backend **ruff + mypy + pytest** and frontend **eslint + build** (`tsc` + `vite`).
- **pre-commit** runs the gate only for the layers you change (`RUN_ALL=1` forces both).
- **pre-push** runs `scripts/ci.sh` — it self-bootstraps the environment, so a freshly cloned
  vanilla VM (with `python3` and `node`/`npm` installed) can push and have CI run. A failure aborts
  the push.

## Backend (local dev)

```bash
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
export DATABASE_URL="sqlite+aiosqlite:///./canopy.db"   # or a local Postgres URL
alembic upgrade head
uvicorn app.main:app --reload
pytest        # CPM math, Jira mapping idempotency, auth + replan API
```

## Frontend (local dev)

```bash
cd frontend
npm install
npm run dev        # proxies /api -> http://localhost:8000
npm run build      # typecheck + production build
```

## Claude plugin

The plugin lives in `plugin/` and is cataloged by `.claude-plugin/marketplace.json` at the repo
root. It bundles an MCP server (`plugin/mcp_server/`, built with FastMCP), three skills
(`planning-roadmaps`, `writing-adrs`, `syncing-jira`), and two subagents (`jira-sync`,
`gantt-planner`).

```bash
cd plugin && python -m venv .venv && . .venv/bin/activate
pip install -r mcp_server/requirements.txt
```

Configure the plugin's `api_base_url` (e.g. `http://localhost:8000`) and `api_token` (a JWT from
`POST /api/v1/auth/login`). The MCP server exposes curated tools — `list_projects`, `create_task`,
`link_dependency`, `replan_schedule`, `trigger_jira_sync`, `read_design_doc`, `create_adr`, … —
that call the backend REST API.

By default the server talks **stdio** (the plugin launches it). To serve it over **SSE** for a
hosted/cloud Claude session, set `CANOPY_MCP_TRANSPORT=sse` (+ `CANOPY_MCP_HOST`/`PORT`/`PATH`) and
provide `CANOPY_API_BASE_URL` / `CANOPY_API_TOKEN` via the environment — see
*Production deployment → MCP server over SSE* above.

## Key concepts

- **WBS / Gantt:** a `Task` is the Gantt unit; a `summary` task is a phase/workstream (tree via
  `parent_id`). Dependencies are typed (FS/SS/FF/SF) with lag.
- **Scheduling:** the **critical path method** is computed backend-side (`app/services/scheduling.py`,
  forward/backward pass over a `networkx` DAG); `POST /projects/{id}/replan` persists dates,
  `is_critical`, and float.
- **Connectors:** a common `Connector` interface (`app/connectors/`). Jira sync is idempotent via
  the `ExternalRef` table; tokens are encrypted at rest (Fernet). Webhooks verify signatures and
  enqueue arq jobs; a periodic poll reconciles.
- **Architecture:** first-class `ArchitectureComponent` and `ArchitectureDecision` (ADR) with a
  supersession chain.
