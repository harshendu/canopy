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
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_projects_require_auth(client):
    resp = await client.get("/api/v1/projects")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_project_crud_flow(client, db_session):
    await _seed_admin(db_session)
    token = await _token(client)
    headers = {"Authorization": f"Bearer {token}"}

    create = await client.post(
        "/api/v1/projects",
        json={"key": "PLAT", "name": "Platform"},
        headers=headers,
    )
    assert create.status_code == 201, create.text
    project_id = create.json()["id"]

    listing = await client.get("/api/v1/projects", headers=headers)
    assert listing.status_code == 200
    assert any(p["id"] == project_id for p in listing.json())


@pytest.mark.asyncio
async def test_replan_endpoint(client, db_session):
    await _seed_admin(db_session)
    token = await _token(client)
    headers = {"Authorization": f"Bearer {token}"}

    project_id = (
        await client.post(
            "/api/v1/projects",
            json={"key": "PLAT", "name": "Platform", "start_date": "2026-01-01"},
            headers=headers,
        )
    ).json()["id"]

    t1 = (
        await client.post(
            "/api/v1/tasks",
            json={"project_id": project_id, "name": "Design", "duration": 2},
            headers=headers,
        )
    ).json()["id"]
    t2 = (
        await client.post(
            "/api/v1/tasks",
            json={"project_id": project_id, "name": "Build", "duration": 3},
            headers=headers,
        )
    ).json()["id"]
    await client.post(
        "/api/v1/dependencies",
        json={"predecessor_id": t1, "successor_id": t2},
        headers=headers,
    )

    replan = await client.post(f"/api/v1/projects/{project_id}/replan", headers=headers)
    assert replan.status_code == 200, replan.text
    body = replan.json()
    assert body["scheduled_tasks"] == 2
    assert body["project_end"] == "2026-01-06"  # 0 + 2 + 3 days from 2026-01-01


@pytest.mark.asyncio
async def test_portfolio_endpoint(client, db_session):
    await _seed_admin(db_session)
    token = await _token(client)
    headers = {"Authorization": f"Bearer {token}"}

    project_id = (
        await client.post(
            "/api/v1/projects", json={"key": "PLAT", "name": "Platform"}, headers=headers
        )
    ).json()["id"]
    await client.post(
        "/api/v1/tasks",
        json={"project_id": project_id, "name": "Done", "percent_complete": 100},
        headers=headers,
    )
    await client.post(
        "/api/v1/tasks",
        json={"project_id": project_id, "name": "WIP", "percent_complete": 0},
        headers=headers,
    )

    resp = await client.get("/api/v1/projects/portfolio", headers=headers)
    assert resp.status_code == 200, resp.text
    summary = next(p for p in resp.json()["projects"] if p["id"] == project_id)
    assert summary["total_tasks"] == 2
    assert summary["completed_tasks"] == 1
    assert summary["avg_percent_complete"] == 50.0


@pytest.mark.asyncio
async def test_capacity_endpoint(client, db_session):
    await _seed_admin(db_session)
    token = await _token(client)
    headers = {"Authorization": f"Bearer {token}"}

    project_id = (
        await client.post(
            "/api/v1/projects",
            json={"key": "PLAT", "name": "Platform", "start_date": "2026-01-05",
                  "target_date": "2026-01-18"},
            headers=headers,
        )
    ).json()["id"]
    eng_id = (
        await client.post(
            "/api/v1/team/engineers", json={"name": "Ada"}, headers=headers
        )
    ).json()["id"]
    await client.post(
        "/api/v1/team/allocations",
        json={"engineer_id": eng_id, "project_id": project_id, "percent_allocation": 60,
              "start_date": "2026-01-05", "end_date": "2026-01-18"},
        headers=headers,
    )

    resp = await client.get(f"/api/v1/team/capacity?project_id={project_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["weeks"]) == 2
    row = body["rows"][0]
    assert row["engineer_name"] == "Ada"
    assert row["cells"]["2026-01-05"] == 60.0


@pytest.mark.asyncio
async def test_baseline_snapshot(client, db_session):
    await _seed_admin(db_session)
    token = await _token(client)
    headers = {"Authorization": f"Bearer {token}"}

    project_id = (
        await client.post(
            "/api/v1/projects",
            json={"key": "PLAT", "name": "Platform", "start_date": "2026-01-01"},
            headers=headers,
        )
    ).json()["id"]
    await client.post(
        "/api/v1/tasks",
        json={"project_id": project_id, "name": "Design", "duration": 2},
        headers=headers,
    )
    await client.post(f"/api/v1/projects/{project_id}/replan", headers=headers)

    base = await client.post(f"/api/v1/projects/{project_id}/baseline", headers=headers)
    assert base.status_code == 200, base.text
    assert base.json()["baselined"] == 1

    gantt = (await client.get(f"/api/v1/projects/{project_id}/gantt", headers=headers)).json()
    task = gantt["tasks"][0]
    assert task["baseline_start"] == task["start_date"]
    assert task["baseline_end"] == task["end_date"]


@pytest.mark.asyncio
async def test_adr_component_links(client, db_session):
    await _seed_admin(db_session)
    token = await _token(client)
    headers = {"Authorization": f"Bearer {token}"}

    project_id = (
        await client.post(
            "/api/v1/projects", json={"key": "PLAT", "name": "Platform"}, headers=headers
        )
    ).json()["id"]
    comp_id = (
        await client.post(
            "/api/v1/architecture/components",
            json={"project_id": project_id, "name": "API", "kind": "service"},
            headers=headers,
        )
    ).json()["id"]
    await client.post(
        "/api/v1/architecture/adrs",
        json={"project_id": project_id, "title": "Use Postgres", "component_ids": [comp_id]},
        headers=headers,
    )

    adrs = (
        await client.get(f"/api/v1/architecture/adrs?project_id={project_id}", headers=headers)
    ).json()
    assert adrs[0]["component_ids"] == [comp_id]
    assert adrs[0]["number"] == 1
