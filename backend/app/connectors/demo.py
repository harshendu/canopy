"""In-process HTTP mock for connectors in demo mode.

When ``settings.DEMO_MODE`` is on and a connection's config carries ``demo: true``, the
connector's HTTP client is backed by an :class:`httpx.MockTransport` instead of the real
network. Every provider endpoint the connectors call (Jira search/agile/changelog/fields,
GitHub repo/PRs/contents, Drive files/export/upload) is answered from the canned fixtures
below, so "Sync from Jira", GitHub PR reads, Drive doc reads, ADR import, doc harvest, and
draft → Jira push all work fully offline.

The fixtures are intentionally small and self-consistent: a Jira project (one epic + three
stories on an active sprint), a GitHub repo (a few PRs + a markdown ADR), and a Drive folder
(a couple of Google Docs). Sync is idempotent — re-running it upserts via ``ExternalRef``
rather than duplicating. This data lives in the repo as part of the demo seed.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx

from app.connectors.base import Connector
from app.core.config import settings

DEMO_CONFIG_FLAG = "demo"

# A fixed "now-ish" timestamp string for fixture `updated` fields (Jira ISO 8601).
_UPDATED = "2026-05-01T12:00:00.000+0000"


def is_demo_connection(connector: Connector) -> bool:
    """True when this connector should be served by the offline mock."""
    return bool(settings.DEMO_MODE and connector.config.get(DEMO_CONFIG_FLAG))


# --------------------------------------------------------------------------- #
# Jira fixtures + handler
# --------------------------------------------------------------------------- #
_JIRA_PROJECT_KEY = "SHOP"
_JIRA_EPIC_ID = "930200"
_JIRA_EPIC_KEY = f"{_JIRA_PROJECT_KEY}-200"


def _jira_issue(
    issue_id: str, key: str, summary: str, issuetype: str, status: str, parent_id: str | None
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "summary": summary,
        "status": {"name": status},
        "issuetype": {"name": issuetype},
        "updated": _UPDATED,
        "customfield_10016": 5,
        "customfield_10042": "https://wiki.example.com/checkout/observability",
    }
    if parent_id is not None:
        fields["parent"] = {"id": parent_id, "key": _JIRA_EPIC_KEY}
    return {"id": issue_id, "key": key, "fields": fields}


_JIRA_EPIC = _jira_issue(
    _JIRA_EPIC_ID, _JIRA_EPIC_KEY, "Checkout observability", "Epic", "In Progress", None
)
_JIRA_STORIES = [
    _jira_issue("930201", "SHOP-201", "Emit checkout funnel events", "Story", "Done",
                _JIRA_EPIC_ID),
    _jira_issue("930202", "SHOP-202", "Payment error dashboards", "Story", "In Progress",
                _JIRA_EPIC_ID),
    _jira_issue("930203", "SHOP-203", "Alert on the checkout error-rate SLO", "Story", "To Do",
                _JIRA_EPIC_ID),
]
_JIRA_ISSUES = [_JIRA_EPIC, *_JIRA_STORIES]
_JIRA_BY_KEY = {i["key"]: i for i in _JIRA_ISSUES}

_JIRA_FIELDS = [
    {"id": "summary", "name": "Summary"},
    {"id": "status", "name": "Status"},
    {"id": "customfield_10016", "name": "Story Points"},
    {"id": "customfield_10042", "name": "Design Doc"},
]

_JIRA_CHANGELOG = {
    "values": [
        {
            "created": "2026-04-10T09:00:00.000+0000",
            "author": {"displayName": "Priya Shah"},
            "items": [{"field": "status", "fromString": "To Do", "toString": "In Progress"}],
        },
        {
            "created": "2026-04-22T16:30:00.000+0000",
            "author": {"displayName": "Priya Shah"},
            "items": [{"field": "status", "fromString": "In Progress", "toString": "Done"}],
        },
    ],
    "isLast": True,
    "startAt": 0,
    "maxResults": 100,
    "total": 2,
}

_jira_created_seq = [930300]

# The demo Jira project's workflow: (name, canopy category) in Jira's order — served as
# `GET /rest/api/3/project/SHOP/statuses` and seeded as the flagship binding's status map.
DEMO_JIRA_STATUSES: tuple[tuple[str, str], ...] = (
    ("To Do", "todo"),
    ("In Progress", "in_progress"),
    ("In Review", "in_progress"),
    ("Done", "done"),
)
_JIRA_STATUS_KEY = {"todo": "new", "in_progress": "indeterminate", "done": "done"}


def _handle_jira(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    method = request.method.upper()

    if method == "POST" and path == "/rest/api/3/search/jql":
        return httpx.Response(
            200, json={"issues": _JIRA_ISSUES, "isLast": True, "nextPageToken": None},
            request=request,
        )
    if method == "GET" and path == "/rest/api/3/field":
        return httpx.Response(200, json=_JIRA_FIELDS, request=request)
    if method == "POST" and path == "/rest/api/3/issue":
        _jira_created_seq[0] += 1
        n = _jira_created_seq[0]
        return httpx.Response(
            201, json={"id": str(n), "key": f"{_JIRA_PROJECT_KEY}-{n - 930000}"}, request=request
        )
    if method == "PUT" and path.startswith("/rest/api/3/issue/"):
        return httpx.Response(204, request=request)
    if method == "GET" and path.startswith("/rest/api/3/issue/"):
        rest = path[len("/rest/api/3/issue/"):]
        key = rest.split("/")[0]
        if rest.endswith("/changelog"):
            return httpx.Response(200, json=_JIRA_CHANGELOG, request=request)
        if rest.endswith("/remotelink"):
            link = {"object": {"url": "https://wiki.example.com/checkout/runbook",
                               "title": "Checkout runbook"}}
            return httpx.Response(200, json=[link], request=request)
        issue = _JIRA_BY_KEY.get(key)
        if issue is None:
            return httpx.Response(404, json={"errorMessages": ["Issue does not exist"]},
                                  request=request)
        return httpx.Response(200, json=issue, request=request)
    if method == "GET" and path == f"/rest/api/3/project/{_JIRA_PROJECT_KEY}/statuses":
        statuses = [
            {"name": name, "statusCategory": {"key": _JIRA_STATUS_KEY[category]}}
            for name, category in DEMO_JIRA_STATUSES
        ]
        return httpx.Response(
            200, json=[{"name": "Story", "statuses": statuses}], request=request
        )
    if method == "GET" and path == "/rest/agile/1.0/board":
        return httpx.Response(
            200, json={"values": [{"id": 1, "name": "SHOP board"}]}, request=request
        )
    if method == "GET" and path.endswith("/sprint"):
        return httpx.Response(
            200,
            json={"values": [{"id": 5001, "name": "Sprint 12", "state": "active"}]},
            request=request,
        )
    if method == "GET" and "/sprint/" in path and path.endswith("/issue"):
        return httpx.Response(
            200, json={"issues": _JIRA_STORIES[:2], "total": 2}, request=request
        )
    return httpx.Response(200, json={"issues": [], "isLast": True, "values": []}, request=request)


# --------------------------------------------------------------------------- #
# Linear fixtures + handler (GraphQL, one POST /graphql endpoint)
# --------------------------------------------------------------------------- #
_LINEAR_TEAM = {"id": "team-eng", "key": "ENG"}
_LINEAR_STATES = [
    {"name": "Backlog", "type": "backlog", "position": 0},
    {"name": "Todo", "type": "unstarted", "position": 1},
    {"name": "In Progress", "type": "started", "position": 2},
    {"name": "In Review", "type": "started", "position": 3},
    {"name": "Done", "type": "completed", "position": 4},
    {"name": "Canceled", "type": "canceled", "position": 5},
]
_LINEAR_UPDATED = "2026-05-02T09:00:00.000Z"


def _linear_issue(
    n: int,
    title: str,
    state: int,
    *,
    parent: int | None = None,
    children: tuple[int, ...] = (),
    estimate: int | None = None,
    assignee: str | None = None,
) -> dict[str, Any]:
    return {
        "id": f"lin-{n}",
        "identifier": f"ENG-{n}",
        "title": title,
        "url": f"https://linear.app/example/issue/ENG-{n}",
        "updatedAt": _LINEAR_UPDATED,
        "estimate": estimate,
        "state": dict(_LINEAR_STATES[state]),
        "parent": {"id": f"lin-{parent}"} if parent else None,
        "children": {"nodes": [{"id": f"lin-{c}"} for c in children]},
        "assignee": {"id": f"user-{assignee.split()[0].lower()}", "name": assignee, "email": None}
        if assignee
        else None,
        "labels": {"nodes": []},
    }


_LINEAR_ISSUES = [
    _linear_issue(1, "Search relevance revamp", 2, children=(2, 3, 4)),
    _linear_issue(2, "Tune ranking signals", 4, parent=1, estimate=3, assignee="Ana Lima"),
    _linear_issue(3, "Synonym dictionary", 2, parent=1, estimate=2, assignee="Ana Lima"),
    _linear_issue(4, "Relevance dashboard", 1, parent=1, estimate=1),
]
_LINEAR_BY_ID = {
    **{i["id"]: i for i in _LINEAR_ISSUES},
    **{i["identifier"]: i for i in _LINEAR_ISSUES},
}
_LINEAR_HISTORY = [
    {
        "createdAt": "2026-04-28T10:00:00.000Z",
        "actor": {"name": "Ana Lima"},
        "fromState": {"name": "Todo", "type": "unstarted"},
        "toState": {"name": "In Progress", "type": "started"},
    },
]
_linear_created_seq = [100]


def _linear_cycles() -> list[dict[str, Any]]:
    """An active cycle around today (dates relative, so it's always current)."""
    from datetime import UTC, datetime, timedelta

    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    iso = "%Y-%m-%dT%H:%M:%S.000Z"
    return [
        {
            "id": "cyc-7",
            "number": 7,
            "name": "Cycle 7",
            "startsAt": (today - timedelta(days=3)).strftime(iso),
            "endsAt": (today + timedelta(days=11)).strftime(iso),
            "completedAt": None,
            "issues": {"nodes": [{"id": "lin-2"}, {"id": "lin-3"}]},
        }
    ]


def _handle_linear(request: httpx.Request) -> httpx.Response:
    body = parse_json_body(request)
    query = str(body.get("query") or "")
    variables = body.get("variables") or {}

    def ok(data: dict[str, Any]) -> httpx.Response:
        return httpx.Response(200, json={"data": data}, request=request)

    if "issueCreate" in query:
        _linear_created_seq[0] += 1
        n = _linear_created_seq[0]
        issue = {"id": f"lin-new-{n}", "identifier": f"ENG-{n}",
                 "url": f"https://linear.app/example/issue/ENG-{n}"}
        return ok({"issueCreate": {"success": True, "issue": issue}})
    if "issueUpdate" in query:
        return ok({"issueUpdate": {"success": True}})
    if "teams(" in query:
        return ok({"teams": {"nodes": [_LINEAR_TEAM]}})
    if "workflowStates" in query:
        return ok({"workflowStates": {"nodes": _LINEAR_STATES}})
    if "cycles(" in query:
        return ok({"cycles": {"nodes": _linear_cycles()}})
    if "history(" in query:
        page = {"nodes": _LINEAR_HISTORY, "pageInfo": {"hasNextPage": False, "endCursor": None}}
        return ok({"issue": {"history": page}})
    if "issues(" in query:
        parents = (((variables.get("filter") or {}).get("parent") or {}).get("id") or {}).get(
            "in"
        )
        nodes = (
            [i for i in _LINEAR_ISSUES if i["parent"] and i["parent"]["id"] in parents]
            if parents
            else _LINEAR_ISSUES
        )
        page = {"nodes": nodes, "pageInfo": {"hasNextPage": False, "endCursor": None}}
        return ok({"issues": page})
    if "issue(" in query:
        found = _LINEAR_BY_ID.get(str(variables.get("id")))
        if found is None:
            return httpx.Response(
                200, json={"data": None, "errors": [{"message": "Entity not found"}]},
                request=request,
            )
        return ok({"issue": found})
    return ok({})


# --------------------------------------------------------------------------- #
# GitHub fixtures + handler
# --------------------------------------------------------------------------- #
_GH_ADR_MARKDOWN = """# ADR-0007: Tokenize cards through the provider vault

## Status
accepted

## Context
Storing card numbers would put every service that touches checkout in PCI scope.

## Decision
Cards are tokenized in the payment provider's vault straight from the browser; our services
only ever see tokens.

## Consequences
PCI scope shrinks to a few services; we depend on the provider's vault for retries and any
future migration.
"""

_GH_REPO = "example-shop/checkout"


def _gh_pull(number: int, title: str, state: str, login: str, updated: str) -> dict[str, Any]:
    return {"number": number, "title": title, "state": state, "user": {"login": login},
            "html_url": f"https://github.com/{_GH_REPO}/pull/{number}", "updated_at": updated}


_GH_PULLS = [
    _gh_pull(412, "Integrate tokenized card payments", "open", "priyashah",
             "2026-05-02T10:00:00Z"),
    _gh_pull(415, "Handle 3-D Secure challenges in checkout", "open", "gabrielsilva",
             "2026-05-01T09:00:00Z"),
    _gh_pull(398, "Checkout session service", "closed", "rahulverma", "2026-04-22T16:00:00Z"),
]


def _handle_github(request: httpx.Request) -> httpx.Response:
    import base64

    path = request.url.path
    method = request.method.upper()
    if method == "GET" and "/contents/" in path:
        content = base64.b64encode(_GH_ADR_MARKDOWN.encode()).decode()
        return httpx.Response(
            200, json={"encoding": "base64", "content": content}, request=request
        )
    if method == "GET" and path.endswith("/pulls"):
        return httpx.Response(200, json=_GH_PULLS, request=request)
    if method == "GET" and path.endswith("/milestones"):
        return httpx.Response(
            200,
            json=[{"number": 1, "title": "Checkout GA", "due_on": "2026-08-01T00:00:00Z"}],
            request=request,
        )
    # GET /repos/{owner}/{repo} — connectivity check for full_sync.
    return httpx.Response(
        200,
        json={"full_name": _GH_REPO, "default_branch": "main", "private": False},
        request=request,
    )


# --------------------------------------------------------------------------- #
# Google Drive fixtures + handler
# --------------------------------------------------------------------------- #
_DRIVE_FILES = [
    {"id": "doc-prd-checkout", "name": "Checkout Modernization — PRD", "modifiedTime":
     "2026-03-01T12:00:00Z"},
    {"id": "doc-payments-arch", "name": "Payments — Reference Architecture", "modifiedTime":
     "2026-03-15T12:00:00Z"},
]
_DRIVE_DOC = (
    "# Checkout Modernization — Design\n\n"
    "The one-page checkout, the server-side checkout session, and tokenized card payments.\n"
)


def _handle_gdrive(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    method = request.method.upper()
    if method == "POST" and "/upload/drive/v3/files" in path:
        return httpx.Response(
            200,
            json={"id": "uploaded-001", "name": "snapshot", "webViewLink":
                  "https://drive.google.com/file/d/uploaded-001/view"},
            request=request,
        )
    if method == "GET" and path.endswith("/export"):
        return httpx.Response(200, text=_DRIVE_DOC, request=request)
    if method == "GET" and path.endswith("/files"):
        return httpx.Response(200, json={"files": _DRIVE_FILES}, request=request)
    return httpx.Response(200, json={"files": []}, request=request)


_HANDLERS: dict[str, Callable[[httpx.Request], httpx.Response]] = {
    "linear": _handle_linear,
    "jira": _handle_jira,
    "github": _handle_github,
    "gdrive": _handle_gdrive,
}


def demo_client(connector: Connector) -> httpx.AsyncClient:
    """An httpx client whose transport answers from the in-memory fixtures (no network)."""
    handler = _HANDLERS[connector.provider.value]
    base_url = str(connector.config.get("base_url") or "https://demo.local")
    return httpx.AsyncClient(
        base_url=base_url, transport=httpx.MockTransport(handler), timeout=5.0
    )


def parse_json_body(request: httpx.Request) -> dict[str, Any]:
    """Best-effort decode of a request body (helper for future fixture assertions)."""
    if not request.content:
        return {}
    try:
        data = json.loads(request.content)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}
