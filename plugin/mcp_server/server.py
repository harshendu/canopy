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
  CANOPY_MCP_AUTH_TOKEN  optional shared secret; when set, network clients must send
                         "Authorization: Bearer <token>" (set it whenever the port is
                         reachable beyond localhost — e.g. behind Caddy/ngrok)

Locally the plugin launches this over stdio. In production, run it as a long-lived
service with CANOPY_MCP_TRANSPORT=http (streamable HTTP, the modern MCP transport —
"streamable-http" is accepted as an alias) and point Claude at https://<host>/mcp.
SSE remains available for older clients but is deprecated upstream.
"""

from __future__ import annotations

import hmac
import os
import pathlib
import sys

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
    scenarios,
    specs,
    team,
)

mcp = FastMCP("canopy")
client = CanopyClient()

projects.register(mcp, client)
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


def main() -> None:
    transport = os.environ.get("CANOPY_MCP_TRANSPORT", "stdio").lower()
    if transport == "stdio":
        mcp.run()
        return

    host = os.environ.get("CANOPY_MCP_HOST", "127.0.0.1")
    port = int(os.environ.get("CANOPY_MCP_PORT", "8765"))
    default_path = "/sse" if transport == "sse" else "/mcp"
    path = os.environ.get("CANOPY_MCP_PATH", default_path)
    auth_token = os.environ.get("CANOPY_MCP_AUTH_TOKEN", "")

    # "http" / "streamable-http" -> streamable HTTP (the modern transport); "sse" -> legacy.
    app_transport = "sse" if transport == "sse" else "streamable-http"
    app = mcp.http_app(path=path, transport=app_transport)
    if auth_token:
        app = BearerGuard(app, auth_token)

    import uvicorn  # a fastmcp dependency; imported lazily to keep stdio startup lean

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
