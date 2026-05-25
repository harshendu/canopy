"""MCP-orchestrated ingest (Phase 3): Claude pushes external data into canopy idempotently.

Covers issue ingest → tasks (idempotent, epic→summary, parent wiring), PR ingest → cache, the
draft push write-back, and that ingest/record-push are planner-gated but allowed for agent-scope
tokens (internal two-way-door writes), unlike the direct external push.
"""

import pytest
from sqlmodel import func, select

from app.core.security import hash_password
from app.models.base import Provider, UserRole
from app.models.draft import DraftPlan, DraftTask
from app.models.integration import Connection, PullRequest
from app.models.project import Project, Task
from app.models.user import User
from app.schemas.entities import IngestIssue, IngestPullRequest
from app.services import ingest


async def _project_and_jira(session) -> tuple[Project, Connection]:
    project = Project(key="PLAT", name="Platform")
    session.add(project)
    await session.flush()
    conn = Connection(provider=Provider.jira, name="jira", config={"project_id": project.id})
    session.add(conn)
    await session.flush()
    return project, conn


def _issue(ext_id, key, issue_type, updated, parent=None) -> IngestIssue:
    return IngestIssue(
        external_id=ext_id,
        external_key=key,
        summary=f"Issue {key}",
        status="To Do",
        issue_type=issue_type,
        parent_external_id=parent,
        updated=updated,
    )


# --- issue ingest (service) ---
@pytest.mark.asyncio
async def test_ingest_issues_idempotent_with_parents(db_session) -> None:
    _, conn = await _project_and_jira(db_session)
    issues = [
        _issue("1", "PLAT-1", "Epic", "2026-05-01T10:00:00.000+0000"),
        _issue("2", "PLAT-2", "Story", "2026-05-01T10:00:00.000+0000", parent="1"),
    ]
    first = await ingest.ingest_issues(db_session, conn, issues)
    assert (first.created, first.updated, first.skipped) == (2, 0, 0)

    tasks = (await db_session.execute(select(Task))).scalars().all()
    by_key = {t.name: t for t in tasks}
    epic = by_key["Issue PLAT-1"]
    story = by_key["Issue PLAT-2"]
    assert epic.type.value == "summary"  # epics become summary tasks
    assert story.parent_id == epic.id  # parent wired via ExternalRef

    # Re-ingest with the same `updated` → all skipped, no duplicates.
    again = await ingest.ingest_issues(db_session, conn, issues)
    assert again.skipped == 2
    count = (await db_session.execute(select(func.count()).select_from(Task))).scalar()
    assert count == 2


@pytest.mark.asyncio
async def test_ingest_issues_requires_configured_project(db_session) -> None:
    conn = Connection(provider=Provider.jira, name="jira", config={})
    db_session.add(conn)
    await db_session.flush()
    with pytest.raises(ValueError, match="project_id"):
        await ingest.ingest_issues(db_session, conn, [_issue("1", "X-1", "Story", "t")])


# --- PR ingest (service) ---
@pytest.mark.asyncio
async def test_ingest_pull_requests_idempotent(db_session) -> None:
    conn = Connection(
        provider=Provider.github, name="gh", config={"owner": "acme", "repo": "platform"}
    )
    db_session.add(conn)
    await db_session.flush()

    pr = IngestPullRequest(number=7, title="Add auth", state="open", author="dev", updated="t1")
    res = await ingest.ingest_pull_requests(db_session, conn, [pr])
    assert (res.created, res.updated) == (1, 0)

    pr2 = IngestPullRequest(number=7, title="Add auth (rev)", state="closed", updated="t2")
    res2 = await ingest.ingest_pull_requests(db_session, conn, [pr2])
    assert (res2.created, res2.updated) == (0, 1)

    rows = (await db_session.execute(select(PullRequest))).scalars().all()
    assert len(rows) == 1 and rows[0].state == "closed" and rows[0].repo == "acme/platform"


# --- endpoints: gating + agent-scope access ---
async def _seed(session) -> None:
    session.add_all(
        [
            User(
                email="arch@e.com",
                hashed_password=hash_password("secret123"),
                role=UserRole.architect,
            ),
            User(
                email="eng@e.com",
                hashed_password=hash_password("secret123"),
                role=UserRole.engineer,
            ),
        ]
    )
    await session.commit()


async def _headers(client, email: str) -> dict[str, str]:
    resp = await client.post(
        "/api/v1/auth/login", data={"username": email, "password": "secret123"}
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _agent_headers(client, full: dict[str, str]) -> dict[str, str]:
    resp = await client.post("/api/v1/auth/agent-token", json={}, headers=full)
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.mark.asyncio
async def test_ingest_endpoint_planner_gated_and_agent_allowed(client, db_session) -> None:
    await _seed(db_session)
    _, conn = await _project_and_jira(db_session)
    await db_session.commit()
    body = {"issues": [{"external_id": "1", "external_key": "PLAT-1", "summary": "S"}]}
    url = f"/api/v1/connectors/connections/{conn.id}/ingest/issues"

    eng = await _headers(client, "eng@e.com")
    assert (await client.post(url, json=body, headers=eng)).status_code == 403

    arch = await _headers(client, "arch@e.com")
    assert (await client.post(url, json=body, headers=arch)).status_code == 200

    # An agent-scope token may ingest — it's an internal two-way-door write (not HumanOnly).
    agent = await _agent_headers(client, arch)
    assert (await client.post(url, json=body, headers=agent)).status_code == 200


@pytest.mark.asyncio
async def test_ingest_pull_requests_endpoint_rejects_non_github(client, db_session) -> None:
    await _seed(db_session)
    _, jira = await _project_and_jira(db_session)
    await db_session.commit()
    arch = await _headers(client, "arch@e.com")
    resp = await client.post(
        f"/api/v1/connectors/connections/{jira.id}/ingest/pull-requests",
        json={"pull_requests": []},
        headers=arch,
    )
    assert resp.status_code == 400


# --- draft push write-back ---
@pytest.mark.asyncio
async def test_record_draft_push_stamps_and_syncs(client, db_session) -> None:
    await _seed(db_session)
    project = Project(key="PLAT", name="Platform")
    db_session.add(project)
    await db_session.flush()
    plan = DraftPlan(project_id=project.id, title="Plan", status="draft")
    db_session.add(plan)
    await db_session.flush()
    task = DraftTask(plan_id=plan.id, name="Build X", type="task", estimate_days=2, sort_order=0)
    db_session.add(task)
    await db_session.commit()

    arch = await _headers(client, "arch@e.com")
    body = {"results": [{"draft_task_id": task.id, "jira_issue_id": "10001", "jira_key": "PLAT-9"}]}
    # Agent-scope tokens are allowed (internal write-back, unlike the human-only direct push).
    agent = await _agent_headers(client, arch)
    resp = await client.post(
        f"/api/v1/draft-plans/{plan.id}/record-push", json=body, headers=agent
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"plan_id": plan.id, "recorded": 1, "status": "synced"}

    await db_session.refresh(task)
    await db_session.refresh(plan)
    assert task.jira_issue_id == "10001" and task.jira_key == "PLAT-9"
    assert plan.status == "synced"

    # Idempotent: re-recording the same ids is safe.
    assert (
        await client.post(f"/api/v1/draft-plans/{plan.id}/record-push", json=body, headers=agent)
    ).status_code == 200
