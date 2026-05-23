"""Jira Cloud connector (deep).

Jira is the source of truth for epics/stories and their status. Canopy syncs
*from* Jira and never writes ticket status back. Reads use the enhanced JQL
search endpoint (POST /rest/api/3/search/jql, cursor pagination) plus the Agile
API for sprints. Status-transition history comes from the issue changelog. All
requests are rate-limit-aware (Retry-After + backoff). Sync is idempotent via
ExternalRef.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
from sqlmodel import select

from app.connectors.base import Connector, SyncResult, register
from app.connectors.http import request_with_retry
from app.models.base import Provider, TaskType
from app.models.integration import ExternalRef
from app.models.project import Task, TaskStatusHistory
from app.services import mapping

_FIELDS = ["summary", "status", "issuetype", "parent", "updated"]
_EPIC_TYPES = {"Epic"}


@register(Provider.jira)
class JiraConnector(Connector):
    @property
    def base_url(self) -> str:
        return str(self.config["base_url"]).rstrip("/")

    @property
    def canopy_project_id(self) -> int:
        return int(self.config["project_id"])

    @property
    def jira_project_key(self) -> str:
        return str(self.config["jira_project_key"])

    @property
    def _is_oauth(self) -> bool:
        return (
            self.config.get("auth_type") == "oauth"
            or self.connection.encrypted_refresh_token is not None
        )

    def _client(self) -> httpx.AsyncClient:
        token = self.access_token() or ""
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self._is_oauth:
            # OAuth 3LO: Bearer token against https://api.atlassian.com/ex/jira/{cloudId}.
            headers["Authorization"] = f"Bearer {token}"
            return httpx.AsyncClient(base_url=self.base_url, headers=headers, timeout=30.0)
        # API token: HTTP Basic (email:token) against the site base URL.
        return httpx.AsyncClient(
            base_url=self.base_url,
            auth=httpx.BasicAuth(self.config.get("email", ""), token),
            headers=headers,
            timeout=30.0,
        )

    # --- issue search (enhanced JQL, cursor pagination) ---
    async def _search(self, client: httpx.AsyncClient, jql: str) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        next_token: str | None = None
        while True:
            body: dict[str, Any] = {"jql": jql, "fields": _FIELDS, "maxResults": 100}
            if next_token:
                body["nextPageToken"] = next_token
            resp = await request_with_retry(client, "POST", "/rest/api/3/search/jql", json=body)
            data: dict[str, Any] = resp.json()
            issues.extend(data.get("issues", []))
            next_token = data.get("nextPageToken")
            if data.get("isLast", True) or not next_token:
                break
        return issues

    async def _upsert_issue(self, issue: dict[str, Any]) -> tuple[str, str | None, str]:
        """Upsert one Jira issue as a canopy Task. Returns (action, parent_external_id, ext_id)."""
        ext_id = issue["id"]
        key = issue["key"]
        fields = issue.get("fields", {})
        summary = fields.get("summary") or key
        status = (fields.get("status") or {}).get("name")
        issuetype = (fields.get("issuetype") or {}).get("name", "")
        updated = fields.get("updated")
        parent = fields.get("parent")
        parent_ext_id = parent.get("id") if parent else None

        ref = await mapping.get_ref(self.session, Provider.jira, ext_id, "task")
        if ref is not None and not mapping.is_stale(ref, updated):
            return "skipped", parent_ext_id, ext_id

        task_type = TaskType.summary if issuetype in _EPIC_TYPES else TaskType.task
        task: Task | None = None
        if ref is not None:
            task = await self.session.get(Task, ref.entity_id)
        if task is None:  # new issue, or dangling ref — create
            task = Task(project_id=self.canopy_project_id, name=summary, type=task_type)
            self.session.add(task)
            await self.session.flush()
            action = "created" if ref is None else "updated"
        else:
            action = "updated"
        task.name = summary
        task.status = status
        task.type = task_type
        await self.session.flush()
        assert task.id is not None  # guaranteed after flush

        await mapping.upsert_ref(
            self.session,
            provider=Provider.jira,
            external_id=ext_id,
            entity_type="task",
            entity_id=task.id,
            external_key=key,
            remote_updated=updated,
        )
        return action, parent_ext_id, ext_id

    async def _wire_parents(self, parent_links: list[tuple[str, str]]) -> None:
        """Second pass: set Task.parent_id once every epic has an ExternalRef."""
        for child_ext_id, parent_ext_id in parent_links:
            child_ref = await mapping.get_ref(self.session, Provider.jira, child_ext_id, "task")
            parent_ref = await mapping.get_ref(self.session, Provider.jira, parent_ext_id, "task")
            if child_ref and parent_ref:
                child = await self.session.get(Task, child_ref.entity_id)
                if child and child.parent_id != parent_ref.entity_id:
                    child.parent_id = parent_ref.entity_id

    async def _run(self, jql: str) -> SyncResult:
        result = SyncResult(provider="jira")
        max_updated: str | None = self.connection.watermark
        parent_links: list[tuple[str, str]] = []
        async with await self.open_client() as client:
            issues = await self._search(client, jql)
        for issue in issues:
            action, parent_ext_id, ext_id = await self._upsert_issue(issue)
            setattr(result, action, getattr(result, action) + 1)
            if parent_ext_id:
                parent_links.append((ext_id, parent_ext_id))
            updated = issue.get("fields", {}).get("updated")
            if updated and (max_updated is None or updated > max_updated):
                max_updated = updated
        await self._wire_parents(parent_links)
        result.watermark = self._to_jql_time(max_updated)
        self.connection.watermark = result.watermark
        await self.session.commit()
        return result

    @staticmethod
    def _to_jql_time(iso_ts: str | None) -> str | None:
        """Convert Jira ISO `updated` to a JQL-comparable 'yyyy-MM-dd HH:mm' string."""
        if not iso_ts:
            return None
        try:
            cleaned = iso_ts.replace("Z", "+0000")
            dt = datetime.strptime(cleaned[:19], "%Y-%m-%dT%H:%M:%S")
            return dt.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            return None

    @staticmethod
    def _parse_dt(iso_ts: str | None) -> datetime | None:
        if not iso_ts:
            return None
        try:
            return datetime.strptime(iso_ts[:19], "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            return None

    async def full_sync(self) -> SyncResult:
        result = await self._run(f'project = "{self.jira_project_key}" ORDER BY updated ASC')
        sprint_result = await self.sync_active_sprints()
        return result.merge(sprint_result)

    async def incremental_sync(self, since: str | None = None) -> SyncResult:
        watermark = since or self.connection.watermark
        jql = f'project = "{self.jira_project_key}"'
        if watermark:
            jql += f' AND updated >= "{watermark}"'
        jql += " ORDER BY updated ASC"
        result = await self._run(jql)
        sprint_result = await self.sync_active_sprints()
        return result.merge(sprint_result)

    async def handle_webhook(self, payload: dict[str, Any]) -> SyncResult:
        issue = payload.get("issue")
        result = SyncResult(provider="jira")
        if not issue:
            return result
        action, parent_ext_id, ext_id = await self._upsert_issue(issue)
        setattr(result, action, getattr(result, action) + 1)
        if parent_ext_id:
            await self._wire_parents([(ext_id, parent_ext_id)])
        await self.session.commit()
        return result

    # --- Agile API: boards & sprints ---
    async def list_boards(self) -> list[dict[str, Any]]:
        async with await self.open_client() as client:
            resp = await request_with_retry(
                client,
                "GET",
                "/rest/agile/1.0/board",
                params={"projectKeyOrId": self.jira_project_key},
            )
            data: dict[str, Any] = resp.json()
        return list(data.get("values", []))

    async def list_sprints(self, board_id: int, state: str = "active") -> list[dict[str, Any]]:
        async with await self.open_client() as client:
            resp = await request_with_retry(
                client, "GET", f"/rest/agile/1.0/board/{board_id}/sprint", params={"state": state}
            )
            data: dict[str, Any] = resp.json()
        return list(data.get("values", []))

    async def _sprint_issues(
        self, client: httpx.AsyncClient, sprint_id: int
    ) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        start_at = 0
        while True:
            resp = await request_with_retry(
                client,
                "GET",
                f"/rest/agile/1.0/sprint/{sprint_id}/issue",
                params={"fields": "summary", "startAt": start_at, "maxResults": 50},
            )
            data: dict[str, Any] = resp.json()
            page = data.get("issues", [])
            issues.extend(page)
            start_at += len(page)
            if start_at >= data.get("total", 0) or not page:
                break
        return issues

    async def sync_active_sprints(self) -> SyncResult:
        """Tag tasks with their active Jira sprint name (no-op without a board_id config)."""
        result = SyncResult(provider="jira")
        board_id = self.config.get("board_id")
        if not board_id:
            return result
        sprints = await self.list_sprints(int(board_id), state="active")
        async with await self.open_client() as client:
            for sprint in sprints:
                sprint_name = sprint.get("name")
                for issue in await self._sprint_issues(client, int(sprint["id"])):
                    ref = await mapping.get_ref(self.session, Provider.jira, issue["id"], "task")
                    if ref is None:
                        continue
                    task = await self.session.get(Task, ref.entity_id)
                    if task is not None and task.sprint != sprint_name:
                        task.sprint = sprint_name
                        result.updated += 1
        await self.session.commit()
        return result

    # --- status history (issue changelog) ---
    @staticmethod
    def _parse_status_history(histories: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Extract status transitions from raw changelog `values`."""
        transitions: list[dict[str, Any]] = []
        for history in histories:
            created = history.get("created")
            author = (history.get("author") or {}).get("displayName")
            for item in history.get("items", []):
                if item.get("field") == "status":
                    transitions.append(
                        {
                            "from_status": item.get("fromString"),
                            "to_status": item.get("toString"),
                            "changed_at": created,
                            "author": author,
                        }
                    )
        return transitions

    async def sync_status_history(self, issue_key: str) -> int:
        """Pull the issue changelog and persist new status transitions. Returns count added."""
        ref = await self._ref_by_key(issue_key)
        if ref is None:
            return 0
        histories: list[dict[str, Any]] = []
        start_at = 0
        async with await self.open_client() as client:
            while True:
                resp = await request_with_retry(
                    client,
                    "GET",
                    f"/rest/api/3/issue/{issue_key}/changelog",
                    params={"startAt": start_at, "maxResults": 100},
                )
                data: dict[str, Any] = resp.json()
                page = data.get("values", [])
                histories.extend(page)
                start_at += len(page)
                if data.get("isLast", True) or not page:
                    break

        added = 0
        for transition in self._parse_status_history(histories):
            changed_at = self._parse_dt(transition["changed_at"])
            if changed_at is None:
                continue
            if await self._has_history(ref.entity_id, changed_at, transition["to_status"]):
                continue
            self.session.add(
                TaskStatusHistory(
                    task_id=ref.entity_id,
                    from_status=transition["from_status"],
                    to_status=transition["to_status"],
                    changed_at=changed_at,
                    author=transition["author"],
                )
            )
            added += 1
        await self.session.commit()
        return added

    async def _ref_by_key(self, issue_key: str) -> ExternalRef | None:
        result = await self.session.execute(
            select(ExternalRef).where(
                ExternalRef.provider == Provider.jira, ExternalRef.external_key == issue_key
            )
        )
        return result.scalar_one_or_none()

    async def _has_history(self, task_id: int, changed_at: datetime, to_status: str | None) -> bool:
        result = await self.session.execute(
            select(TaskStatusHistory).where(
                TaskStatusHistory.task_id == task_id,
                TaskStatusHistory.changed_at == changed_at,
                TaskStatusHistory.to_status == to_status,
            )
        )
        return result.scalar_one_or_none() is not None
