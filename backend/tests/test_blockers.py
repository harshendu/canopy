import pytest

from app.core.security import hash_password
from app.models.base import UserRole
from app.models.user import User


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
async def test_blocker_lifecycle_and_alerts(client, db_session):
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
            json={"project_id": project_id, "name": "Ship API", "duration": 3},
            headers=headers,
        )
    ).json()["id"]

    raised = await client.post(
        f"/api/v1/tasks/{task_id}/blockers",
        json={"reason": "Waiting on infra access"},
        headers=headers,
    )
    assert raised.status_code == 201, raised.text
    blocker_id = raised.json()["id"]
    assert raised.json()["resolved_at"] is None

    # Open blockers list (project-scoped) shows it.
    open_list = (
        await client.get(f"/api/v1/blockers?project_id={project_id}", headers=headers)
    ).json()
    assert [b["id"] for b in open_list] == [blocker_id]

    # It surfaces in the project's alerts digest as a warning.
    alerts = (await client.get(f"/api/v1/projects/{project_id}/alerts", headers=headers)).json()
    blocked = [a for a in alerts["alerts"] if a["kind"] == "blocked"]
    assert len(blocked) == 1
    assert blocked[0]["severity"] == "warning"
    assert blocked[0]["entity_id"] == task_id

    # Resolve it -> drops out of the open list and the digest.
    resolved = await client.patch(
        f"/api/v1/blockers/{blocker_id}", json={"resolved": True}, headers=headers
    )
    assert resolved.status_code == 200
    assert resolved.json()["resolved_at"] is not None
    assert (
        await client.get(f"/api/v1/blockers?project_id={project_id}", headers=headers)
    ).json() == []
    alerts2 = (await client.get(f"/api/v1/projects/{project_id}/alerts", headers=headers)).json()
    assert [a for a in alerts2["alerts"] if a["kind"] == "blocked"] == []


@pytest.mark.asyncio
async def test_blocker_shows_in_my_workspace(client, db_session):
    await _seed_admin(db_session)
    headers = {"Authorization": f"Bearer {await _token(client)}"}
    me = (await client.get("/api/v1/auth/me", headers=headers)).json()

    project_id = (
        await client.post(
            "/api/v1/projects", json={"key": "PLAT", "name": "Platform"}, headers=headers
        )
    ).json()["id"]
    # An engineer linked to my login, assigned a task.
    eng_id = (
        await client.post(
            "/api/v1/team/engineers",
            json={"name": "Me", "user_id": me["id"]},
            headers=headers,
        )
    ).json()["id"]
    task_id = (
        await client.post(
            "/api/v1/tasks",
            json={"project_id": project_id, "name": "My task", "duration": 2},
            headers=headers,
        )
    ).json()["id"]
    await client.patch(
        f"/api/v1/tasks/{task_id}", json={"assignee_engineer_id": eng_id}, headers=headers
    )
    await client.post(
        f"/api/v1/tasks/{task_id}/blockers",
        json={"reason": "Blocked on review"},
        headers=headers,
    )

    ws = (await client.get("/api/v1/me/workspace", headers=headers)).json()
    assert len(ws["blockers"]) == 1
    assert ws["blockers"][0]["task_id"] == task_id
    # raised_by defaulted to my engineer.
    assert ws["blockers"][0]["raised_by_engineer_id"] == eng_id
