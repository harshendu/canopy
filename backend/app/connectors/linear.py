"""Linear as a work tracker (USER_FLOWS §J0): a team's issues over Linear's GraphQL API, its
workflow states (their `type` gives the category), cycles (→ tracker-owned sprints), issue
history (exact transitions), signed webhooks (`Linear-Signature`, HMAC-SHA256 of the raw body),
OAuth, and content writes for draft plans / publishing — never a state change.

Hierarchy: a Linear issue with sub-issues is an epic in canopy (a summary task, or a project
when mapped into an initiative); a binding's mapping can name `epic_labels` too.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, ClassVar

import httpx
from pydantic import BaseModel

from app.connectors.http import request_with_retry
from app.connectors.tracker import WorkTracker, register_tracker
from app.models.base import Provider
from app.services import workflow
from app.services.tracker_types import (
    KIND_EPIC,
    KIND_ITEM,
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

API_BASE = "https://api.linear.app"
# Linear's workflow-state types → canopy categories.
CATEGORY = {
    "triage": "todo",
    "backlog": "todo",
    "unstarted": "todo",
    "started": "in_progress",
    "completed": "done",
    "canceled": "cancelled",
}
_ORDER = {"todo": 0, "in_progress": 1, "done": 2, "cancelled": 3}
_COMPLETED_CYCLES_KEPT = 3
_PAGE = 100

_ISSUE_FIELDS = """
  id identifier title url updatedAt estimate
  state { name type position }
  parent { id }
  children(first: 1) { nodes { id } }
  assignee { id name email }
  labels(first: 20) { nodes { name } }
