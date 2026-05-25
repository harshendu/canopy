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
_JIRA_PROJECT_KEY = "PLAT"


def _jira_issue(
    issue_id: str, key: str, summary: str, issuetype: str, status: str, parent_id: str | None
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "summary": summary,
        "status": {"name": status},
        "issuetype": {"name": issuetype},
        "updated": _UPDATED,
        "customfield_10016": 5,
        "customfield_10042": "https://demo.atlassian.net/wiki/spaces/PLAT/design",
    }
    if parent_id is not None:
        fields["parent"] = {"id": parent_id, "key": f"{_JIRA_PROJECT_KEY}-100"}
    return {"id": issue_id, "key": key, "fields": fields}


_JIRA_EPIC = _jira_issue(
    "910000", "PLAT-100", "Observability & SLOs", "Epic", "In Progress", None
)
_JIRA_STORIES = [
    _jira_issue("910001", "PLAT-101", "Emit structured request logs", "Story", "Done", "910000"),
    _jira_issue("910002", "PLAT-102", "Dashboards for the golden signals", "Story",
                "In Progress", "910000"),
    _jira_issue("910003", "PLAT-103", "Define and wire SLO alerts", "Story", "To Do", "910000"),
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
            "author": {"displayName": "Sofia Garcia"},
            "items": [{"field": "status", "fromString": "To Do", "toString": "In Progress"}],
        },
        {
            "created": "2026-04-22T16:30:00.000+0000",
            "author": {"displayName": "Sofia Garcia"},
            "items": [{"field": "status", "fromString": "In Progress", "toString": "Done"}],
        },
    ],
    "isLast": True,
    "startAt": 0,
    "maxResults": 100,
    "total": 2,
}

_jira_created_seq = [910100]


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
            201, json={"id": str(n), "key": f"{_JIRA_PROJECT_KEY}-{n - 910000}"}, request=request
        )
    if method == "PUT" and path.startswith("/rest/api/3/issue/"):
        return httpx.Response(204, request=request)
    if method == "GET" and path.startswith("/rest/api/3/issue/"):
        rest = path[len("/rest/api/3/issue/"):]
        key = rest.split("/")[0]
        if rest.endswith("/changelog"):
            return httpx.Response(200, json=_JIRA_CHANGELOG, request=request)
        if rest.endswith("/remotelink"):
            link = {"object": {"url": "https://demo.atlassian.net/runbook", "title": "Runbook"}}
            return httpx.Response(200, json=[link], request=request)
        issue = _JIRA_BY_KEY.get(key)
        if issue is None:
            return httpx.Response(404, json={"errorMessages": ["Issue does not exist"]},
                                  request=request)
        return httpx.Response(200, json=issue, request=request)
    if method == "GET" and path == "/rest/agile/1.0/board":
        return httpx.Response(
            200, json={"values": [{"id": 1, "name": "PLAT board"}]}, request=request
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
# GitHub fixtures + handler
# --------------------------------------------------------------------------- #
_GH_ADR_MARKDOWN = """# ADR-0007: Adopt OpenTelemetry for tracing

## Status
accepted

## Context
We need vendor-neutral distributed tracing across the gateway and downstream services.

## Decision
Standardize on OpenTelemetry SDKs with an OTLP collector.

## Consequences
All services emit OTLP; dashboards read from a single backend.
"""

_GH_PULLS = [
    {"number": 128, "title": "Add OTLP exporter to gateway", "html_url":
     "https://github.com/canopy-co/platform/pull/128", "state": "open", "user": {"login":
     "sofiagarcia"}, "updated_at": "2026-05-02T10:00:00Z"},
    {"number": 126, "title": "Golden-signal dashboards", "html_url":
     "https://github.com/canopy-co/platform/pull/126", "state": "open", "user": {"login":
     "tombecker"}, "updated_at": "2026-05-01T09:00:00Z"},
    {"number": 120, "title": "Structured request logging", "html_url":
     "https://github.com/canopy-co/platform/pull/120", "state": "closed", "user": {"login":
     "sofiagarcia"}, "updated_at": "2026-04-22T16:00:00Z"},
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
            json=[{"number": 1, "title": "v2 GA", "due_on": "2026-08-01T00:00:00Z"}],
            request=request,
        )
    # GET /repos/{owner}/{repo} — connectivity check for full_sync.
    return httpx.Response(
        200,
        json={"full_name": "canopy-co/platform", "default_branch": "main", "private": False},
        request=request,
    )


# --------------------------------------------------------------------------- #
# Google Drive fixtures + handler
# --------------------------------------------------------------------------- #
_DRIVE_FILES = [
    {"id": "doc-prd-001", "name": "Platform 2026 — PRD", "modifiedTime":
     "2026-03-01T12:00:00Z"},
    {"id": "doc-design-002", "name": "Observability — Design", "modifiedTime":
     "2026-03-15T12:00:00Z"},
]
_DRIVE_DOC = "# Observability — Design\n\nGoals, golden signals, and the SLO alerting plan.\n"


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
