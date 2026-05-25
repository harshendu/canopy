"""Canopy MCP server (FastMCP).

A thin, curated layer over the canopy FastAPI backend — one tool per architect
intent, not a 1:1 mirror of REST routes.

Backend connection (used by the tools):
  CANOPY_API_BASE_URL   e.g. http://localhost:8000  (or your production API URL)
  CANOPY_API_TOKEN      a JWT from POST /api/v1/auth/login

Transport (how Claude reaches this server):
  CANOPY_MCP_TRANSPORT  stdio (default) | sse | http | streamable-http
  CANOPY_MCP_HOST       bind host for the network transports (default 127.0.0.1)
  CANOPY_MCP_PORT       bind port for the network transports (default 8765)
  CANOPY_MCP_PATH       URL path for the network transports (default /sse for sse, /mcp otherwise)

Locally the plugin launches this over stdio. In production / cloud Claude sessions, run it
as a long-lived service with CANOPY_MCP_TRANSPORT=sse and point the session at the SSE URL.
"""

from __future__ import annotations

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


def main() -> None:
    transport = os.environ.get("CANOPY_MCP_TRANSPORT", "stdio").lower()
    if transport == "stdio":
        mcp.run()
        return
    host = os.environ.get("CANOPY_MCP_HOST", "127.0.0.1")
    port = int(os.environ.get("CANOPY_MCP_PORT", "8765"))
    default_path = "/sse" if transport == "sse" else "/mcp"
    path = os.environ.get("CANOPY_MCP_PATH", default_path)
    mcp.run(transport=transport, host=host, port=port, path=path)


if __name__ == "__main__":
    main()
