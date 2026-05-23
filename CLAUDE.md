# CLAUDE.md

Guidance for Claude Code working in this repo.

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
frontend/  Vite + React + TS + Tailwind v4 + TanStack Query. Pages in src/pages,
           the SVG Gantt in src/components/GanttChart.tsx, API client in src/api.
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
pytest -q
```
Frontend (run from `frontend/`):
```bash
npm install
npm run dev          # proxies /api -> :8000
npm run build        # tsc typecheck + vite build (this is the "build" the hook runs)
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
  a `networkx` DAG). `POST /projects/{id}/replan` persists dates, `is_critical`, and float. Keep the
  scheduler pure and unit-tested; the frontend only renders.
- Connectors implement the ABC in `app/connectors/base.py` and self-register via `@register`. Sync is
  idempotent through the `ExternalRef` table (`app/services/mapping.py`). Connector tokens are
  encrypted at rest with Fernet (`app/core/crypto.py`).
- Webhooks (`app/webhooks/`) verify HMAC **before** parsing, then enqueue arq jobs — never process
  inline.
- MCP tools (`plugin/mcp_server/tools/`) are curated — one per architect intent, not a 1:1 mirror of
  REST routes. Skills are runbooks; subagents do isolated multi-step work.

## Gotchas (decisions already made — don't "fix" these back)
- Auth uses **`bcrypt` directly**, not `passlib` (passlib is unmaintained and breaks with bcrypt 4.x).
- GitHub/Drive connectors use **`httpx`**, not `githubkit`/google SDKs (fewer deps, stable REST).
- The Gantt is a **custom SVG component**, not a third-party Gantt lib (so it builds/typechecks in CI
  without a browser). SVAR/frappe are a possible upgrade.
- The `User` table is named `app_user` (`user` is reserved in Postgres).

## Before committing
A pre-commit hook runs backend `pytest` (if `backend/` changed) and the frontend `npm run build`
(if `frontend/` changed). Install it once with `scripts/install-hooks.sh`. Set `RUN_ALL=1` to force
both. Don't bypass with `--no-verify` — fix the failure.
