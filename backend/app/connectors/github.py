"""GitHub connector (thin).

GitHub is the source of truth for code and some architecture docs. For the slice
this provides on-demand reads — fetch architecture markdown, list PRs/milestones —
used by the API and MCP tools. Auth: PAT for dev (GitHub App is the production path).
"""

from __future__ import annotations

import base64

import httpx

from app.connectors.base import Connector, SyncResult, register
from app.models.base import Provider

_API = "https://api.github.com"


@register(Provider.github)
class GitHubConnector(Connector):
    @property
    def owner(self) -> str:
        return str(self.config["owner"])

    @property
    def repo(self) -> str:
        return str(self.config["repo"])

    def _client(self) -> httpx.AsyncClient:
        token = self.access_token() or ""
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return httpx.AsyncClient(base_url=_API, headers=headers, timeout=30.0)

    async def read_file(self, path: str) -> str:
        """Return the decoded text of a file (e.g. an architecture markdown doc)."""
        async with self._client() as client:
            resp = await client.get(f"/repos/{self.owner}/{self.repo}/contents/{path}")
            resp.raise_for_status()
            data = resp.json()
        if data.get("encoding") == "base64":
            return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        return str(data.get("content", ""))

    async def list_pull_requests(self, state: str = "open") -> list[dict]:
        async with self._client() as client:
            resp = await client.get(
                f"/repos/{self.owner}/{self.repo}/pulls", params={"state": state}
            )
            resp.raise_for_status()
            pulls = resp.json()
        return [
            {
                "number": p["number"],
                "title": p["title"],
                "url": p["html_url"],
                "state": p["state"],
                "user": (p.get("user") or {}).get("login"),
            }
            for p in pulls
        ]

    async def list_milestones(self, state: str = "open") -> list[dict]:
        async with self._client() as client:
            resp = await client.get(
                f"/repos/{self.owner}/{self.repo}/milestones", params={"state": state}
            )
            resp.raise_for_status()
            data = resp.json()
        return [
            {"number": m["number"], "title": m["title"], "due_on": m.get("due_on")}
            for m in data
        ]

    async def full_sync(self) -> SyncResult:
        # No mirrored entities by default; reads are on-demand. Verify connectivity.
        async with self._client() as client:
            resp = await client.get(f"/repos/{self.owner}/{self.repo}")
            resp.raise_for_status()
        return SyncResult(provider="github")

    async def incremental_sync(self, since: str | None = None) -> SyncResult:
        return SyncResult(provider="github")
