"""Jira Cloud connector (deep).

Jira is the source of truth for epics/stories and their status. Canopy syncs
*from* Jira and never writes ticket **status** back. Reads use the enhanced JQL
search endpoint (POST /rest/api/3/search/jql, cursor pagination) plus the Agile
API for sprints. Status-transition history comes from the issue changelog.

As a deliberate, scoped exception, canopy can **create and update ticket content**
(summary, description, story points) from an architect-reviewed draft plan via
`create_issue` / `update_issue` — but status remains Jira-owned and is never pushed.
All requests are rate-limit-aware (Retry-After + backoff). Sync is idempotent via
ExternalRef.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx
from sqlmodel import select

from app.connectors.base import Connector, SyncResult, register
from app.connectors.http import request_with_retry
from app.models.base import Provider, TaskType
from app.models.integration import ExternalRef
from app.models.project import Project, Task, TaskStatusHistory
from app.services import ingest, mapping

_FIELDS = ["summary", "status", "issuetype", "parent", "updated", "assignee"]
_EPIC_TYPES = {"Epic"}
_CHILD_BATCH = 50  # max parent keys per `parent in (...)` JQL page


@dataclass
class LinkMapResult:
    """Outcome of mapping a linked Jira subtree onto canopy entities (see `JiraLink`)."""

    tasks_created: int = 0
    tasks_updated: int = 0
    projects_created: int = 0
    projects_linked: int = 0
    skipped: int = 0
    created_project_ids: list[int] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


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

    async def _upsert_issue(
        self, issue: dict[str, Any], *, project_id: int | None = None, force_leaf: bool = False
    ) -> tuple[str, str | None, str]:
        """Upsert one Jira issue as a canopy Task. Returns (action, parent_external_id, ext_id).

        `project_id` overrides the connection's configured project (used when linking a ticket
        into a specific target project). `force_leaf` keeps the task a leaf even for an epic
        issue type (used when an epic is mapped to a Project elsewhere, not a summary task).
        """
        pid = project_id if project_id is not None else self.canopy_project_id
        ext_id = issue["id"]
        key = issue["key"]
        fields = issue.get("fields", {})
        summary = fields.get("summary") or key
        status = (fields.get("status") or {}).get("name")
        issuetype = (fields.get("issuetype") or {}).get("name", "")
        updated = fields.get("updated")
        parent = fields.get("parent")
        parent_ext_id = parent.get("id") if parent else None
        assignee = fields.get("assignee") or {}

        # Shared upsert core (also used by MCP ingest) keeps the two paths from drifting.
        action, _ = await ingest.upsert_task_from_external(
            self.session,
            project_id=pid,
            provider=Provider.jira,
            external_id=ext_id,
            external_key=key,
            summary=summary,
            status=status,
            is_epic=issuetype in self._epic_type_names(),
            updated=updated,
            force_leaf=force_leaf,
            assignee_account_id=assignee.get("accountId"),
            assignee_name=assignee.get("displayName"),
        )
        return action, parent_ext_id, ext_id

    async def _wire_parents(self, parent_links: list[tuple[str, str]]) -> None:
        """Second pass: set Task.parent_id once every epic has an ExternalRef."""
        await ingest.wire_parents(self.session, Provider.jira, parent_links)

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
        if result.created:
            await self._auto_replan()
        return result

    async def _auto_replan(self, project_id: int | None = None) -> None:
        """Reschedule a canopy project after new tasks were imported (best-effort)."""
        import contextlib

        from app.services.planner import reschedule_project
        from app.services.scheduling import CycleError

        pid = project_id if project_id is not None else self.canopy_project_id
        # Leave dates as-is if the imported graph happens to contain a cycle.
        with contextlib.suppress(CycleError):
            await reschedule_project(self.session, pid)

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

    # --- ticket linking: map a chosen ticket + its descendant subtree into canopy ---
    def _epic_type_names(self) -> set[str]:
        """Issue-type names treated as epics (the configured `epic_issue_type`, plus `Epic`)."""
        names = set(_EPIC_TYPES)
        configured = self.config.get("epic_issue_type")
        if configured:
            names.add(str(configured))
        return names

    def _is_epic_issue(self, issue: dict[str, Any]) -> bool:
        name = (issue.get("fields", {}).get("issuetype") or {}).get("name", "")
        return name in self._epic_type_names()

    def _nearest_epic_ancestor(
        self, issue: dict[str, Any], by_id: dict[str, dict[str, Any]]
    ) -> str | None:
        """Walk up the parent chain (within the imported set) to the closest epic, if any."""
        seen: set[str] = set()
        parent = issue.get("fields", {}).get("parent")
        cur: str | None = str(parent["id"]) if parent else None
        while cur is not None and cur in by_id and cur not in seen:
            seen.add(cur)
            node = by_id[cur]
            if self._is_epic_issue(node):
                return cur
            parent = node.get("fields", {}).get("parent")
            cur = str(parent["id"]) if parent else None
        return None

    async def get_issue(self, key_or_id: str) -> dict[str, Any] | None:
        """Fetch a single issue (the link root). Returns None if it doesn't exist (404)."""
        async with await self.open_client() as client:
            try:
                resp = await request_with_retry(
                    client,
                    "GET",
                    f"/rest/api/3/issue/{key_or_id}",
                    params={"fields": ",".join(_FIELDS)},
                )
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == httpx.codes.NOT_FOUND:
                    return None
                raise
        data: dict[str, Any] = resp.json()
        return data

    async def fetch_descendant_tree(self, root_key: str) -> list[dict[str, Any]]:
        """The root issue plus every descendant (BFS over Jira `parent` links). Deduped."""
        root = await self.get_issue(root_key)
        if root is None:
            return []
        issues: dict[str, dict[str, Any]] = {str(root["id"]): root}
        frontier = [str(root["key"])]
        async with await self.open_client() as client:
            while frontier:
                next_frontier: list[str] = []
                for start in range(0, len(frontier), _CHILD_BATCH):
                    batch = frontier[start : start + _CHILD_BATCH]
                    keys = ", ".join(f'"{k}"' for k in batch)
                    for child in await self._search(client, f"parent in ({keys})"):
                        cid = str(child["id"])
                        if cid not in issues:
                            issues[cid] = child
                            next_frontier.append(str(child["key"]))
                frontier = next_frontier
        return list(issues.values())

    async def _unique_project_key(self, base: str) -> str:
        """A project `key` (unique slug) derived from a Jira key, disambiguated on collision."""
        candidate, n = base, 1
        while True:
            existing = (
                await self.session.execute(select(Project).where(Project.key == candidate))
            ).scalar_one_or_none()
            if existing is None:
                return candidate
            n += 1
            candidate = f"{base}-{n}"

    async def _upsert_epic_project(
        self, issue: dict[str, Any], initiative_id: int
    ) -> tuple[int, str]:
        """Map a Jira epic onto a canopy Project under the initiative. Returns (id, action)."""
        ext_id = str(issue["id"])
        key = str(issue["key"])
        summary = issue.get("fields", {}).get("summary") or key
        updated = issue.get("fields", {}).get("updated")

        ref = await mapping.get_ref(self.session, Provider.jira, ext_id, "project")
        project: Project | None = None
        if ref is not None:
            project = await self.session.get(Project, ref.entity_id)
        if project is None:  # new epic, or dangling ref — create the project
            project = Project(
                key=await self._unique_project_key(key), name=summary, initiative_id=initiative_id
            )
            self.session.add(project)
            action = "created"
        else:
            project.name = summary
            if project.initiative_id is None:
                project.initiative_id = initiative_id
            action = "linked"
        await self.session.flush()
        assert project.id is not None
        await mapping.upsert_ref(
            self.session,
            provider=Provider.jira,
            external_id=ext_id,
            entity_type="project",
            entity_id=project.id,
            external_key=key,
            remote_updated=updated,
        )
        return project.id, action

    async def map_subtree_into_project(
        self, issues: list[dict[str, Any]], project_id: int
    ) -> LinkMapResult:
        """Map every issue in the subtree onto a Task in `project_id` (epics → summary tasks)."""
        result = LinkMapResult()
        imported = {str(i["id"]) for i in issues}
        parent_links: list[tuple[str, str]] = []
        for issue in issues:
            action, parent_ext_id, ext_id = await self._upsert_issue(issue, project_id=project_id)
            if action == "created":
                result.tasks_created += 1
            elif action == "updated":
                result.tasks_updated += 1
            else:
                result.skipped += 1
            if parent_ext_id and parent_ext_id in imported:
                parent_links.append((ext_id, parent_ext_id))
        await self._wire_parents(parent_links)
        await self.session.commit()
        if result.tasks_created:
            await self._auto_replan(project_id)
        return result

    async def map_subtree_into_initiative(
        self, issues: list[dict[str, Any]], initiative_id: int
    ) -> LinkMapResult:
        """Map epics → Projects under the initiative; each non-epic → a Task in its epic project."""
        result = LinkMapResult()
        by_id = {str(i["id"]): i for i in issues}

        epic_project: dict[str, int] = {}
        for issue in issues:
            if self._is_epic_issue(issue):
                project_id, action = await self._upsert_epic_project(issue, initiative_id)
                epic_project[str(issue["id"])] = project_id
                if action == "created":
                    result.projects_created += 1
                    result.created_project_ids.append(project_id)
                else:
                    result.projects_linked += 1

        parent_links: list[tuple[str, str]] = []
        for issue in issues:
            if self._is_epic_issue(issue):
                continue
            epic_id = self._nearest_epic_ancestor(issue, by_id)
            if epic_id is None:  # the initiative-level anchor, or a story with no epic ancestor
                result.skipped += 1
                result.notes.append(f"{issue['key']}: no epic ancestor — not mapped")
                continue
            project_id = epic_project[epic_id]
            action, parent_ext_id, ext_id = await self._upsert_issue(
                issue, project_id=project_id, force_leaf=True
            )
            if action == "created":
                result.tasks_created += 1
            elif action == "updated":
                result.tasks_updated += 1
            else:
                result.skipped += 1
            # Wire a parent only when it's a non-epic in the same project (e.g. sub-task → story);
            # a task whose parent is the epic stays top-level (the epic is the project itself).
            if parent_ext_id and parent_ext_id in by_id and not self._is_epic_issue(
                by_id[parent_ext_id]
            ):
                parent_links.append((ext_id, parent_ext_id))
        await self._wire_parents(parent_links)
        await self.session.commit()
        if result.tasks_created:
            for pid in set(epic_project.values()):
                await self._auto_replan(pid)
        return result

    # --- writing issues (content only — status stays Jira-owned, never pushed) ---
    @staticmethod
    def _adf(text: str) -> dict[str, Any]:
        """Wrap plain text in a minimal Atlassian Document Format doc (API v3 needs ADF)."""
        return {
            "type": "doc",
            "version": 1,
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
        }

    @property
    def _story_point_field(self) -> str | None:
        """Jira custom field id holding story points (e.g. 'customfield_10016'), per config."""
        field = self.config.get("story_point_field")
        return str(field) if field else None

    def issue_type_for(self, task_type: TaskType) -> str:
        """Map a canopy task type to a Jira issue-type name (overridable via config)."""
        if task_type == TaskType.summary:
            return str(self.config.get("epic_issue_type", "Epic"))
        return str(self.config.get("story_issue_type", "Story"))

    def _build_create_fields(
        self,
        *,
        summary: str,
        description: str | None,
        issue_type: str,
        story_points: float | None,
        parent_key: str | None,
    ) -> dict[str, Any]:
        fields: dict[str, Any] = {
            "project": {"key": self.jira_project_key},
            "summary": summary,
            "issuetype": {"name": issue_type},
        }
        if description:
            fields["description"] = self._adf(description)
        if parent_key:
            fields["parent"] = {"key": parent_key}
        story_field = self._story_point_field
        if story_field and story_points is not None:
            fields[story_field] = story_points
        return fields

    async def create_issue(
        self,
        *,
        summary: str,
        issue_type: str,
        description: str | None = None,
        story_points: float | None = None,
        parent_key: str | None = None,
    ) -> dict[str, str]:
        """Create a Jira issue from plan content. Returns {'id', 'key'}. Never sets status."""
        fields = self._build_create_fields(
            summary=summary,
            description=description,
            issue_type=issue_type,
            story_points=story_points,
            parent_key=parent_key,
        )
        async with await self.open_client() as client:
            resp = await request_with_retry(
                client, "POST", "/rest/api/3/issue", json={"fields": fields}
            )
        data: dict[str, Any] = resp.json()
        return {"id": str(data["id"]), "key": str(data["key"])}

    async def update_issue(
        self,
        issue_id_or_key: str,
        *,
        summary: str | None = None,
        description: str | None = None,
        story_points: float | None = None,
    ) -> None:
        """Update an existing issue's content fields. Only provided fields change; status is
        never touched (it stays Jira-owned)."""
        fields: dict[str, Any] = {}
        if summary is not None:
            fields["summary"] = summary
        if description:
            fields["description"] = self._adf(description)
        story_field = self._story_point_field
        if story_field and story_points is not None:
            fields[story_field] = story_points
        if not fields:
            return
        async with await self.open_client() as client:
            await request_with_retry(
                client, "PUT", f"/rest/api/3/issue/{issue_id_or_key}", json={"fields": fields}
            )

    # --- document harvest: epic fields, the field registry, and remote links ---
    async def list_fields(self) -> dict[str, str]:
        """The Jira field registry as {field_id: human_name} — used to label custom fields
        (e.g. customfield_10042 → "Design Link") when proposing a doc field mapping."""
        async with await self.open_client() as client:
            resp = await request_with_retry(client, "GET", "/rest/api/3/field")
        out: dict[str, str] = {}
        for entry in resp.json():
            field_id = entry.get("id")
            if field_id:
                out[str(field_id)] = str(entry.get("name") or field_id)
        return out

    async def fetch_epics(
        self, *, limit: int | None = None, all_fields: bool = True
    ) -> list[dict[str, Any]]:
        """Epics in the configured project (newest first). `all_fields=True` pulls every
        field (needed to find doc links in custom fields / description)."""
        epic_types = ", ".join(f'"{name}"' for name in sorted(self._epic_type_names()))
        jql = (
            f'project = "{self.jira_project_key}" AND issuetype in ({epic_types}) '
            "ORDER BY updated DESC"
        )
        fields = ["*all"] if all_fields else _FIELDS
        issues: list[dict[str, Any]] = []
        next_token: str | None = None
        async with await self.open_client() as client:
            while True:
                page_size = min(limit, 100) if limit else 100
                body: dict[str, Any] = {"jql": jql, "fields": fields, "maxResults": page_size}
                if next_token:
                    body["nextPageToken"] = next_token
                resp = await request_with_retry(
                    client, "POST", "/rest/api/3/search/jql", json=body
                )
                data: dict[str, Any] = resp.json()
                issues.extend(data.get("issues", []))
                next_token = data.get("nextPageToken")
                if limit is not None and len(issues) >= limit:
                    return issues[:limit]
                if data.get("isLast", True) or not next_token:
                    break
        return issues

    async def fetch_remote_links(self, issue_key: str) -> list[dict[str, Any]]:
        """An issue's remote links (Confluence pages, web links). Returns [{url, title}]."""
        async with await self.open_client() as client:
            try:
                resp = await request_with_retry(
                    client, "GET", f"/rest/api/3/issue/{issue_key}/remotelink"
                )
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == httpx.codes.NOT_FOUND:
                    return []
                raise
        out: list[dict[str, Any]] = []
        for link in resp.json():
            obj = link.get("object") or {}
            url = obj.get("url")
            if url:
                out.append({"url": str(url), "title": obj.get("title")})
        return out

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
