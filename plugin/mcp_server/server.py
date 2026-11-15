"""Canopy MCP server (FastMCP).

A thin, curated layer over the canopy FastAPI backend — one tool per architect
intent, not a 1:1 mirror of REST routes.

Backend connection (used by the tools):
  CANOPY_API_BASE_URL   e.g. http://localhost:8000  (or your production API URL)
  CANOPY_API_TOKEN      a JWT from POST /api/v1/auth/login

Transport (how Claude reaches this server):
  CANOPY_MCP_TRANSPORT   stdio (default) | http | sse (legacy)
  CANOPY_MCP_HOST        bind host for the network transports (default 127.0.0.1)
  CANOPY_MCP_PORT        bind port for the network transports (default 8765)
  CANOPY_MCP_PATH        URL path (default /mcp for http, /sse for sse)
  CANOPY_MCP_AUTH_MODE   shared (default) | per_caller — how network clients authenticate:
                         shared: every client sends the one CANOPY_MCP_AUTH_TOKEN secret and
                           every tool acts with this server's own canopy credentials;
                         per_caller: every request carries the caller's OWN canopy agent token
                           ("Authorization: Bearer <token>"), validated with the API and used
                           for that request's calls — each session acts as itself, with its own
                           role / project scope (docs/AGENT_EXECUTION.md §18.2)
  CANOPY_MCP_AUTH_TOKEN  the shared secret (shared mode). Required to bind anywhere but loopback
                         in shared mode: every tool acts with this server's canopy credentials,
                         so the server refuses to start rather than serve them unauthenticated

Locally the plugin launches this over stdio. In production, run it as a long-lived
service with CANOPY_MCP_TRANSPORT=http (streamable HTTP, the modern MCP transport —
"streamable-http" is accepted as an alias) and point Claude at https://<host>/mcp.
SSE remains available for older clients but is deprecated upstream.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import os
import pathlib
import sys
import time

import httpx

# Make sibling modules importable when run as a script (python server.py).
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from fastmcp import FastMCP  # noqa: E402

from client import CanopyClient  # noqa: E402
from tools import (  # noqa: E402
    architecture,
    connectors,
    delivery,
    docs,
    drafts,
    metadata,
    outcomes,
    planning,
    projects,
    proposals,
    scenarios,
    specs,
    sprints,
    team,
    tracking,
)

mcp = FastMCP("canopy")
client = CanopyClient()

projects.register(mcp, client)
proposals.register(mcp, client)
planning.register(mcp, client)
connectors.register(mcp, client)
team.register(mcp, client)
architecture.register(mcp, client)
drafts.register(mcp, client)
scenarios.register(mcp, client)
metadata.register(mcp, client)
docs.register(mcp, client)
specs.register(mcp, client)
delivery.register(mcp, client)
outcomes.register(mcp, client)
sprints.register(mcp, client)
tracking.register(mcp, client)


class BearerGuard:
    """Minimal ASGI wrapper requiring `Authorization: Bearer <token>` on HTTP requests.

    Deliberately independent of the fastmcp version's auth plumbing; non-HTTP scopes
    (lifespan, websocket) pass through untouched.
    """

    def __init__(self, app, token: str) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        supplied = headers.get(b"authorization") or b""
        expected = f"Bearer {self.token}".encode()
        if not hmac.compare_digest(supplied, expected):
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"text/plain"),
                        (b"www-authenticate", b"Bearer"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": b"unauthorized"})
            return
        await self.app(scope, receive, send)


class CallerGuard:
    """Per-caller mode: every HTTP request must carry the caller's own canopy token, which is
    validated with the canopy API (`GET /auth/session` — signature, expiry, revocation) before the
    request reaches a tool. Valid tokens are remembered for a minute (by hash, never the secret)
    so a busy session doesn't re-validate on every call; a revoked token stops working within
    that minute. The tools then use the same token for their API calls (`client.caller_token`)."""

    CACHE_SECONDS = 60.0

    def __init__(self, app, api_base_url: str) -> None:
        self.app = app
        self.session_url = f"{api_base_url.rstrip('/')}/api/v1/auth/session"
        self._valid: dict[str, float] = {}

    async def _is_valid(self, token: str) -> bool:
        key = hashlib.sha256(token.encode()).hexdigest()
        now = time.monotonic()
        if self._valid.get(key, 0.0) > now:
            return True
        try:
            async with httpx.AsyncClient(timeout=10.0) as http:
                resp = await http.get(
                    self.session_url, headers={"Authorization": f"Bearer {token}"}
                )
        except httpx.HTTPError:
            return False
        if resp.status_code != 200:
            self._valid.pop(key, None)
            return False
        if len(self._valid) > 4096:  # bound the cache; expired entries go first
            self._valid = {k: v for k, v in self._valid.items() if v > now}
        self._valid[key] = now + self.CACHE_SECONDS
        return True

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        auth = (headers.get(b"authorization") or b"").decode("latin-1")
        kind, _, token = auth.partition(" ")
        token = token.strip()
        if kind.lower() != "bearer" or not token or not await self._is_valid(token):
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"text/plain"),
                        (b"www-authenticate", b"Bearer"),
                    ],
                }
            )
            await send(
                {"type": "http.response.body", "body": b"a valid canopy agent token is required"}
            )
            return
        await self.app(scope, receive, send)


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:  # a hostname: it may resolve to any interface
        return False


def main() -> None:
    transport = os.environ.get("CANOPY_MCP_TRANSPORT", "stdio").lower()
    if transport == "stdio":
        mcp.run()
        return

    host = os.environ.get("CANOPY_MCP_HOST", "127.0.0.1")
    port = int(os.environ.get("CANOPY_MCP_PORT", "8765"))
    default_path = "/sse" if transport == "sse" else "/mcp"
    path = os.environ.get("CANOPY_MCP_PATH", default_path)
    auth_mode = os.environ.get("CANOPY_MCP_AUTH_MODE", "shared").strip().lower().replace("-", "_")
    if auth_mode not in ("shared", "per_caller"):
        sys.exit(f"CANOPY_MCP_AUTH_MODE must be shared or per_caller, not {auth_mode!r}")
    auth_token = os.environ.get("CANOPY_MCP_AUTH_TOKEN", "")
    if auth_mode == "shared" and not auth_token and not _is_loopback(host):
        sys.exit(
            f"Refusing to serve the canopy MCP server on {host}:{port} without "
            "CANOPY_MCP_AUTH_TOKEN: anyone who can reach the port could act with this server's "
            "canopy credentials. Set CANOPY_MCP_AUTH_TOKEN (e.g. `openssl rand -hex 24`), "
            "bind CANOPY_MCP_HOST to 127.0.0.1, or set CANOPY_MCP_AUTH_MODE=per_caller so every "
            "client must present its own canopy agent token."
        )

    # "http" / "streamable-http" -> streamable HTTP (the modern transport); "sse" -> legacy.
    app_transport = "sse" if transport == "sse" else "streamable-http"
    app = mcp.http_app(path=path, transport=app_transport)
    if auth_mode == "per_caller":
        client.per_caller = True
        app = CallerGuard(app, os.environ.get("CANOPY_API_BASE_URL") or "http://localhost:8000")
    elif auth_token:
        app = BearerGuard(app, auth_token)

    import uvicorn  # a fastmcp dependency; imported lazily to keep stdio startup lean

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
