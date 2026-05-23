"""Jira Cloud connector (deep).

Jira is the source of truth for epics/stories and their status. Canopy syncs
*from* Jira and never writes ticket status back. Reads use the enhanced JQL
search endpoint (POST /rest/api/3/search/jql, cursor pagination). Epics map to
summary tasks (phases); stories/tasks/bugs map to leaf tasks parented under
their epic. Sync is idempotent via ExternalRef.
"""

from __future__ import annotations

from datetime import datetime

import httpx

from app.connectors.base import Connector, SyncResult, register
from app.models.base import Provider, TaskType
from app.models.project import Task
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

    def _client(self) -> httpx.AsyncClient:
        email = self.config.get("email", "")
        token = self.access_token() or ""
        return httpx.AsyncClient(
            base_url=self.base_url,
            auth=httpx.BasicAuth(email, token),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            timeout=30.0,
        )

    async def _search(self, client: httpx.AsyncClient, jql: str) -> list[dict]:
        """Page through the enhanced JQL endpoint and return all issues."""
        issues: list[dict] = []
        next_token: str | None = None
        while True:
            body: dict = {"jql": jql, "fields": _FIELDS, "maxResults": 100}
            if next_token:
                body["nextPageToken"] = next_token
            resp = await client.post("/rest/api/3/search/jql", json=body)
            resp.raise_for_status()
            data = resp.json()
            issues.extend(data.get("issues", []))
            next_token = data.get("nextPageToken")
            if data.get("isLast", True) or not next_token:
                break
        return issues

    async def _upsert_issue(self, issue: dict) -> tuple[str, str | None, str]:
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
        async with self._client() as client:
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

    async def full_sync(self) -> SyncResult:
        return await self._run(f'project = "{self.jira_project_key}" ORDER BY updated ASC')

    async def incremental_sync(self, since: str | None = None) -> SyncResult:
        watermark = since or self.connection.watermark
        jql = f'project = "{self.jira_project_key}"'
        if watermark:
            jql += f' AND updated >= "{watermark}"'
        jql += " ORDER BY updated ASC"
        return await self._run(jql)

    async def handle_webhook(self, payload: dict) -> SyncResult:
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
