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


@pytest.mark.asyncio
async def test_activity_ingest_feed_and_incident_autoopens_postmortem(client, db_session):
    await _seed_admin(db_session)
    headers = {"Authorization": f"Bearer {await _token(client)}"}
    project_id = (
        await client.post(
            "/api/v1/projects", json={"key": "PLAT", "name": "Platform"}, headers=headers
        )
    ).json()["id"]

    # A deploy and a build failure land in the feed.
    for kind, summary in [("deploy", "v1.2 to prod"), ("build_failure", "CI red on main")]:
        r = await client.post(
            f"/api/v1/projects/{project_id}/activity",
            json={"kind": kind, "summary": summary, "source": "ci"},
            headers=headers,
        )
        assert r.status_code == 201, r.text

    # An incident auto-opens a postmortem.
    inc = await client.post(
        f"/api/v1/projects/{project_id}/activity",
        json={"kind": "incident_open", "summary": "API 500s spike", "reference": "INC-9"},
        headers=headers,
    )
    assert inc.status_code == 201

    feed = (
        await client.get(f"/api/v1/projects/{project_id}/activity", headers=headers)
    ).json()
    assert {e["kind"] for e in feed} == {"deploy", "build_failure", "incident_open"}
    # Most recent first.
    assert feed[0]["kind"] == "incident_open"

    retros = (
        await client.get(f"/api/v1/projects/{project_id}/retrospectives", headers=headers)
    ).json()
    postmortems = [r for r in retros if r["kind"] == "incident_postmortem"]
    assert len(postmortems) == 1
    assert "API 500s spike" in postmortems[0]["title"]


@pytest.mark.asyncio
async def test_activity_ingest_requires_planner(client, db_session):
    await _seed_admin(db_session)
    admin = {"Authorization": f"Bearer {await _token(client)}"}
    await client.post(
        "/api/v1/auth/register",
        json={"email": "v@x.com", "password": "pw12345678", "role": "viewer"},
        headers=admin,
    )
    project_id = (
        await client.post(
            "/api/v1/projects", json={"key": "PLAT", "name": "Platform"}, headers=admin
        )
    ).json()["id"]
    viewer = {"Authorization": f"Bearer {await _token(client, 'v@x.com', 'pw12345678')}"}
    # Viewers can read the feed but not ingest.
    assert (
        await client.get(f"/api/v1/projects/{project_id}/activity", headers=viewer)
    ).status_code == 200
    assert (
        await client.post(
            f"/api/v1/projects/{project_id}/activity",
            json={"kind": "deploy", "summary": "x"},
            headers=viewer,
        )
    ).status_code == 403
