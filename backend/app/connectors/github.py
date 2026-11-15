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
from app.services import ingest, pr_signals
from app.services.workflow import parse_remote_time

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
        async with await self.open_client() as client:
            resp = await request_with_retry(
                client, "GET", f"/repos/{self.owner}/{self.repo}/contents/{path}"
            )
            data: dict[str, Any] = resp.json()
        if data.get("encoding") == "base64":
            return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        return str(data.get("content", ""))

    async def list_pull_requests(self, state: str = "open") -> list[dict[str, Any]]:
        async with await self.open_client() as client:
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
        async with await self.open_client() as client:
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
        async with await self.open_client() as client:
            await request_with_retry(client, "GET", f"/repos/{self.owner}/{self.repo}")
        return SyncResult(provider="github")

    async def incremental_sync(self, since: str | None = None) -> SyncResult:
        return SyncResult(provider="github")

    async def _upsert_pull_request(self, repo: str, pr: dict[str, Any]) -> str:
        """Upsert a PullRequest cache row from a webhook `pull_request`; returns the action.
        Delegates to the shared cache upsert so the webhook and MCP/file ingest stay consistent."""
        head = pr.get("head") or {}
        return await ingest.upsert_pull_request(
            self.session,
            repo=repo,
            number=pr["number"],
            title=pr.get("title", ""),
            state=pr.get("state", "open"),
            url=pr.get("html_url"),
            author=(pr.get("user") or {}).get("login"),
            updated=pr.get("updated_at"),
            branch=head.get("ref"),
            signals=ingest.PullRequestSignals(
                draft=pr.get("draft"),
                merged=pr.get("merged"),
                merged_at=parse_remote_time(pr.get("merged_at")),
                merged_by=(pr.get("merged_by") or {}).get("login"),
                head_sha=head.get("sha"),
                additions=pr.get("additions"),
                deletions=pr.get("deletions"),
                changed_files=pr.get("changed_files"),
            ),
        )

    async def handle_webhook(self, payload: dict[str, Any]) -> SyncResult:
        """Handle a GitHub webhook (the receiver passes the `X-GitHub-Event` name as
        `_github_event`). Any event carrying a `pull_request` upserts the PR cache; a
        `pull_request_review` also records that reviewer's verdict; `check_suite`, `check_run`
        and `status` update the check state of the PRs whose current head they report on
        (docs/AGENT_EXECUTION.md §11.3). Nothing here moves a task's status."""
        result = SyncResult(provider="github")
        event = str(payload.get("_github_event") or "")
        repo = (payload.get("repository") or {}).get("full_name", self.full_name)
        pr = payload.get("pull_request")
        if pr:
            action = await self._upsert_pull_request(repo, pr)
            setattr(result, action, getattr(result, action) + 1)
            review = payload.get("review")
            if event == "pull_request_review" and isinstance(review, dict):
                row = await ingest.find_pull_request(self.session, repo, int(pr["number"]))
                if row is not None:
                    self._record_review(row, review)
        elif event in ("check_suite", "check_run", "status"):
            result.updated += await self._record_check(repo, event, payload)
        if result.created or result.updated:
            await self.session.commit()
        return result

    @staticmethod
    def _record_review(row: PullRequest, review: dict[str, Any]) -> None:
        row.reviews = pr_signals.record_review(row.reviews or [], review)
        row.approved_by = pr_signals.approvals_at_head(row.reviews, row.head_sha)
        row.review_decision = pr_signals.review_decision(row.reviews, row.head_sha)

    async def _record_check(self, repo: str, event: str, payload: dict[str, Any]) -> int:
        """Record one check suite / check run / commit status on the PRs at that head."""
        if event == "status":
            head_sha = str(payload.get("sha") or "")
            key = f"status:{payload.get('context') or 'default'}"
            state = pr_signals.normalize_check(payload.get("state"), None)
            numbers: list[int] = []
        else:
            body = payload.get(event) or {}
            head_sha = str(body.get("head_sha") or "")
            name = (
                (body.get("app") or {}).get("slug") or body.get("id")
                if event == "check_suite"
                else body.get("name")
            )
            key = f"{'suite' if event == 'check_suite' else 'run'}:{name or 'default'}"
            state = pr_signals.normalize_check(body.get("status"), body.get("conclusion"))
            numbers = [
                int(p["number"]) for p in body.get("pull_requests") or [] if p.get("number")
            ]
        if not head_sha:
            return 0
        rows: dict[int, PullRequest] = {}
        for row in (
            await self.session.execute(
                select(PullRequest).where(
                    PullRequest.repo == repo, PullRequest.head_sha == head_sha
                )
            )
        ).scalars().all():
            if row.id is not None:
                rows[row.id] = row
        for number in numbers:
            found = await ingest.find_pull_request(self.session, repo, number)
            if found is not None and found.id is not None:
                rows.setdefault(found.id, found)
        touched = 0
        for row in rows.values():
            if row.head_sha and row.head_sha != head_sha:
                continue  # a check on an older commit says nothing about the current head
            row.head_sha = head_sha
            checks = dict(row.checks or {})
            checks[key] = state
            row.checks = checks
            row.checks_state = pr_signals.roll_up_checks(checks)
            touched += 1
        return touched