"""

ISSUES_QUERY = f"""
query CanopyIssues($filter: IssueFilter, $after: String) {{
  issues(filter: $filter, first: {_PAGE}, after: $after, orderBy: updatedAt) {{
    nodes {{ {_ISSUE_FIELDS} }}
    pageInfo {{ hasNextPage endCursor }}
  }}
}}
"""

ISSUE_QUERY = f"""
query CanopyIssue($id: String!) {{
  issue(id: $id) {{ {_ISSUE_FIELDS} }}
}}
"""

STATES_QUERY = """
query CanopyStates($filter: WorkflowStateFilter) {
  workflowStates(filter: $filter, first: 100) { nodes { name type position } }
}
"""

HISTORY_QUERY = """
query CanopyHistory($id: String!, $after: String) {
  issue(id: $id) {
    history(first: 50, after: $after) {
      nodes { createdAt actor { name } fromState { name type } toState { name type } }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""

CYCLES_QUERY = """
query CanopyCycles($filter: CycleFilter) {
  cycles(filter: $filter, first: 50) {
    nodes {
      id number name startsAt endsAt completedAt
      issues(first: 250) { nodes { id } }
    }
  }
}
"""

TEAMS_QUERY = """
query CanopyTeam($filter: TeamFilter) {
  teams(filter: $filter, first: 1) { nodes { id key } }
}
"""

CREATE_MUTATION = """
mutation CanopyCreate($input: IssueCreateInput!) {
  issueCreate(input: $input) { success issue { id identifier url } }
}
"""

UPDATE_MUTATION = """
mutation CanopyUpdate($id: String!, $input: IssueUpdateInput!) {
  issueUpdate(id: $id, input: $input) { success }
}
"""

COMMENT_MUTATION = """
mutation CanopyComment($input: CommentCreateInput!) {
  commentCreate(input: $input) { success }
}
"""


class LinearError(RuntimeError):
    """Linear answered with GraphQL errors."""


class LinearConnectionConfig(BaseModel):
    """A Linear workspace. The API key (or OAuth token) is entered separately."""

    workspace_url_key: str | None = None  # the "acme" of linear.app/acme — for browse links
    team_key: str | None = None  # the default team for bindings, e.g. "ENG"


class LinearScope(BaseModel):
    """Where in Linear a binding points."""

    team_key: str | None = None  # the team whose issues the project mirrors, e.g. "ENG"
    linear_project_id: str | None = None  # narrow to one Linear project (its id)
    label: str | None = None  # narrow to issues carrying this label


def _parse_time(value: Any) -> datetime | None:
    return workflow.parse_remote_time(str(value)) if value else None


@register_tracker(Provider.linear)
class LinearTracker(WorkTracker):
    label: ClassVar[str] = "Linear"
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
    config_schema: ClassVar[type[BaseModel]] = LinearConnectionConfig
    scope_schema: ClassVar[type[BaseModel]] = LinearScope
    # Linear signs the raw body: `Linear-Signature: <hex HMAC-SHA256>`.
    webhook_signature_header: ClassVar[str | None] = "Linear-Signature"
    scope_selector_keys: ClassVar[tuple[str, ...]] = ("team_key", "linear_project_id", "label")

    # --------------------------------------------------------------------- #
    # HTTP
    # --------------------------------------------------------------------- #

    @property
    def _is_oauth(self) -> bool:
        return (
            self.config.get("auth_type") == "oauth"
            or self.connection.encrypted_refresh_token is not None
        )

    def _client(self) -> httpx.AsyncClient:
        token = self.access_token() or ""
        # A personal API key goes in Authorization as-is; an OAuth token as a Bearer token.
        auth = f"Bearer {token}" if self._is_oauth else token
        return httpx.AsyncClient(
            base_url=API_BASE,
            headers={"Content-Type": "application/json", "Authorization": auth},
            timeout=30.0,
        )

    async def _gql(
        self, client: httpx.AsyncClient, query: str, variables: dict[str, Any]
    ) -> dict[str, Any]:
        resp = await request_with_retry(
            client, "POST", "/graphql", json={"query": query, "variables": variables}
        )
        body: dict[str, Any] = resp.json()
        errors = body.get("errors")
        if errors:
            raise LinearError("; ".join(str(e.get("message")) for e in errors))
        data: dict[str, Any] = body.get("data") or {}
        return data

    def _team_key(self, scope: Scope) -> str:
        return str(scope.get("team_key") or self.config.get("team_key") or "")

    def _issue_filter(self, scope: Scope, since: str | None = None) -> dict[str, Any]:
        out: dict[str, Any] = {}
        team = self._team_key(scope)
        if team:
            out["team"] = {"key": {"eq": team}}
        if scope.get("linear_project_id"):
            out["project"] = {"id": {"eq": str(scope.get("linear_project_id"))}}
        if scope.get("label"):
            out["labels"] = {"name": {"eq": str(scope.get("label"))}}
        if since:
            out["updatedAt"] = {"gt": since}
        return out

    # --------------------------------------------------------------------- #
    # Normalization
    # --------------------------------------------------------------------- #

    @staticmethod
    def _epic_labels(scope: Scope | None) -> set[str]:
        labels = {"epic"}
        if scope is not None:
            labels |= {str(x).casefold() for x in scope.mapping.get("epic_labels") or []}
        return labels

    def normalize(self, issue: Mapping[str, Any], scope: Scope | None = None) -> WorkItem:
        state = issue.get("state") or {}
        children = ((issue.get("children") or {}).get("nodes")) or []
        labels = {
            str(n.get("name") or "").casefold()
            for n in ((issue.get("labels") or {}).get("nodes") or [])
        }
        kind = KIND_EPIC if children or (labels & self._epic_labels(scope)) else KIND_ITEM
        parent = issue.get("parent") or {}
        parent_id = parent.get("id") or issue.get("parentId")
        assignee = issue.get("assignee") or {}
        estimate = issue.get("estimate")
        key = str(issue.get("identifier") or "") or None
        return WorkItem(
            external_id=str(issue["id"]),
            key=key,
            title=str(issue.get("title") or key or issue["id"]),
            status_name=state.get("name"),
            status_category=CATEGORY.get(str(state.get("type") or "")),
            kind=kind,
            parent_external_id=str(parent_id) if parent_id else None,
            assignee=Assignee(
                account_id=assignee.get("id"),
                name=assignee.get("name"),
                email=assignee.get("email"),
            )
            if assignee
            else None,
            estimate=float(estimate) if isinstance(estimate, int | float) else None,
            updated=issue.get("updatedAt"),
            url=issue.get("url") or (self.item_url(key) if key else None),
            raw_type="Issue",
        )

    @classmethod
    def browse_url(cls, config: Mapping[str, Any], key: str) -> str | None:
        workspace = config.get("workspace_url_key")
        return f"https://linear.app/{workspace}/issue/{key}" if workspace else None

    # --------------------------------------------------------------------- #
    # Reads
    # --------------------------------------------------------------------- #

    async def _issues(
        self, client: httpx.AsyncClient, issue_filter: dict[str, Any]
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        after: str | None = None
        while True:
            data = await self._gql(client, ISSUES_QUERY, {"filter": issue_filter, "after": after})
            page = data.get("issues") or {}
            out.extend(page.get("nodes") or [])
            info = page.get("pageInfo") or {}
            after = info.get("endCursor")
            if not info.get("hasNextPage") or not after:
                break
        return out

    async def fetch_items(self, scope: Scope, since: str | None) -> ItemPage:
        async with await self.open_client() as client:
            issues = await self._issues(client, self._issue_filter(scope, since))
        stamps = [str(i["updatedAt"]) for i in issues if i.get("updatedAt")]
        return ItemPage(
            items=[self.normalize(i, scope) for i in issues],
            watermark=max(stamps) if stamps else since,
        )

    async def fetch_item(self, scope: Scope, key: str) -> WorkItem | None:
        async with await self.open_client() as client:
            try:
                data = await self._gql(client, ISSUE_QUERY, {"id": key})
            except LinearError:
                return None
        issue = data.get("issue")
        return self.normalize(issue, scope) if issue else None

    async def fetch_subtree(self, scope: Scope, root_key: str) -> list[WorkItem]:
        """The root issue and every sub-issue below it (breadth-first by parent)."""
        async with await self.open_client() as client:
            try:
                root = (await self._gql(client, ISSUE_QUERY, {"id": root_key})).get("issue")
            except LinearError:
                return []
            if not root:
                return []
            seen: dict[str, dict[str, Any]] = {str(root["id"]): root}
            frontier = [str(root["id"])]
            while frontier:
                children = await self._issues(client, {"parent": {"id": {"in": frontier}}})
                frontier = []
                for child in children:
                    cid = str(child["id"])
                    if cid not in seen:
                        seen[cid] = child
                        frontier.append(cid)
        return [self.normalize(i, scope) for i in seen.values()]

    async def list_statuses(self, scope: Scope) -> list[StatusDef]:
        team = self._team_key(scope)
        variables: dict[str, Any] = {
            "filter": {"team": {"key": {"eq": team}}} if team else None
        }
        async with await self.open_client() as client:
            data = await self._gql(client, STATES_QUERY, variables)
        ranked: list[tuple[str, dict[str, Any]]] = []
        for node in (data.get("workflowStates") or {}).get("nodes") or []:
            category = CATEGORY.get(str(node.get("type") or ""))
            if category is not None and node.get("name"):
                ranked.append((category, node))
        ranked.sort(key=lambda pair: (_ORDER[pair[0]], float(pair[1].get("position") or 0)))
        seen: set[str] = set()
        out: list[StatusDef] = []
        for category, state in ranked:
            name = str(state["name"])
            if name.casefold() in seen:
                continue
            seen.add(name.casefold())
            out.append(StatusDef(name=name, category=category, position=len(out)))
        return out

    async def fetch_status_changes(self, scope: Scope, ref: ItemRef) -> list[StatusChange]:
        changes: list[StatusChange] = []
        after: str | None = None
        async with await self.open_client() as client:
            while True:
                data = await self._gql(
                    client, HISTORY_QUERY, {"id": ref.external_id, "after": after}
                )
                history = ((data.get("issue") or {}).get("history")) or {}
                for entry in history.get("nodes") or []:
                    to_state = entry.get("toState") or {}
                    at = _parse_time(entry.get("createdAt"))
                    if not to_state.get("name") or at is None:
                        continue
                    from_state = entry.get("fromState") or {}
                    changes.append(
                        StatusChange(
                            to_status=str(to_state["name"]),
                            from_status=from_state.get("name"),
                            at=at,
                            author=(entry.get("actor") or {}).get("name"),
                            to_category=CATEGORY.get(str(to_state.get("type") or "")),
                        )
                    )
                info = history.get("pageInfo") or {}
                after = info.get("endCursor")
                if not info.get("hasNextPage") or not after:
                    break
        return sorted(changes, key=lambda c: c.at)

    async def fetch_iterations(self, scope: Scope) -> list[Iteration]:
        """The team's active and upcoming cycles plus its most recently completed ones."""
        team = self._team_key(scope)
        if not team:
            return []
        async with await self.open_client() as client:
            data = await self._gql(
                client, CYCLES_QUERY, {"filter": {"team": {"key": {"eq": team}}}}
            )
        now = datetime.now(UTC).replace(tzinfo=None)
        live: list[Iteration] = []
        done: list[Iteration] = []
        for cycle in (data.get("cycles") or {}).get("nodes") or []:
            start = _parse_time(cycle.get("startsAt"))
            end = _parse_time(cycle.get("endsAt"))
            if cycle.get("completedAt") or (end is not None and end <= now):
                state = "completed"
            elif start is not None and start > now:
                state = "planned"
            else:
                state = "active"
            iteration = Iteration(
                external_id=str(cycle["id"]),
                name=str(cycle.get("name") or f"Cycle {cycle.get('number') or ''}".strip()),
                state=state,
                start=start.date() if start else None,
                end=end.date() if end else None,
                item_external_ids=tuple(
                    str(i["id"]) for i in (cycle.get("issues") or {}).get("nodes") or []
                ),
            )
            (done if state == "completed" else live).append(iteration)
        done.sort(key=lambda i: i.end or i.start or datetime.min.date())
        return live + done[-_COMPLETED_CYCLES_KEPT:]

    # --------------------------------------------------------------------- #
    # Content writes (never a state change)
    # --------------------------------------------------------------------- #

    async def _team_id(self, client: httpx.AsyncClient, scope: Scope) -> str:
        team = self._team_key(scope)
        if not team:
            raise LinearError("No Linear team in the binding's scope (team_key)")
        data = await self._gql(client, TEAMS_QUERY, {"filter": {"key": {"eq": team}}})
        nodes = (data.get("teams") or {}).get("nodes") or []
        if not nodes:
            raise LinearError(f"Linear team {team} not found")
        return str(nodes[0]["id"])

    async def create_item(self, scope: Scope, draft: ItemDraft) -> ItemRef:
        async with await self.open_client() as client:
            payload: dict[str, Any] = {
                "teamId": await self._team_id(client, scope),
                "title": draft.title,
            }
            if draft.description:
                payload["description"] = draft.description
            if draft.estimate is not None:
                payload["estimate"] = round(draft.estimate)
            if draft.parent is not None:
                payload["parentId"] = draft.parent.external_id
            if scope.get("linear_project_id"):
                payload["projectId"] = str(scope.get("linear_project_id"))
            data = await self._gql(client, CREATE_MUTATION, {"input": payload})
        issue = ((data.get("issueCreate") or {}).get("issue")) or {}
        if not issue.get("id"):
            raise LinearError("Linear did not create the issue")
        return ItemRef(external_id=str(issue["id"]), key=issue.get("identifier"))

    async def update_item(self, scope: Scope, ref: ItemRef, patch: ItemPatch) -> None:
        payload: dict[str, Any] = {}
        if patch.title is not None:
            payload["title"] = patch.title
        if patch.description:
            payload["description"] = patch.description
        if patch.estimate is not None:
            payload["estimate"] = round(patch.estimate)
        if not payload:
            return
        async with await self.open_client() as client:
            await self._gql(client, UPDATE_MUTATION, {"id": ref.external_id, "input": payload})

    async def add_comment(self, scope: Scope, ref: ItemRef, body: str) -> None:
        async with await self.open_client() as client:
            await self._gql(client, COMMENT_MUTATION,
                            {"input": {"issueId": ref.external_id, "body": body}})

    # --------------------------------------------------------------------- #
    # Webhooks
    # --------------------------------------------------------------------- #

    @classmethod
    def webhook_scope_hint(cls, payload: dict[str, Any]) -> dict[str, Any]:
        data = payload.get("data") or {}
        team = (data.get("team") or {}).get("key")
        if not team:
            identifier = str(data.get("identifier") or "")
            team = identifier.split("-")[0] if "-" in identifier else None
        return {"team_key": team} if team else {}

    def parse_webhook(self, payload: dict[str, Any]) -> WebhookEvent | None:
        if payload.get("type") != "Issue":
            return None
        data = payload.get("data") or {}
        if not data.get("id"):
            return None
        hint = self.webhook_scope_hint(payload)
        if payload.get("action") == "remove":
            return WebhookEvent(item=None, scope_hint=hint, deleted=True)
        return WebhookEvent(item=self.normalize(data), scope_hint=hint)
