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


async def _project(client, headers) -> int:
    return (
        await client.post(
            "/api/v1/projects", json={"key": "PLAT", "name": "Platform"}, headers=headers
        )
    ).json()["id"]


@pytest.mark.asyncio
async def test_task_tags_and_three_point_estimate_round_trip(client, db_session):
    await _seed_admin(db_session)
    headers = {"Authorization": f"Bearer {await _token(client)}"}
    project_id = await _project(client, headers)

    created = await client.post(
        "/api/v1/tasks",
        json={
            "project_id": project_id,
            "name": "Migrate store",
            "duration": 5,
            "tags": [" Backend ", "DATA", "data"],
            "estimate_optimistic": 3,
            "estimate_likely": 5,
            "estimate_pessimistic": 13,
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    # Tags are normalised (lowercased, deduped, trimmed).
    assert body["tags"] == ["backend", "data"]
    # PERT mean + spread are computed read-only fields.
    assert body["pert_mean"] == round((3 + 4 * 5 + 13) / 6, 1)
    assert body["estimate_spread"] == 10
    # `duration` is NOT moved by the estimate (advisory only).
    assert body["duration"] == 5

    # Estimates with no full triple yield null computed fields.
    plain = await client.post(
        "/api/v1/tasks",
        json={"project_id": project_id, "name": "Plain", "duration": 2},
        headers=headers,
    )
    assert plain.json()["pert_mean"] is None
    assert plain.json()["estimate_spread"] is None


@pytest.mark.asyncio
async def test_wide_estimate_raises_schedule_uncertainty_indicator(client, db_session):
    await _seed_admin(db_session)
    headers = {"Authorization": f"Bearer {await _token(client)}"}
    project_id = await _project(client, headers)
    await client.post(
        "/api/v1/tasks",
        json={
            "project_id": project_id,
            "name": "Spike",
            "estimate_optimistic": 2,
            "estimate_likely": 4,
            "estimate_pessimistic": 20,
        },
        headers=headers,
    )
    risk = (await client.get(f"/api/v1/projects/{project_id}/risk", headers=headers)).json()
    schedule = next(f for f in risk["families"] if f["key"] == "schedule")
    uncertainty = next(i for i in schedule["indicators"] if i["key"] == "estimate_uncertainty")
    assert uncertainty["score"] > 0


@pytest.mark.asyncio
async def test_project_health_stamps_updated_at(client, db_session):
    await _seed_admin(db_session)
    headers = {"Authorization": f"Bearer {await _token(client)}"}
    project_id = await _project(client, headers)
    assert (await client.get(f"/api/v1/projects/{project_id}", headers=headers)).json()[
        "status_updated_at"
    ] is None

    patched = await client.patch(
        f"/api/v1/projects/{project_id}",
        json={"health": "at_risk", "status_note": "Awaiting vendor"},
        headers=headers,
    )
    assert patched.status_code == 200
    assert patched.json()["health"] == "at_risk"
    assert patched.json()["status_note"] == "Awaiting vendor"
    assert patched.json()["status_updated_at"] is not None

    # The portfolio card carries the human health + tags.
    await client.patch(
        f"/api/v1/projects/{project_id}", json={"tags": ["Q3", "platform"]}, headers=headers
    )
    portfolio = (await client.get("/api/v1/projects/portfolio", headers=headers)).json()
    card = next(p for p in portfolio["projects"] if p["id"] == project_id)
    assert card["health"] == "at_risk"
    assert card["tags"] == ["q3", "platform"]


@pytest.mark.asyncio
async def test_blocker_enrichment_round_trip_and_alert_severity(client, db_session):
    await _seed_admin(db_session)
    headers = {"Authorization": f"Bearer {await _token(client)}"}
    project_id = await _project(client, headers)
    task_id = (
        await client.post(
            "/api/v1/tasks",
            json={"project_id": project_id, "name": "Ship", "duration": 2},
            headers=headers,
        )
    ).json()["id"]

    raised = await client.post(
        f"/api/v1/tasks/{task_id}/blockers",
        json={
            "reason": "Infra access pending",
            "category": "external",
            "severity": "critical",
            "needed_by": "2026-06-01",
        },
        headers=headers,
    )
    assert raised.status_code == 201, raised.text
    assert raised.json()["category"] == "external"
    assert raised.json()["severity"] == "critical"
    assert raised.json()["needed_by"] == "2026-06-01"

    # Critical severity escalates the digest alert to an error.
    alerts = (await client.get(f"/api/v1/projects/{project_id}/alerts", headers=headers)).json()
    blocked = next(a for a in alerts["alerts"] if a["kind"] == "blocked")
    assert blocked["severity"] == "error"
    assert "needed by 2026-06-01" in blocked["message"]

    # Patch the category and confirm it persists (and resolved special-case still works).
    patched = await client.patch(
        f"/api/v1/blockers/{raised.json()['id']}",
        json={"category": "decision", "severity": "low"},
        headers=headers,
    )
    assert patched.json()["category"] == "decision"
    assert patched.json()["severity"] == "low"
    assert patched.json()["resolved_at"] is None


@pytest.mark.asyncio
async def test_initiative_tags_and_health(client, db_session):
    await _seed_admin(db_session)
    headers = {"Authorization": f"Bearer {await _token(client)}"}
    init_id = (
        await client.post(
            "/api/v1/initiatives",
            json={"key": "Q3-PLAT", "name": "Platform Q3", "tags": ["Strategic"]},
            headers=headers,
        )
    ).json()["id"]
    assert (
        await client.get(f"/api/v1/initiatives/{init_id}", headers=headers)
    ).json()["tags"] == ["strategic"]

    patched = await client.patch(
        f"/api/v1/initiatives/{init_id}",
        json={"health": "on_track", "status_note": "Green"},
        headers=headers,
    )
    assert patched.json()["health"] == "on_track"
    assert patched.json()["status_updated_at"] is not None
