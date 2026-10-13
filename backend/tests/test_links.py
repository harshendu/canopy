import pytest

from app.core.security import hash_password
from app.models.base import DocKind, DocScope, DocSource, Provider, UserRole
from app.models.doc import DocReference
from app.models.integration import Connection, ExternalRef, PullRequest
from app.models.user import User
from app.services.links import jira_browse_url


def test_jira_browse_url_builds_site_link() -> None:
    assert (
        jira_browse_url("https://jira.example.com", "SHOP-101")
        == "https://jira.example.com/browse/SHOP-101"
    )
    # trailing slash is normalized
    assert (
        jira_browse_url("https://jira.example.com/", "SHOP-101")
        == "https://jira.example.com/browse/SHOP-101"
    )


def test_jira_browse_url_none_when_unbuildable() -> None:
    assert jira_browse_url(None, "SHOP-1") is None
    assert jira_browse_url("", "SHOP-1") is None
    # OAuth connections store the non-browsable API base — no site host to link to.
    assert jira_browse_url("https://api.atlassian.com/ex/jira/abc-123", "SHOP-1") is None


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
            json={"project_id": project_id, "name": "Integrate payments", "duration": 3},
            headers=headers,
        )
    ).json()["id"]

    db_session.add(
        Connection(
            provider=Provider.jira,
            name="Jira",
            config={"base_url": "https://jira.example.com"},
        )
    )
    db_session.add(
        ExternalRef(
            provider=Provider.jira,
            external_id="930105",
            external_key="SHOP-105",
            entity_type="task",
            entity_id=task_id,
        )
    )
    db_session.add(
        PullRequest(
            repo="example-shop/checkout",
            number=412,
            title="Integrate tokenized card payments",
            state="open",
            url="https://github.com/example-shop/checkout/pull/412",
            task_id=task_id,
        )
    )
    db_session.add(
        DocReference(
            scope_level=DocScope.task,
            scope_id=task_id,
            kind=DocKind.runbook,
            title="Payments integration notes",
            url="https://github.com/example-shop/checkout/blob/main/docs/payments.md",
            source=DocSource.repo,
        )
    )
    await db_session.commit()

    resp = await client.get(f"/api/v1/tasks/{task_id}/links", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["jira"] == {
        "key": "SHOP-105",
        "url": "https://jira.example.com/browse/SHOP-105",
    }
    assert [pr["number"] for pr in body["pull_requests"]] == [412]
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
