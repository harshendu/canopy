import pytest

from app.core.security import hash_password
from app.models.base import UserRole
from app.models.user import User


async def _seed_admin(session) -> None:
    session.add(
        User(
            email="admin@example.com",
            hashed_password=hash_password("secret123"),
            role=UserRole.admin,
        )
    )
    await session.commit()


async def _token(client, email: str, password: str = "pw12345678") -> str:
    resp = await client.post(
        "/api/v1/auth/login", data={"username": email, "password": password}
    )
    return resp.json()["access_token"]


def _hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def actors(client, db_session):
    """Seed an admin + one user per role; return {role: headers} and the admin's id map."""
    await _seed_admin(db_session)
    admin = _hdr(await _token(client, "admin@example.com", "secret123"))
    headers = {"admin": admin}
    ids: dict[str, int] = {}
    for role in ("architect", "engineering_manager", "engineer", "viewer"):
        created = await client.post(
            "/api/v1/auth/register",
            json={"email": f"{role}@example.com", "password": "pw12345678", "role": role},
            headers=admin,
        )
        ids[role] = created.json()["id"]
        headers[role] = _hdr(await _token(client, f"{role}@example.com"))
    return headers, ids


@pytest.mark.asyncio
async def test_reads_open_to_everyone_incl_viewer(client, actors):
    headers, _ = actors
    for role in ("admin", "architect", "engineering_manager", "engineer", "viewer"):
        resp = await client.get("/api/v1/projects/portfolio", headers=headers[role])
        assert resp.status_code == 200, f"{role} should read portfolio"


@pytest.mark.asyncio
async def test_project_writes_admin_and_architect_only(client, actors):
    headers, _ = actors
    body = {"key": "PLAT", "name": "Platform"}
    assert (
        await client.post("/api/v1/projects", json=body, headers=headers["architect"])
    ).status_code == 201
    for role in ("engineering_manager", "engineer", "viewer"):
        resp = await client.post(
            "/api/v1/projects", json={"key": f"P{role[:3]}", "name": "x"}, headers=headers[role]
        )
        assert resp.status_code == 403, f"{role} must not create projects"


@pytest.mark.asyncio
async def test_plan_writes_need_planner_role(client, actors):
    headers, _ = actors
    project_id = (
        await client.post(
            "/api/v1/projects", json={"key": "PLAT", "name": "Platform"}, headers=headers["admin"]
        )
    ).json()["id"]
    task_body = {"project_id": project_id, "name": "Build"}
    # engineering_manager (planner) can create a task; engineer/viewer cannot.
    assert (
        await client.post("/api/v1/tasks", json=task_body, headers=headers["engineering_manager"])
    ).status_code == 201
    assert (
        await client.post("/api/v1/tasks", json=task_body, headers=headers["engineer"])
    ).status_code == 403
    assert (
        await client.post("/api/v1/tasks", json=task_body, headers=headers["viewer"])
    ).status_code == 403


@pytest.mark.asyncio
async def test_engineer_may_edit_only_their_own_task(client, actors):
    headers, ids = actors
    admin = headers["admin"]
    project_id = (
        await client.post(
            "/api/v1/projects", json={"key": "PLAT", "name": "Platform"}, headers=admin
        )
    ).json()["id"]
    # Link an engineer record to the engineer login.
    eng_id = (
        await client.post(
            "/api/v1/team/engineers",
            json={"name": "Ada", "user_id": ids["engineer"]},
            headers=admin,
        )
    ).json()["id"]
    mine = (
        await client.post(
            "/api/v1/tasks",
            json={"project_id": project_id, "name": "Mine", "assignee_engineer_id": eng_id},
            headers=admin,
        )
    ).json()["id"]
    theirs = (
        await client.post(
            "/api/v1/tasks", json={"project_id": project_id, "name": "Theirs"}, headers=admin
        )
    ).json()["id"]

    ok = await client.patch(
        f"/api/v1/tasks/{mine}", json={"percent_complete": 50}, headers=headers["engineer"]
    )
    assert ok.status_code == 200, ok.text
    nope = await client.patch(
        f"/api/v1/tasks/{theirs}", json={"percent_complete": 50}, headers=headers["engineer"]
    )
    assert nope.status_code == 403


@pytest.mark.asyncio
async def test_adr_engineer_can_propose_and_comment_but_not_accept(client, actors):
    headers, _ = actors
    project_id = (
        await client.post(
            "/api/v1/projects", json={"key": "PLAT", "name": "Platform"}, headers=headers["admin"]
        )
    ).json()["id"]

    # Engineer can propose an ADR.
    proposed = await client.post(
        "/api/v1/architecture/adrs",
        json={"project_id": project_id, "title": "Use queue"},
        headers=headers["engineer"],
    )
    assert proposed.status_code == 201, proposed.text
    adr_id = proposed.json()["id"]

    # Viewer cannot propose.
    assert (
        await client.post(
            "/api/v1/architecture/adrs",
            json={"project_id": project_id, "title": "nope"},
            headers=headers["viewer"],
        )
    ).status_code == 403

    # Engineer can comment...
    assert (
        await client.post(
            f"/api/v1/architecture/adrs/{adr_id}/comments",
            json={"body": "looks good", "kind": "approve"},
            headers=headers["engineer"],
        )
    ).status_code == 201
    # ...but cannot move the decision's status.
    assert (
        await client.patch(
            f"/api/v1/architecture/adrs/{adr_id}",
            json={"status": "accepted"},
            headers=headers["engineer"],
        )
    ).status_code == 403
    # An engineering manager can.
    accepted = await client.patch(
        f"/api/v1/architecture/adrs/{adr_id}",
        json={"status": "accepted"},
        headers=headers["engineering_manager"],
    )
    assert accepted.status_code == 200, accepted.text


@pytest.mark.asyncio
async def test_risk_mitigations_need_planner_role(client, actors):
    headers, _ = actors
    project_id = (
        await client.post(
            "/api/v1/projects", json={"key": "PLAT", "name": "Platform"}, headers=headers["admin"]
        )
    ).json()["id"]
    body = {"indicator_key": "deadline_violations", "note": "on it"}
    assert (
        await client.post(
            f"/api/v1/projects/{project_id}/risk/mitigations",
            json=body,
            headers=headers["engineer"],
        )
    ).status_code == 403
    assert (
        await client.post(
            f"/api/v1/projects/{project_id}/risk/mitigations",
            json=body,
            headers=headers["engineering_manager"],
        )
    ).status_code == 201
