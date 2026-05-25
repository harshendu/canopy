"""Connectors API — split into focused routers, aggregated onto one `router` that
`app/api/v1/__init__.py` mounts at `/connectors`:

- `connections` — connection lifecycle (list / create / delete)
- `sync`        — pull data in: direct sync + MCP-orchestrated ingest (issues / PRs / file)
- `oauth`       — OAuth 2.0 (3LO): authorize / connect-me / callback
- `reads`       — on-demand provider reads (Jira Agile + docs, GitHub, Drive)
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.connectors import connections, oauth, reads, sync

router = APIRouter()
router.include_router(connections.router)
router.include_router(sync.router)
router.include_router(oauth.router)
router.include_router(reads.router)
