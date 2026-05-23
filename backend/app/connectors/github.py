"""GitHub connector (thin).

GitHub is the source of truth for code and some architecture docs. Provides
on-demand reads (architecture markdown, PRs, milestones) and keeps a lightweight
PullRequest cache fresh via webhooks. Requests are rate-limit-aware. Auth: PAT
for dev (GitHub App is the production path).
"""

from __future__ import annotations

import base64
from typing import Any

import httpx
from sqlmodel import select

from app.connectors.base import Connector, SyncResult, register
from app.connectors.http import request_with_retry
from app.models.base import Provider
from app.models.integration import PullRequest

_API = "https://api.github.com"


@register(Provider.github)
class GitHubConnector(Connector):
    @property
    def owner(self) -> str:
        return str(self.config["owner"])

    @property
    def repo(self) -> str:
        return str(self.config["repo"])

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.repo}"

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
            resp = await request_with_retry(
                client, "GET", f"/repos/{self.owner}/{self.repo}/contents/{path}"
            )
            data: dict[str, Any] = resp.json()
        if data.get("encoding") == "base64":
            return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        return str(data.get("content", ""))

    async def list_pull_requests(self, state: str = "open") -> list[dict[str, Any]]:
        async with self._client() as client:
            resp = await request_with_retry(
                client, "GET", f"/repos/{self.owner}/{self.repo}/pulls", params={"state": state}
            )
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

    async def list_milestones(self, state: str = "open") -> list[dict[str, Any]]:
        async with self._client() as client:
            resp = await request_with_retry(
                client,
                "GET",
                f"/repos/{self.owner}/{self.repo}/milestones",
                params={"state": state},
            )
            data = resp.json()
        return [
            {"number": m["number"], "title": m["title"], "due_on": m.get("due_on")} for m in data
        ]

    async def full_sync(self) -> SyncResult:
        # No mirrored entities by default; reads are on-demand. Verify connectivity.
        async with self._client() as client:
            await request_with_retry(client, "GET", f"/repos/{self.owner}/{self.repo}")
        return SyncResult(provider="github")

    async def incremental_sync(self, since: str | None = None) -> SyncResult:
        return SyncResult(provider="github")

    async def _upsert_pull_request(self, repo: str, pr: dict[str, Any]) -> str:
        """Upsert a PullRequest cache row from a webhook `pull_request`; returns the action."""
        number = pr["number"]
        result = await self.session.execute(
            select(PullRequest).where(PullRequest.repo == repo, PullRequest.number == number)
        )
        existing = result.scalar_one_or_none()
        if existing is None:
            self.session.add(
                PullRequest(
                    repo=repo,
                    number=number,
                    title=pr.get("title", ""),
                    state=pr.get("state", "open"),
                    url=pr.get("html_url"),
                    author=(pr.get("user") or {}).get("login"),
                    remote_updated=pr.get("updated_at"),
                )
            )
            return "created"
        existing.title = pr.get("title", existing.title)
        existing.state = pr.get("state", existing.state)
        existing.url = pr.get("html_url")
        existing.author = (pr.get("user") or {}).get("login")
        existing.remote_updated = pr.get("updated_at")
        return "updated"

    async def handle_webhook(self, payload: dict[str, Any]) -> SyncResult:
        """Handle a GitHub `pull_request` event by upserting the PR cache."""
        result = SyncResult(provider="github")
        pr = payload.get("pull_request")
        repo = (payload.get("repository") or {}).get("full_name", self.full_name)
        if not pr:
            return result
        action = await self._upsert_pull_request(repo, pr)
        setattr(result, action, getattr(result, action) + 1)
        await self.session.commit()
        return result
