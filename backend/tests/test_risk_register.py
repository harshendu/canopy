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


async def _token(client, email: str = "architect@example.com", password: str = "secret123") -> str:
    resp = await client.post(
        "/api/v1/auth/login", data={"username": email, "password": password}
    )
    return resp.json()["access_token"]


async def _project(client, headers) -> int:
    return (
        await client.post(
            "/api/v1/projects", json={"key": "PLAT", "name": "Platform"}, headers=headers
        )
    ).json()["id"]


@pytest.mark.asyncio
async def test_risk_register_crud_and_exposure(client, db_session):
    await _seed_admin(db_session)
    headers = {"Authorization": f"Bearer {await _token(client)}"}
    project_id = await _project(client, headers)

    created = await client.post(
        "/api/v1/risks",
        json={
            "scope_level": "project",
            "scope_id": project_id,
            "title": "Vendor API may slip",
            "category": "external",
            "probability": "high",
            "impact": "high",
            "mitigation": "Weekly sync with vendor",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    risk_id = body["id"]
    # Exposure is computed (3 x 3 = 9, banded to critical), never stored.
    assert body["exposure"] == 9
    assert body["probability_value"] == 3
    assert body["impact_value"] == 3
    assert body["exposure_level"] == "critical"
    assert body["status"] == "open"
    assert body["resolved_at"] is None

    # Filter by scope.
    listed = (
        await client.get(
            f"/api/v1/risks?scope_level=project&scope_id={project_id}", headers=headers
        )
    ).json()
    assert [r["id"] for r in listed] == [risk_id]

    # Update lowers exposure.
    patched = await client.patch(
        f"/api/v1/risks/{risk_id}", json={"impact": "low"}, headers=headers
    )
    assert patched.status_code == 200
    assert patched.json()["exposure"] == 3  # 3 x 1

    # Close stamps resolved_at and appends the note to the mitigation narrative.
    closed = await client.post(
        f"/api/v1/risks/{risk_id}/close",
        json={"status": "resolved", "note": "Vendor delivered"},
        headers=headers,
    )
    assert closed.status_code == 200
    assert closed.json()["status"] == "resolved"
    assert closed.json()["resolved_at"] is not None
    assert "Vendor delivered" in closed.json()["mitigation"]

    # Reopening clears resolved_at.
    reopened = await client.patch(
        f"/api/v1/risks/{risk_id}", json={"status": "open"}, headers=headers
    )
    assert reopened.json()["resolved_at"] is None

    # Delete.
    assert (
        await client.delete(f"/api/v1/risks/{risk_id}", headers=headers)
    ).status_code == 204
    assert (await client.get(f"/api/v1/risks/{risk_id}", headers=headers)).status_code == 404


@pytest.mark.asyncio
async def test_risk_register_validates_scope_target(client, db_session):
    await _seed_admin(db_session)
    headers = {"Authorization": f"Bearer {await _token(client)}"}
    resp = await client.post(
        "/api/v1/risks",
        json={
            "scope_level": "task",
            "scope_id": 99999,
            "title": "Orphan",
            "category": "technical",
        },
        headers=headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_open_register_risks_count_on_portfolio_card(client, db_session):
    await _seed_admin(db_session)
    headers = {"Authorization": f"Bearer {await _token(client)}"}
    project_id = await _project(client, headers)
    for status_value in ("open", "resolved"):
        await client.post(
            "/api/v1/risks",
            json={
                "scope_level": "project",
                "scope_id": project_id,
                "title": f"r-{status_value}",
                "category": "technical",
                "status": status_value,
            },
            headers=headers,
        )
    portfolio = (await client.get("/api/v1/projects/portfolio", headers=headers)).json()
    card = next(p for p in portfolio["projects"] if p["id"] == project_id)
    assert card["open_risks"] == 1  # only the open one counts


@pytest.mark.asyncio
async def test_overdue_register_risk_surfaces_in_alerts_but_not_the_score(client, db_session):
    await _seed_admin(db_session)
    headers = {"Authorization": f"Bearer {await _token(client)}"}
    project_id = await _project(client, headers)

    score_before = (
        await client.get(f"/api/v1/projects/{project_id}/risk", headers=headers)
    ).json()["score"]

    await client.post(
        "/api/v1/risks",
        json={
            "scope_level": "project",
            "scope_id": project_id,
            "title": "Past-due risk",
            "category": "schedule",
            "probability": "high",
            "impact": "high",
            "target_resolution_date": "2020-01-01",
        },
        headers=headers,
    )

    alerts = (await client.get(f"/api/v1/projects/{project_id}/alerts", headers=headers)).json()
    overdue = [a for a in alerts["alerts"] if a["kind"] == "risk_overdue"]
    assert len(overdue) == 1
    assert overdue[0]["severity"] == "error"

    # The register is kept separate from the computed score — it must be unchanged.
    score_after = (
        await client.get(f"/api/v1/projects/{project_id}/risk", headers=headers)
    ).json()["score"]
    assert score_after == score_before


@pytest.mark.asyncio
async def test_viewer_cannot_write_risks(client, db_session):
    await _seed_admin(db_session)
    admin = {"Authorization": f"Bearer {await _token(client)}"}
    project_id = await _project(client, admin)
    await client.post(
        "/api/v1/auth/register",
        json={"email": "viewer@example.com", "password": "pw12345678", "role": "viewer"},
        headers=admin,
    )
    viewer = {"Authorization": f"Bearer {await _token(client, 'viewer@example.com', 'pw12345678')}"}
    resp = await client.post(
        "/api/v1/risks",
        json={
            "scope_level": "project",
            "scope_id": project_id,
            "title": "x",
            "category": "technical",
        },
        headers=viewer,
    )
    assert resp.status_code == 403
