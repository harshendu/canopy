# Production setup (single machine, quick start)

One machine runs the whole stack — API, MCP server, database, worker — behind **Caddy**
(SSL termination + port mapping) with **ngrok** for public access:

```
   Claude (MCP)          browser            Jira / GitHub webhooks
        \                   |                     /
         \                  |                    /
          └────────── ngrok public HTTPS ──────┘        (optional --profile ngrok)
                            |
                          caddy  :80 / :443              SSL termination + port mapping
             ┌──────────────┼──────────────────┐
          /mcp        /api  /webhooks       /  (static React build)
             |              |
            mcp ────────► backend :8000 ◄──── worker (arq cron)
          :8765             |        \
   (streamable HTTP)       db :5432  redis :6379
```

Only Caddy publishes host ports; db/redis/backend/mcp stay on the internal Docker
network. The frontend is a static production build served by Caddy — same origin as
the API, so no CORS configuration is needed.

## 1. Configure

```bash
git clone <your-fork> canopy && cd canopy
cp .env.example .env
```

Set in `.env` (everything else can keep its default):

| Variable | What it is |
| --- | --- |
| `SECRET_KEY` | long random string (`openssl rand -hex 32`) — signs JWTs; the backend and worker refuse to start without a strong one |
| `TOKEN_ENCRYPTION_KEY` | Fernet key for connector tokens: `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `POSTGRES_PASSWORD` | database password (compose refuses to start without it) |
| `FIRST_SUPERUSER_EMAIL` / `FIRST_SUPERUSER_PASSWORD` | the initial admin account, seeded on first boot (8+ characters; placeholders like `changeme` are refused) |
| `CANOPY_MCP_AUTH_TOKEN` | shared secret for the public MCP endpoint (`openssl rand -hex 24`) |
| `CANOPY_API_EMAIL` / `CANOPY_API_PASSWORD` | the canopy account the MCP server acts as (create a dedicated one after first login, or reuse the superuser to start); it logs in and refreshes its own JWT |
| `DEMO_MODE` | leave `false` — demo/seed endpoints are hard-gated off in production |

> The MCP service account's **role** bounds what Claude can do (e.g. an
> `engineering_manager` can plan but not administer users). For one-way-door safety you
> can instead mint a bounded **agent token** (`POST /api/v1/auth/agent-token`) and set it
> as `CANOPY_API_TOKEN` — it blocks Jira pushes / scenario applies / one-way ADR accepts,
> but expires (30 days max), so the email/password service account is the
> zero-maintenance default.

## 2. Launch

```bash
docker compose -f compose.prod.yml up -d --build
```

Check it:

```bash
curl -s http://localhost/api/v1/health        # {"status":"ok",...,"demo_mode":false}
curl -s http://localhost/api/v1/health/ready  # {"status":"ready"} (DB reachable)
```

Open `http://localhost` (or `http://<machine-ip>` from another machine), sign in as the
superuser, then:

- **Users** (`/admin/users`): provision accounts — email + temp password + role +
  function; reset passwords; deactivate leavers. Everyone can rotate their own password
  from the sidebar. The last active admin can't be demoted/deactivated.
- **Features** (`/admin/features`): turn whole surfaces (groups) or single features
  on/off. Toggles enforce at the API (403 with `feature_disabled`) and the UI updates
  live over SSE — no restart. Core flows (projects, tasks, Gantt/CPM, team, auth) are
  always on.
- **Integrations** (`/admin/integrations`) + **Connectors** (`/connectors`): per-provider
  read/write policy and the actual Jira/GitHub/Drive connections.

## 3. Public access with ngrok

```bash
# add NGROK_AUTHTOKEN to .env (from https://dashboard.ngrok.com), then:
docker compose -f compose.prod.yml --profile ngrok up -d
# the public URL appears in the inspector: http://localhost:4040  (or `docker compose logs ngrok`)
```

