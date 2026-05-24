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

## Run the whole stack (Docker)

```bash
cp .env.example .env
# edit .env: set SECRET_KEY, TOKEN_ENCRYPTION_KEY (see comment in the file), superuser creds
docker compose up --build
```

- API: http://localhost:8000 (`/docs` for OpenAPI, `/api/v1/health` for health)
- Web: http://localhost:5173
- Migrations (`alembic upgrade head`) and superuser seeding run automatically on start.

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
