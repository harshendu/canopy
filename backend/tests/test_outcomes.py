from datetime import date

import pytest

from app.core.security import hash_password
from app.models.user import User
from app.services import outcomes as outcomes_service
from app.services.retro import RetroInputs, generate_project_retro

# --- pure: progress -------------------------------------------------------------

def test_progress_basic() -> None:
    assert outcomes_service.progress(0, 100, 25) == 0.25
    assert outcomes_service.progress(20, 120, 70) == 0.5  # baseline offset
    assert outcomes_service.progress(None, 10, 5) == 0.5  # baseline defaults to 0


def test_progress_unmeasurable_is_none() -> None:
    assert outcomes_service.progress(0, None, 5) is None
    assert outcomes_service.progress(0, 100, None) is None
    assert outcomes_service.progress(50, 50, 50) is None  # target == baseline


def test_progress_can_exceed_or_go_negative() -> None:
    assert outcomes_service.progress(0, 100, 150) == 1.5  # overshot — honest, not clamped
    assert outcomes_service.progress(0, 100, -10) == -0.1


# --- retro seeder includes outcomes ---------------------------------------------

def test_retro_body_includes_outcomes_section() -> None:
    body = generate_project_retro(
        RetroInputs(
            project_name="Platform",
            generated_on=date(2026, 5, 25),
            outcomes=["Cut p95 latency — 320/200 ms (at_risk)"],
        )
    )
    assert "## Outcomes — did the bet pay off?" in body
    assert "Cut p95 latency — 320/200 ms (at_risk)" in body


# --- API ------------------------------------------------------------------------

async def _seed_admin(session) -> None:
    session.add(
        User(email="a@e.com", hashed_password=hash_password("secret123"), role="admin")
    )
    await session.commit()


async def _token(client) -> str:
    resp = await client.post(
        "/api/v1/auth/login", data={"username": "a@e.com", "password": "secret123"}
    )
    return resp.json()["access_token"]


async def _project(client, headers) -> int:
    return (
        await client.post(
            "/api/v1/projects", json={"key": "PLAT", "name": "Platform"}, headers=headers
        )
    ).json()["id"]


@pytest.mark.asyncio
async def test_outcome_crud_and_progress(client, db_session) -> None:
    await _seed_admin(db_session)
    headers = {"Authorization": f"Bearer {await _token(client)}"}
    project_id = await _project(client, headers)

    created = await client.post(
        "/api/v1/outcomes",
        json={
            "scope_level": "project",
            "scope_id": project_id,
            "statement": "We believe checkout v2 lifts conversion",
            "metric": "checkout conversion rate",
            "unit": "%",
            "baseline_value": 40,
            "target_value": 50,
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    oid = created.json()["id"]
    assert created.json()["status"] == "pending"
    assert created.json()["progress_ratio"] is None  # no current value yet

    recorded = await client.patch(
        f"/api/v1/outcomes/{oid}",
        json={"current_value": 45, "status": "on_track"},
        headers=headers,
    )
    assert recorded.status_code == 200
    assert recorded.json()["progress_ratio"] == 0.5  # (45-40)/(50-40)
    assert recorded.json()["status"] == "on_track"

    listed = await client.get(
        "/api/v1/outcomes",
        params={"scope_level": "project", "scope_id": project_id},
        headers=headers,
    )
    assert len(listed.json()) == 1

    assert (await client.delete(f"/api/v1/outcomes/{oid}", headers=headers)).status_code == 204


@pytest.mark.asyncio
async def test_outcome_rejects_missing_scope(client, db_session) -> None:
    await _seed_admin(db_session)
    headers = {"Authorization": f"Bearer {await _token(client)}"}
    resp = await client.post(
        "/api/v1/outcomes",
        json={"scope_level": "initiative", "scope_id": 999, "statement": "x"},
        headers=headers,
    )
    assert resp.status_code == 404