ngrok terminates public TLS at its edge and forwards to Caddy's plain-HTTP `:80`
listener (which never redirects, so the tunnel doesn't bounce). With a reserved ngrok
domain, pin it via the alternate `command:` line in `compose.prod.yml`.

Then set the public URL in `.env` and restart the backend so OAuth redirects and
outbound links use it:

```bash
# .env
PUBLIC_BASE_URL=https://<your-tunnel>.ngrok.app
docker compose -f compose.prod.yml up -d backend
```

- **Webhooks:** point GitHub at `https://<public>/webhooks/github` and Jira at
  `https://<public>/webhooks/jira` (secrets: `GITHUB_WEBHOOK_SECRET` /
  `JIRA_WEBHOOK_SECRET` in `.env`).
- **OAuth apps:** register the callback `https://<public>/api/v1/connectors/oauth/callback`.

With your own domain instead of ngrok: point DNS at the machine, open 80/443, set
`CANOPY_DOMAIN=canopy.example.com` and `CANOPY_TLS=you@example.com` in `.env` — Caddy
fetches Let's Encrypt certificates automatically.

## 4. Connect Claude over MCP (streamable HTTP)

The MCP server speaks **streamable HTTP** (the modern MCP transport; SSE remains only
for legacy clients) at `https://<public>/mcp`, guarded by the bearer token:

```json
{
  "mcpServers": {
    "canopy": {
      "type": "http",
      "url": "https://<your-tunnel>.ngrok.app/mcp",
      "headers": { "Authorization": "Bearer <CANOPY_MCP_AUTH_TOKEN>" }
    }
  }
}
```

Locally-installed plugins keep using stdio (unchanged): the plugin launches
`mcp_server/server.py` itself and reads `api_base_url` / `api_token` (or
`api_email`+`api_password`) from the plugin config.

Smoke-test the endpoint:

```bash
curl -s https://<public>/mcp -X POST \
  -H "Authorization: Bearer $CANOPY_MCP_AUTH_TOKEN" \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"probe","version":"0"}}}'
# -> event: message / data: {..."serverInfo":{"name":"canopy"...}}
```

## 5. Operations

- **Backups:** the database is the state — `docker compose -f compose.prod.yml exec db pg_dump -U canopy canopy > backup.sql`.
- **Upgrades:** `git pull && docker compose -f compose.prod.yml up -d --build` — Alembic
  migrations run automatically before the API starts.
- **Logs:** `docker compose -f compose.prod.yml logs -f backend worker mcp caddy`.
- **Health for orchestration:** `GET /api/v1/health` (liveness), `GET /api/v1/health/ready` (DB).
- The backend runs a **single uvicorn process** because the SSE live-refresh broker is
  in-process; Redis pub/sub is the documented upgrade path before scaling out.

### Security checklist

- [ ] `SECRET_KEY`, `TOKEN_ENCRYPTION_KEY`, `POSTGRES_PASSWORD` are strong + unique
- [ ] `DEMO_MODE=false` (verify via `/api/v1/health`)
- [ ] `CANOPY_MCP_AUTH_TOKEN` set (the `/mcp` path is public through the tunnel)
- [ ] MCP service account has the least role that fits (or a bounded agent token)
- [ ] Webhook secrets set (`GITHUB_WEBHOOK_SECRET`, `JIRA_WEBHOOK_SECRET`, `EVENTS_WEBHOOK_SECRET`)
      for each integration you use — an endpoint rejects every request (403) until its secret is set
- [ ] The superuser password was rotated after first login (sidebar → Change password)

## Bare-metal variant (no Docker)

Run the same four processes under systemd, with Caddy installed from your package
manager using the same `deploy/Caddyfile` (adjust the two upstreams to
`localhost:8000` / `localhost:8765`, and point the static root at `frontend/dist`
after `npm run build`):

```bash
# API           (backend/, venv active, .env exported)
alembic upgrade head && uvicorn app.main:app --host 127.0.0.1 --port 8000
# Worker
arq app.workers.worker.WorkerSettings
# MCP server    (plugin/, venv active)
CANOPY_MCP_TRANSPORT=http CANOPY_MCP_HOST=127.0.0.1 CANOPY_MCP_PORT=8765 \
CANOPY_MCP_AUTH_TOKEN=... CANOPY_API_BASE_URL=http://127.0.0.1:8000 \
CANOPY_API_EMAIL=... CANOPY_API_PASSWORD=... python mcp_server/server.py
# Tunnel
ngrok http 80
```
