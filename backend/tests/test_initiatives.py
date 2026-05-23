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
async def test_initiative_crud_and_rollup(client, db_session):
    await _seed_admin(db_session)
    headers = {"Authorization": f"Bearer {await _token(client)}"}

    init = await client.post(
        "/api/v1/initiatives",
        json={
            "key": "Q3-PLATFORM",
            "name": "Q3 Platform",
            "outcome_statement": "Ship multi-tenant platform",
            "target_date": "2026-03-01",
        },
        headers=headers,
    )
    assert init.status_code == 201, init.text
    initiative_id = init.json()["id"]

    # Duplicate key is rejected.
    dup = await client.post(
        "/api/v1/initiatives", json={"key": "Q3-PLATFORM", "name": "x"}, headers=headers
    )
    assert dup.status_code == 409

    # One project linked at creation, one linked afterward via PATCH.
    p1 = (
        await client.post(
            "/api/v1/projects",
            json={"key": "ALPHA", "name": "Alpha", "initiative_id": initiative_id},
            headers=headers,
        )
    ).json()
    assert p1["initiative_id"] == initiative_id
    p2 = (
        await client.post(
            "/api/v1/projects", json={"key": "BETA", "name": "Beta"}, headers=headers
        )
    ).json()
    linked = await client.patch(
        f"/api/v1/projects/{p2['id']}",
        json={"initiative_id": initiative_id},
        headers=headers,
    )
    assert linked.json()["initiative_id"] == initiative_id

    # A task on Alpha that ends past its deadline (schedule risk) + a proposed decision.
    task = (
        await client.post(
            "/api/v1/tasks",
            json={"project_id": p1["id"], "name": "Ship", "duration": 3},
            headers=headers,
        )
    ).json()
    await client.patch(
        f"/api/v1/tasks/{task['id']}",
        json={"deadline": "2026-01-01", "end": "2026-02-01"},
        headers=headers,
    )
    await client.post(
        "/api/v1/architecture/adrs",
        json={"project_id": p1["id"], "title": "Pick datastore"},  # status proposed
        headers=headers,
    )

    rollup = (
        await client.get(f"/api/v1/initiatives/{initiative_id}/rollup", headers=headers)
    ).json()
    assert {p["key"] for p in rollup["projects"]} == {"ALPHA", "BETA"}
    assert rollup["open_decisions"] == 1  # the proposed ADR
    # The riskiest sub-project (Alpha, with a deadline miss) drives initiative risk.
    alpha = next(p for p in rollup["projects"] if p["key"] == "ALPHA")
    assert rollup["risk_score"] == max(p["risk_score"] for p in rollup["projects"])
    assert rollup["risk_score"] == alpha["risk_score"]
    assert rollup["risk_level"] == alpha["risk_level"]
    assert rollup["initiative"]["key"] == "Q3-PLATFORM"

    # Deleting the initiative unlinks its projects rather than deleting them.
    assert (
        await client.delete(f"/api/v1/initiatives/{initiative_id}", headers=headers)
    ).status_code == 204
    still_there = await client.get(f"/api/v1/projects/{p1['id']}", headers=headers)
    assert still_there.status_code == 200
    assert still_there.json()["initiative_id"] is None


async def _make_task(client, headers, project_id: int, name: str, duration: int) -> int:
    resp = await client.post(
        "/api/v1/tasks",
        json={"project_id": project_id, "name": name, "duration": duration},
        headers=headers,
    )
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_cross_project_dependency_and_critical_path(client, db_session):
    await _seed_admin(db_session)
    headers = {"Authorization": f"Bearer {await _token(client)}"}

    init_id = (
        await client.post(
            "/api/v1/initiatives", json={"key": "INIT", "name": "Init"}, headers=headers
        )
    ).json()["id"]
    a = (
        await client.post(
            "/api/v1/projects",
            json={"key": "A", "name": "A", "initiative_id": init_id},
            headers=headers,
        )
    ).json()["id"]
    b = (
        await client.post(
            "/api/v1/projects",
            json={"key": "B", "name": "B", "initiative_id": init_id},
            headers=headers,
        )
    ).json()["id"]
    # An UNlinked project — used to prove cross-initiative deps are rejected.
    loose = (
        await client.post(
            "/api/v1/projects", json={"key": "LOOSE", "name": "Loose"}, headers=headers
        )
    ).json()["id"]

    a1 = await _make_task(client, headers, a, "A1", 3)
    a2 = await _make_task(client, headers, a, "A2", 2)
    b1 = await _make_task(client, headers, b, "B1", 5)
    loose_t = await _make_task(client, headers, loose, "L1", 1)

    # Intra-project + a cross-project hand-off within the initiative are allowed.
    assert (
        await client.post(
            "/api/v1/dependencies",
            json={"predecessor_id": a1, "successor_id": a2},
            headers=headers,
        )
    ).status_code == 201
    handoff = await client.post(
        "/api/v1/dependencies",
        json={"predecessor_id": a2, "successor_id": b1},  # A -> B, same initiative
        headers=headers,
    )
    assert handoff.status_code == 201, handoff.text

    # A cross-project edge to a project outside the initiative is rejected.
    bad = await client.post(
        "/api/v1/dependencies",
        json={"predecessor_id": b1, "successor_id": loose_t},
        headers=headers,
    )
    assert bad.status_code == 400

    cp = (
        await client.get(f"/api/v1/initiatives/{init_id}/critical-path", headers=headers)
    ).json()
    assert cp["spans_projects"] is True
    assert cp["total_working_days"] == 10  # 3 + 2 + 5
    assert [t["name"] for t in cp["tasks"]] == ["A1", "A2", "B1"]
    assert len(cp["handoffs"]) == 1
    assert cp["handoffs"][0]["from_project_key"] == "A"
    assert cp["handoffs"][0]["to_project_key"] == "B"
