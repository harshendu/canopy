import pytest

from app.core.security import hash_password
from app.models.base import DocKind, DocScope, DocSource, Provider, UserRole
from app.models.doc import DocReference
from app.models.integration import Connection, ExternalRef, PullRequest
from app.models.user import User
from app.services.links import jira_browse_url


def test_jira_browse_url_builds_site_link() -> None:
    assert (
        jira_browse_url("https://helix.atlassian.net", "HELIX-101")
        == "https://helix.atlassian.net/browse/HELIX-101"
    )
    # trailing slash is normalized
    assert (
        jira_browse_url("https://helix.atlassian.net/", "HELIX-101")
        == "https://helix.atlassian.net/browse/HELIX-101"
    )


def test_jira_browse_url_none_when_unbuildable() -> None:
    assert jira_browse_url(None, "HELIX-1") is None
    assert jira_browse_url("", "HELIX-1") is None
    # OAuth connections store the non-browsable API base — no site host to link to.
    assert jira_browse_url("https://api.atlassian.com/ex/jira/abc-123", "HELIX-1") is None


async def _seed_admin(session) -> None:
    session.add(
        User(
            email="architect@example.com",
            hashed_password=hash_password("secret123"),
            role=UserRole.admin,
        )
    )
    await session.commit()


async def _token(client) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "architect@example.com", "password": "secret123"},
    )
    return resp.json()["access_token"]


@pytest.mark.asyncio
async def test_task_links_endpoint(client, db_session) -> None:
    await _seed_admin(db_session)
    headers = {"Authorization": f"Bearer {await _token(client)}"}
    project_id = (
        await client.post(
            "/api/v1/projects", json={"key": "PLAT", "name": "Platform"}, headers=headers
        )
    ).json()["id"]
    task_id = (
        await client.post(
            "/api/v1/tasks",
            json={"project_id": project_id, "name": "Wire gateway", "duration": 3},
            headers=headers,
        )
    ).json()["id"]

    db_session.add(
        Connection(
            provider=Provider.jira,
            name="Jira",
            config={"base_url": "https://helix.atlassian.net"},
        )
    )
    db_session.add(
        ExternalRef(
            provider=Provider.jira,
            external_id="910105",
            external_key="HELIX-105",
            entity_type="task",
            entity_id=task_id,
        )
    )
    db_session.add(
        PullRequest(
            repo="helix-io/data-plane",
            number=318,
            title="Wire secure gateway",
            state="open",
            url="https://github.com/helix-io/data-plane/pull/318",
            task_id=task_id,
        )
    )
    db_session.add(
        DocReference(
            scope_level=DocScope.task,
            scope_id=task_id,
            kind=DocKind.runbook,
            title="Gateway notes",
            url="https://github.com/helix-io/data-plane/blob/main/docs/gateway.md",
            source=DocSource.repo,
        )
    )
    await db_session.commit()

    resp = await client.get(f"/api/v1/tasks/{task_id}/links", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["jira"] == {
        "key": "HELIX-105",
        "url": "https://helix.atlassian.net/browse/HELIX-105",
    }
    assert [pr["number"] for pr in body["pull_requests"]] == [318]
    assert body["pull_requests"][0]["task_id"] == task_id
    assert [d["source"] for d in body["docs"]] == ["repo"]


@pytest.mark.asyncio
async def test_task_links_empty_and_404(client, db_session) -> None:
    await _seed_admin(db_session)
    headers = {"Authorization": f"Bearer {await _token(client)}"}
    project_id = (
        await client.post(
            "/api/v1/projects", json={"key": "PLAT", "name": "Platform"}, headers=headers
        )
    ).json()["id"]
    task_id = (
        await client.post(
            "/api/v1/tasks",
            json={"project_id": project_id, "name": "Lonely task", "duration": 1},
            headers=headers,
        )
    ).json()["id"]

    resp = await client.get(f"/api/v1/tasks/{task_id}/links", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {"jira": None, "pull_requests": [], "docs": []}

    missing = await client.get("/api/v1/tasks/999999/links", headers=headers)
    assert missing.status_code == 404
