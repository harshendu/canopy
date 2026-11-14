"""Guardrails for the pluggable-tracking work: characterisation tests that pin today's Jira sync
behaviour so the port onto the tracker interface can be proven to change nothing.

The "unmodified-Jira gate" is this file plus: test_jira_mapping, test_jira_linking,
test_jira_history, test_ingest, test_drafts, test_webhook_security, test_integration_policy and
test_user_connections. They must keep passing with import-path edits only.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from sqlmodel import func, select

import app.workers.worker as worker
from app.connectors.jira import JiraConnector
from app.core.crypto import encrypt_token
from app.models.base import Provider
from app.models.integration import Connection
from app.models.project import Project, Task
from app.services import ingest
from app.services import sync as sync_service
from tests.conftest import TestSession


async def _project(session: Any, key: str = "PLAT") -> Project:
    project = Project(key=key, name="Platform")
    session.add(project)
    await session.flush()
    return project


async def _jira_connection(session: Any, project: Project) -> Connection:
    connection = Connection(
        provider=Provider.jira,
        name="jira",
        encrypted_token=encrypt_token("api-token"),
        config={
            "base_url": "https://example.atlassian.net",
            "email": "a@b.com",
            "project_id": project.id,
            "jira_project_key": "PLAT",
        },
    )
    session.add(connection)
    await session.commit()
    return connection


def _issue(ext_id: str, key: str, status: str, updated: str) -> dict[str, Any]:
    return {
        "id": ext_id,
        "key": key,
        "fields": {
            "summary": f"Issue {key}",
            "status": {"name": status},
            "issuetype": {"name": "Story"},
            "updated": updated,
        },
    }


async def _upsert(session: Any, project_id: int, status: str, updated: str) -> Task:
    _, task_id = await ingest.upsert_task_from_external(
        session,
        project_id=project_id,
        provider=Provider.jira,
        external_id="10001",
        external_key="PLAT-1",
        summary="Issue PLAT-1",
        status=status,
        is_epic=False,
        updated=updated,
    )
    await session.commit()
    task = await session.get(Task, task_id)
    assert task is not None
    return task


async def test_done_status_sets_progress_and_leaving_done_resets_it(db_session):
    project = await _project(db_session)
    assert project.id is not None

    task = await _upsert(db_session, project.id, "In Progress", "2026-05-01T10:00:00.000+0000")
    task.percent_complete = 40.0
    await db_session.commit()

    task = await _upsert(db_session, project.id, "Done", "2026-05-02T10:00:00.000+0000")
    assert task.percent_complete == 100.0

    task = await _upsert(db_session, project.id, "In Progress", "2026-05-03T10:00:00.000+0000")
    assert task.percent_complete == 0.0  # regressed out of done

    task.percent_complete = 30.0
    await db_session.commit()
    task = await _upsert(db_session, project.id, "In Review", "2026-05-04T10:00:00.000+0000")
    assert task.percent_complete == 30.0  # partial manual progress survives a not-done move


async def test_incremental_sync_advances_the_watermark(db_session, monkeypatch):
    project = await _project(db_session)
    connection = await _jira_connection(db_session, project)
    assert connection.id is not None
    jqls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        if request.url.path.endswith("/search/jql"):
            jqls.append(str(body.get("jql")))
            issues = [_issue("10001", "PLAT-1", "To Do", "2026-05-02T10:00:00.000+0000")]
            return httpx.Response(200, json={"issues": issues, "isLast": True})
        return httpx.Response(200, json={"values": []})

    def fake_client(self: JiraConnector) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url="https://example.atlassian.net", transport=httpx.MockTransport(handler)
        )

    monkeypatch.setattr(JiraConnector, "_client", fake_client)

    first = await sync_service.run_incremental_sync(db_session, connection.id)
    second = await sync_service.run_incremental_sync(db_session, connection.id)

    assert first.created == 1
    assert second.created == 0
    assert "updated >=" not in jqls[0]
    assert 'updated >= "2026-05-02 10:00"' in jqls[1]


async def test_webhook_upsert_is_idempotent(db_session, monkeypatch):
    monkeypatch.setattr(worker, "async_session_factory", TestSession)
    project = await _project(db_session)
    connection = await _jira_connection(db_session, project)
    assert connection.id is not None
    payload = {"issue": _issue("10001", "PLAT-1", "In Progress", "2026-05-02T10:00:00.000+0000")}

    await worker.process_webhook({}, connection.id, payload)
    await worker.process_webhook({}, connection.id, payload)

    async with TestSession() as session:
        count = (await session.execute(select(func.count()).select_from(Task))).scalar()
        task = (await session.execute(select(Task))).scalars().one()
    assert count == 1
    assert task.status == "In Progress"
