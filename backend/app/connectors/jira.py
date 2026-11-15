"""Jira Cloud as a work tracker (USER_FLOWS §J).

A `WorkTracker`: it fetches issues and normalizes them into `WorkItem`s (status + its Jira
status category, epic/sub-task kind, assignee, story points, sprint), lists the project's
statuses (the mirrored board's columns), replays the changelog, mirrors board sprints, and
writes ticket **content** (summary, description, story points, epic→story parent) from a
reviewed draft plan. Status is never written back: the interface has no transition method.
Everything canopy does with the data — upsert, parents, watermarks, history, sprints,
auto-replan — is the shared engine in `app/services/tracker_sync.py`.

Reads use the enhanced JQL search (POST /rest/api/3/search/jql, cursor pagination) and the
Agile API; all requests are rate-limit-aware (Retry-After + backoff). The epic doc-field
harvest (`list_fields`, `fetch_epics`, `fetch_remote_links`) is a Jira feature of the document
graph, not of work tracking, and stays here unchanged.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, ClassVar

import httpx
from pydantic import BaseModel

from app.connectors.base import EffectiveCredential
from app.connectors.http import request_with_retry
from app.connectors.tracker import WorkTracker, register_tracker
from app.models.base import Provider, TaskType
from app.services import workflow
from app.services.links import jira_browse_url
from app.services.tracker_types import (
    KIND_EPIC,
    KIND_ITEM,
    KIND_SUBITEM,
    Assignee,
    ItemDraft,
    ItemPage,
    ItemPatch,
    ItemRef,
    Iteration,
    Scope,
    StatusChange,
    StatusDef,
    TrackerCapabilities,
    WebhookEvent,
    WorkItem,
)

__all__ = ["JiraConnector"]

_FIELDS = ["summary", "status", "issuetype", "parent", "updated", "assignee"]
_EPIC_TYPES = {"Epic"}
_CHILD_BATCH = 50  # max parent keys per `parent in (...)` JQL page
_CLOSED_SPRINTS_KEPT = 6  # completed sprints mirrored (velocity history)
# Jira's status categories → canopy's. Jira has no "cancelled" category: a done-category status
# whose name says it was dropped ("Won't Do", "Cancelled") maps to cancelled.
_CATEGORY = {"new": "todo", "indeterminate": "in_progress", "done": "done"}
_SPRINT_STATE = {"future": "planned", "active": "active", "closed": "completed"}


class JiraConnectionConfig(BaseModel):
    """A Jira site and how to authenticate (credentials are entered separately)."""

    base_url: str  # https://your-site.atlassian.net (OAuth sets the api.atlassian.com base)
    email: str | None = None  # API-token auth (HTTP Basic email:token)
    auth_type: str | None = None  # "oauth" once connected through OAuth


class JiraScope(BaseModel):
    """Where in Jira a binding points."""

    project_key: str | None = None  # e.g. "SHOP"
    board_id: int | None = None  # mirror this board's sprints
    jql: str | None = None  # a saved query (scope_kind = query) instead of the whole project


@register_tracker(Provider.jira)
class JiraConnector(WorkTracker):
    label: ClassVar[str] = "Jira"
    capabilities: ClassVar[TrackerCapabilities] = TrackerCapabilities(
        direct_read=True,
        hierarchy=True,
        status_categories=True,
        status_history=True,
        iterations=True,
        webhooks=True,
        create_items=True,
        update_items=True,
        estimates=True,
        oauth=True,
        comments=True,
    )
    config_schema: ClassVar[type[BaseModel]] = JiraConnectionConfig
    scope_schema: ClassVar[type[BaseModel]] = JiraScope
    webhook_signature_header: ClassVar[str | None] = "X-Hub-Signature"
    scope_selector_keys: ClassVar[tuple[str, ...]] = ("project_key", "jql")

    @property
    def base_url(self) -> str:
        return str(self.config["base_url"]).rstrip("/")

    @property
    def jira_project_key(self) -> str:
        return str(self.config.get("jira_project_key") or self.config.get("project_key") or "")

    @property
    def connection_id(self) -> int | None:
        if isinstance(self.connection, EffectiveCredential):
            return self.connection._connection.id
        return self.connection.id

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

    # --------------------------------------------------------------------- #
    # Normalization
    # --------------------------------------------------------------------- #

    def _epic_type_names(self, scope: Scope | None = None) -> set[str]:
        """Issue-type names treated as epics: the binding's mapping, the connection's configured
        `epic_issue_type`, plus `Epic`."""
        names = set(_EPIC_TYPES)
        configured = self.config.get("epic_issue_type")
        if configured:
            names.add(str(configured))
        if scope is not None:
            names.update(str(n) for n in scope.mapping.get("epic_types") or [])
        return names

    def _estimate_field(self, scope: Scope | None = None) -> str | None:
        if scope is not None and scope.mapping.get("estimate_field"):
            return str(scope.mapping["estimate_field"])
        return self._story_point_field

    def _fields(self, scope: Scope | None = None) -> list[str]:
        estimate = self._estimate_field(scope)
        return [*_FIELDS, estimate] if estimate else list(_FIELDS)

    def normalize(self, issue: dict[str, Any], scope: Scope | None = None) -> WorkItem:
        """One Jira issue as a `WorkItem`."""
        fields = issue.get("fields") or {}
        status = fields.get("status") or {}
        status_name = status.get("name")
        category = _CATEGORY.get(str((status.get("statusCategory") or {}).get("key") or ""))
        if category == "done" and workflow.heuristic_category(status_name) == "cancelled":
            category = "cancelled"
        issuetype = fields.get("issuetype") or {}
        type_name = str(issuetype.get("name") or "")
        if type_name in self._epic_type_names(scope):
            kind = KIND_EPIC
        elif issuetype.get("subtask"):
            kind = KIND_SUBITEM
        else:
            kind = KIND_ITEM
        parent = fields.get("parent")
        assignee = fields.get("assignee") or {}
        estimate_field = self._estimate_field(scope)
        raw_estimate = fields.get(estimate_field) if estimate_field else None
        key = str(issue.get("key") or "") or None
        return WorkItem(
            external_id=str(issue["id"]),
            key=key,
            title=str(fields.get("summary") or key or issue["id"]),
            status_name=status_name,
            status_category=category,
            kind=kind,
            parent_external_id=str(parent["id"]) if parent and parent.get("id") else None,
            assignee=(
                Assignee(
                    account_id=assignee.get("accountId"),
                    name=assignee.get("displayName"),
                    email=assignee.get("emailAddress"),
                )
                if assignee
                else None
            ),
            estimate=float(raw_estimate) if isinstance(raw_estimate, int | float) else None,
            updated=fields.get("updated"),
            url=self.item_url(key) if key else None,
            raw_type=type_name or None,
        )

    @classmethod
    def browse_url(cls, config: Mapping[str, Any], key: str) -> str | None:
        return jira_browse_url(config.get("base_url"), key)

    # --------------------------------------------------------------------- #
    # WorkTracker: reads
    # --------------------------------------------------------------------- #

    async def _search(
        self, client: httpx.AsyncClient, jql: str, fields: list[str] | None = None
    ) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        next_token: str | None = None
        while True:
            body: dict[str, Any] = {"jql": jql, "fields": fields or _FIELDS, "maxResults": 100}
            if next_token:
                body["nextPageToken"] = next_token
            resp = await request_with_retry(client, "POST", "/rest/api/3/search/jql", json=body)
            data: dict[str, Any] = resp.json()
            issues.extend(data.get("issues", []))
            next_token = data.get("nextPageToken")
            if data.get("isLast", True) or not next_token:
                break
        return issues

    def _scope_jql(self, scope: Scope) -> str:
        if scope.get("jql"):
            return f"({scope.get('jql')})"
        key = scope.get("project_key") or self.jira_project_key
        return f'project = "{key}"'

    async def fetch_items(self, scope: Scope, since: str | None) -> ItemPage:
        jql = self._scope_jql(scope)
        if since:
            jql += f' AND updated >= "{since}"'
        jql += " ORDER BY updated ASC"
        async with await self.open_client() as client:
            issues = await self._search(client, jql, self._fields(scope))
        updated = [str(u) for i in issues if (u := (i.get("fields") or {}).get("updated"))]
        watermark = self._to_jql_time(max(updated)) if updated else None
        return ItemPage(
            items=[self.normalize(i, scope) for i in issues], watermark=watermark or since
        )

    async def fetch_item(self, scope: Scope, key: str) -> WorkItem | None:
        issue = await self.get_issue(key)
        return self.normalize(issue, scope) if issue is not None else None

    async def fetch_subtree(self, scope: Scope, root_key: str) -> list[WorkItem]:
        return [self.normalize(i, scope) for i in await self.fetch_descendant_tree(root_key)]

    async def list_statuses(self, scope: Scope) -> list[StatusDef]:
        """The project's statuses across its issue types, ordered by category then Jira's
        order (GET /rest/api/3/project/{key}/statuses)."""
        key = scope.get("project_key") or self.jira_project_key
        if not key:
            return []
        async with await self.open_client() as client:
            try:
                resp = await request_with_retry(
                    client, "GET", f"/rest/api/3/project/{key}/statuses"
                )
            except httpx.HTTPStatusError:
                return []
        data = resp.json()
        if not isinstance(data, list):
            return []
        seen: dict[str, StatusDef] = {}
        for issue_type in data:
            for status in (issue_type or {}).get("statuses") or []:
                name = status.get("name")
                if not name or name.casefold() in seen:
                    continue
                category = _CATEGORY.get(str((status.get("statusCategory") or {}).get("key")))
                if category is None:
                    continue
                if category == "done" and workflow.heuristic_category(name) == "cancelled":
                    category = "cancelled"
                seen[name.casefold()] = StatusDef(name=str(name), category=category)
        order = {"todo": 0, "in_progress": 1, "done": 2, "cancelled": 3}
        ranked = sorted(
            enumerate(seen.values()), key=lambda pair: (order.get(pair[1].category, 9), pair[0])
        )
        return [
            StatusDef(name=s.name, category=s.category, position=i)
            for i, (_, s) in enumerate(ranked)
        ]

    async def fetch_status_changes(self, scope: Scope, ref: ItemRef) -> list[StatusChange]:
        histories: list[dict[str, Any]] = []
        start_at = 0
        key = ref.key or ref.external_id
        async with await self.open_client() as client:
            while True:
                resp = await request_with_retry(
                    client,
                    "GET",
                    f"/rest/api/3/issue/{key}/changelog",
                    params={"startAt": start_at, "maxResults": 100},
                )
                data: dict[str, Any] = resp.json()
                page = data.get("values", [])
                histories.extend(page)
                start_at += len(page)
                if data.get("isLast", True) or not page:
                    break
        out: list[StatusChange] = []
        for transition in self._parse_status_history(histories):
            at = workflow.parse_remote_time(transition["changed_at"])
            if at is None:
                continue
            out.append(
                StatusChange(
                    to_status=transition["to_status"],
                    from_status=transition["from_status"],
                    at=at,
                    author=transition["author"],
                )
            )
        return out

    async def fetch_iterations(self, scope: Scope) -> list[Iteration]:
        """The board's active and future sprints plus its most recent closed ones."""
        board_id = scope.get("board_id") or self.config.get("board_id")
        if not board_id:
            return []
        sprints = await self.list_sprints(int(board_id), state="active,future,closed")
        by_id: dict[str, dict[str, Any]] = {}
        for sprint in sprints:
            by_id.setdefault(str(sprint["id"]), sprint)
        closed = sorted(
            (s for s in by_id.values() if s.get("state") == "closed"),
            key=lambda s: str(s.get("endDate") or ""),
        )[-_CLOSED_SPRINTS_KEPT:]
        keep = [s for s in by_id.values() if s.get("state") != "closed"] + closed
        out: list[Iteration] = []
        async with await self.open_client() as client:
            for sprint in keep:
                issues = await self._sprint_issues(client, int(sprint["id"]))
                start = workflow.parse_remote_time(sprint.get("startDate"))
                end = workflow.parse_remote_time(sprint.get("endDate"))
                out.append(
                    Iteration(
                        external_id=str(sprint["id"]),
                        name=str(sprint.get("name") or sprint["id"]),
                        state=_SPRINT_STATE.get(str(sprint.get("state")), "active"),
                        start=start.date() if start else None,
                        end=end.date() if end else None,
                        goal=sprint.get("goal") or None,
                        item_external_ids=tuple(str(i["id"]) for i in issues),
                    )
                )
        return out

    # --------------------------------------------------------------------- #
    # WorkTracker: content writes (never status)
    # --------------------------------------------------------------------- #

    async def create_item(self, scope: Scope, draft: ItemDraft) -> ItemRef:
        # A binding may point at another Jira project than the connection's default one; only
        # then is the project passed (keeping the pre-tracker call shape otherwise).
        extra: dict[str, str] = {}
        scope_key = str(scope.get("project_key") or "")
        if scope_key and scope_key != self.jira_project_key:
            extra["project_key"] = scope_key
        issue = await self._create_issue(
            summary=draft.title,
            issue_type=self._issue_type(draft.kind, scope),
            description=draft.description,
            story_points=draft.estimate,
            parent_key=draft.parent.key if draft.parent is not None else None,
            estimate_field=self._estimate_field(scope),
            **extra,
        )
        return ItemRef(external_id=issue["id"], key=issue["key"])

    async def update_item(self, scope: Scope, ref: ItemRef, patch: ItemPatch) -> None:
        await self._update_issue(
            ref.external_id,
            summary=patch.title,
            description=patch.description,
            story_points=patch.estimate,
            estimate_field=self._estimate_field(scope),
        )

    async def add_comment(self, scope: Scope, ref: ItemRef, body: str) -> None:
        async with await self.open_client() as client:
            await request_with_retry(
                client, "POST", f"/rest/api/3/issue/{ref.key or ref.external_id}/comment",
                json={"body": self._adf_blocks(body)},
            )

    # --------------------------------------------------------------------- #
    # Webhooks
    # --------------------------------------------------------------------- #

    @classmethod
    def webhook_scope_hint(cls, payload: dict[str, Any]) -> dict[str, Any]:
        key = str((payload.get("issue") or {}).get("key") or "")
        return {"project_key": key.split("-")[0]} if "-" in key else {}

    def parse_webhook(self, payload: dict[str, Any]) -> WebhookEvent | None:
        issue = payload.get("issue")
        if not issue or not issue.get("id"):
            return None
        return WebhookEvent(item=self.normalize(issue), scope_hint=self.webhook_scope_hint(payload))

    # --------------------------------------------------------------------- #
    # Helpers
    # --------------------------------------------------------------------- #

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

    async def get_issue(self, key_or_id: str) -> dict[str, Any] | None:
        """Fetch a single issue (the link root). Returns None if it doesn't exist (404)."""
        async with await self.open_client() as client:
            try:
                resp = await request_with_retry(
                    client,
                    "GET",
                    f"/rest/api/3/issue/{key_or_id}",
                    params={"fields": ",".join(self._fields())},
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
                    for child in await self._search(
                        client, f"parent in ({keys})", self._fields()
                    ):
                        cid = str(child["id"])
                        if cid not in issues:
                            issues[cid] = child
                            next_frontier.append(str(child["key"]))
                frontier = next_frontier
        return list(issues.values())

    # --- writing issues (content only — status stays Jira-owned, never pushed) ---
    @staticmethod
    def _adf(text: str) -> dict[str, Any]:
        """Wrap plain text in a minimal Atlassian Document Format doc (API v3 needs ADF)."""
        return {
            "type": "doc",
            "version": 1,
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
        }

    @staticmethod
    def _adf_blocks(text: str) -> dict[str, Any]:
        """Multi-line text as ADF: a paragraph per block, hard breaks between its lines."""
        paragraphs: list[dict[str, Any]] = []
        for block in [b for b in text.replace("\r\n", "\n").split("\n\n") if b.strip()]:
            content: list[dict[str, Any]] = []
            for i, line in enumerate(block.split("\n")):
                if i:
                    content.append({"type": "hardBreak"})
                if line:
                    content.append({"type": "text", "text": line})
            paragraphs.append({"type": "paragraph", "content": content})
        return {"type": "doc", "version": 1, "content": paragraphs or [
            {"type": "paragraph", "content": [{"type": "text", "text": text or " "}]}]}

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

    def _issue_type(self, kind: str, scope: Scope | None = None) -> str:
        """The issue type a new item is created as: the binding's mapping (its first epic type,
        or its item type), else the connection's configured type, else Jira's default."""
        mapping = scope.mapping if scope is not None else {}
        if kind == KIND_EPIC:
            epic_types = [str(t) for t in mapping.get("epic_types") or []]
            return epic_types[0] if epic_types else self.issue_type_for(TaskType.summary)
        item_type = mapping.get("item_type")
        return str(item_type) if item_type else self.issue_type_for(TaskType.task)

    def _build_create_fields(
        self,
        *,
        summary: str,
        description: str | None,
        issue_type: str,
        story_points: float | None,
        parent_key: str | None,
        project_key: str | None = None,
        estimate_field: str | None = None,
    ) -> dict[str, Any]:
        fields: dict[str, Any] = {
            "project": {"key": project_key or self.jira_project_key},
            "summary": summary,
            "issuetype": {"name": issue_type},
        }
        if description:
            fields["description"] = self._adf(description)
        if parent_key:
            fields["parent"] = {"key": parent_key}
        story_field = estimate_field or self._story_point_field
        if story_field and story_points is not None:
            fields[story_field] = story_points
        return fields

    async def _create_issue(
        self,
        *,
        summary: str,
        issue_type: str,
        description: str | None = None,
        story_points: float | None = None,
        parent_key: str | None = None,
        project_key: str | None = None,
        estimate_field: str | None = None,
    ) -> dict[str, str]:
        """Create a Jira issue from plan content. Returns {'id', 'key'}. Never sets status."""
        fields = self._build_create_fields(
            summary=summary,
            description=description,
            issue_type=issue_type,
            story_points=story_points,
            parent_key=parent_key,
            project_key=project_key,
            estimate_field=estimate_field,
        )
        async with await self.open_client() as client:
            resp = await request_with_retry(
                client, "POST", "/rest/api/3/issue", json={"fields": fields}
            )
        data: dict[str, Any] = resp.json()
        return {"id": str(data["id"]), "key": str(data["key"])}

    async def _update_issue(
        self,
        issue_id_or_key: str,
        *,
        summary: str | None = None,
        description: str | None = None,
        story_points: float | None = None,
        estimate_field: str | None = None,
    ) -> None:
        """Update an existing issue's content fields. Only provided fields change; status is
        never touched (it stays Jira-owned)."""
        fields: dict[str, Any] = {}
        if summary is not None:
            fields["summary"] = summary
        if description:
            fields["description"] = self._adf(description)
        story_field = estimate_field or self._story_point_field
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
