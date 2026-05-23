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
async def test_health_ready(client):
    resp = await client.get("/api/v1/health/ready")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"


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
async def test_capacity_org_wide_sums_across_projects(client, db_session):
    await _seed_admin(db_session)
    token = await _token(client)
    headers = {"Authorization": f"Bearer {token}"}

    async def make_project(key: str) -> int:
        resp = await client.post(
            "/api/v1/projects",
            json={"key": key, "name": key, "start_date": "2026-01-05",
                  "target_date": "2026-01-11"},
            headers=headers,
        )
        return resp.json()["id"]

    p1 = await make_project("ALPHA")
    p2 = await make_project("BETA")
    eng_id = (
        await client.post("/api/v1/team/engineers", json={"name": "Ada"}, headers=headers)
    ).json()["id"]
    for pid in (p1, p2):
        await client.post(
            "/api/v1/team/allocations",
            json={"engineer_id": eng_id, "project_id": pid, "percent_allocation": 60,
                  "start_date": "2026-01-05", "end_date": "2026-01-11"},
            headers=headers,
        )

    # Per project: 60% — looks fine. Org-wide: 120% — over-allocated.
    per_project = (
        await client.get(f"/api/v1/team/capacity?project_id={p1}", headers=headers)
    ).json()
    assert per_project["rows"][0]["cells"]["2026-01-05"] == 60.0

    org = (await client.get("/api/v1/team/capacity", headers=headers)).json()
    assert org["project_id"] is None
    row = org["rows"][0]
    assert row["cells"]["2026-01-05"] == 120.0
    assert row["projects"] == ["ALPHA", "BETA"]


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


async def _project_with_task(client, headers, **task_fields):
    project_id = (
        await client.post(
            "/api/v1/projects",
            json={"key": "PLAT", "name": "Platform", "start_date": "2026-01-05"},
            headers=headers,
        )
    ).json()["id"]
    task_id = (
        await client.post(
            "/api/v1/tasks",
            json={"project_id": project_id, "name": "Build", "duration": 2, **task_fields},
            headers=headers,
        )
    ).json()["id"]
    return project_id, task_id


@pytest.mark.asyncio
async def test_whatif_does_not_persist(client, db_session):
    await _seed_admin(db_session)
    token = await _token(client)
    headers = {"Authorization": f"Bearer {token}"}
    project_id, task_id = await _project_with_task(client, headers)
    await client.post(f"/api/v1/projects/{project_id}/replan", headers=headers)

    resp = await client.post(
        f"/api/v1/projects/{project_id}/whatif",
        json={"duration_overrides": {str(task_id): 10}},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["project_end"] == "2026-01-15"  # 2026-01-05 + 10 days, projected

    task = (await client.get(f"/api/v1/tasks/{task_id}", headers=headers)).json()
    assert task["duration"] == 2  # unchanged — what-if was not persisted


@pytest.mark.asyncio
async def test_deadline_violation_reported(client, db_session):
    await _seed_admin(db_session)
    token = await _token(client)
    headers = {"Authorization": f"Bearer {token}"}
    project_id, task_id = await _project_with_task(
        client, headers, duration=5, deadline="2026-01-06"
    )
    replan = await client.post(f"/api/v1/projects/{project_id}/replan", headers=headers)
    assert task_id in replan.json()["deadline_violations"]


@pytest.mark.asyncio
async def test_skip_weekends_extends_schedule(client, db_session):
    await _seed_admin(db_session)
    token = await _token(client)
    headers = {"Authorization": f"Bearer {token}"}
    project_id, _ = await _project_with_task(client, headers, duration=5)
    await client.patch(
        f"/api/v1/projects/{project_id}", json={"skip_weekends": True}, headers=headers
    )
    replan = await client.post(f"/api/v1/projects/{project_id}/replan", headers=headers)
    # 5 working days from Mon 2026-01-05 skips the weekend -> ends Mon 2026-01-12.
    assert replan.json()["project_end"] == "2026-01-12"


@pytest.mark.asyncio
async def test_adr_impact(client, db_session):
    await _seed_admin(db_session)
    token = await _token(client)
    headers = {"Authorization": f"Bearer {token}"}
    project_id = (
        await client.post(
            "/api/v1/projects", json={"key": "PLAT", "name": "Platform"}, headers=headers
        )
    ).json()["id"]

    async def comp(name: str) -> int:
        return (
            await client.post(
                "/api/v1/architecture/components",
                json={"project_id": project_id, "name": name},
                headers=headers,
            )
        ).json()["id"]

    a, b, c = await comp("A"), await comp("B"), await comp("C")
    # A depends on B, C depends on A.
    for source, target in [(a, b), (c, a)]:
        await client.post(
            "/api/v1/architecture/component-links",
            json={"source_id": source, "target_id": target},
            headers=headers,
        )
    adr_id = (
        await client.post(
            "/api/v1/architecture/adrs",
            json={"project_id": project_id, "title": "Change B", "component_ids": [b]},
            headers=headers,
        )
    ).json()["id"]

    impact = (
        await client.get(f"/api/v1/architecture/adrs/{adr_id}/impact", headers=headers)
    ).json()
    assert impact["direct_component_ids"] == [b]
    assert sorted(impact["downstream_component_ids"]) == sorted([a, c])
