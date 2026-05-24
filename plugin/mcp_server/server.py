"""Canopy MCP server (FastMCP).

A thin, curated layer over the canopy FastAPI backend — one tool per architect
intent, not a 1:1 mirror of REST routes. Runs over stdio when launched by the
Claude plugin. Configure via CANOPY_API_BASE_URL / CANOPY_API_TOKEN.
"""

from __future__ import annotations

import pathlib
import sys

# Make sibling modules importable when run as a script (python server.py).
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from fastmcp import FastMCP  # noqa: E402

from client import CanopyClient  # noqa: E402
from tools import (  # noqa: E402
    architecture,
    connectors,
    drafts,
    metadata,
    planning,
    projects,
    scenarios,
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


if __name__ == "__main__":
    mcp.run()
