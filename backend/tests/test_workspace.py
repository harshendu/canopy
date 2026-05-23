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
async def test_me_workspace_surfaces_assigned_tasks_and_owned_decisions(client, db_session):
    await _seed_admin(db_session)
    headers = {"Authorization": f"Bearer {await _token(client)}"}

    me = (await client.get("/api/v1/auth/me", headers=headers)).json()
    user_id = me["id"]

    # An engineer linked to the logged-in user.
    eng = await client.post(
        "/api/v1/team/engineers",
        json={
            "name": "Ada",
            "user_id": user_id,
            "skill_tags": ["python", "infra"],
            "github_login": "ada",
            "committed_hours_per_week": 30,
        },
        headers=headers,
    )
    assert eng.status_code == 201, eng.text
    eng_id = eng.json()["id"]
    assert eng.json()["skill_tags"] == ["python", "infra"]

    project_id = (
        await client.post(
            "/api/v1/projects", json={"key": "PLAT", "name": "Platform"}, headers=headers
        )
    ).json()["id"]
    # A task assigned to this engineer.
    await client.post(
        "/api/v1/tasks",
        json={"project_id": project_id, "name": "Build API", "assignee_engineer_id": eng_id},
        headers=headers,
    )
    # A decision this engineer owns + one they're a stakeholder on.
    await client.post(
        "/api/v1/architecture/adrs",
        json={"project_id": project_id, "title": "Owned ADR", "decision_owner_id": eng_id},
        headers=headers,
    )
    await client.post(
        "/api/v1/architecture/adrs",
        json={"project_id": project_id, "title": "Review ADR", "stakeholder_ids": [eng_id]},
        headers=headers,
    )

    ws = (await client.get("/api/v1/me/workspace", headers=headers)).json()
    assert ws["engineer"]["id"] == eng_id
    assert [t["name"] for t in ws["assigned_tasks"]] == ["Build API"]
    assert [a["title"] for a in ws["owned_decisions"]] == ["Owned ADR"]
    assert [a["title"] for a in ws["stakeholder_decisions"]] == ["Review ADR"]

    # /me/today: the owned ADR is proposed -> a decision to push; the critical-or-due-soon
    # task surfaces as focus.
    today = (await client.get("/api/v1/me/today", headers=headers)).json()
    assert [a["title"] for a in today["decisions_to_push"]] == ["Owned ADR"]
    assert isinstance(today["focus_tasks"], list)


@pytest.mark.asyncio
async def test_me_workspace_without_linked_engineer_is_empty(client, db_session):
    await _seed_admin(db_session)
    headers = {"Authorization": f"Bearer {await _token(client)}"}
    ws = (await client.get("/api/v1/me/workspace", headers=headers)).json()
    assert ws["engineer"] is None
    assert ws["assigned_tasks"] == []
    assert ws["user"]["email"] == "architect@example.com"


@pytest.mark.asyncio
async def test_user_management_roles_and_self_deactivation_guard(client, db_session):
    await _seed_admin(db_session)
    headers = {"Authorization": f"Bearer {await _token(client)}"}

    # Invite an engineer-role user (widened roles).
    created = await client.post(
        "/api/v1/auth/register",
        json={"email": "eng@example.com", "password": "pw12345678", "role": "engineer"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    new_id = created.json()["id"]
    assert created.json()["role"] == "engineer"

    users = (await client.get("/api/v1/auth/users", headers=headers)).json()
    assert {u["email"] for u in users} >= {"architect@example.com", "eng@example.com"}

    # Promote them to engineering_manager.
    promoted = await client.patch(
        f"/api/v1/auth/users/{new_id}",
        json={"role": "engineering_manager"},
        headers=headers,
    )
    assert promoted.status_code == 200 and promoted.json()["role"] == "engineering_manager"

    # The admin can't lock themselves out.
    me = (await client.get("/api/v1/auth/me", headers=headers)).json()
    guard = await client.patch(
        f"/api/v1/auth/users/{me['id']}", json={"is_active": False}, headers=headers
    )
    assert guard.status_code == 400


@pytest.mark.asyncio
async def test_user_management_requires_admin(client, db_session):
    await _seed_admin(db_session)
    headers = {"Authorization": f"Bearer {await _token(client)}"}
    # A non-admin (viewer) cannot list users.
    await client.post(
        "/api/v1/auth/register",
        json={"email": "v@example.com", "password": "pw12345678", "role": "viewer"},
        headers=headers,
    )
    viewer_login = await client.post(
        "/api/v1/auth/login", data={"username": "v@example.com", "password": "pw12345678"}
    )
    viewer_headers = {"Authorization": f"Bearer {viewer_login.json()['access_token']}"}
    forbidden = await client.get("/api/v1/auth/users", headers=viewer_headers)
    assert forbidden.status_code == 403
