import pytest

from app.core.config import settings
from app.core.security import hash_password
from app.models.base import UserRole
from app.models.user import User
from app.services import seed


async def _admin(session) -> User:
    user = User(
        email="admin@example.com", hashed_password=hash_password("secret123"),
        role=UserRole.admin, full_name="Op Admin",
    )
    session.add(user)
    await session.commit()
    return user


async def _token(client, email: str, password: str) -> str:
    resp = await client.post(
        "/api/v1/auth/login", data={"username": email, "password": password}
    )
    return resp.json()["access_token"]


def _hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_seed_loader_builds_a_full_coherent_dataset(db_session):
    counts = await seed.load_seed_data(db_session, set())

    assert counts["projects"] >= 8
    assert counts["initiatives"] == 3
    assert counts["users"] >= 6  # one login per role, spanning every persona
    assert counts["tasks"] > 40
    assert counts["dependencies"] > 0
    assert counts["decisions"] >= 10  # ADRs spread across every project
    assert counts["components"] >= 15
    assert counts["risks"] >= 8  # project + initiative scope
    assert counts["specs"] >= 8  # every project has a spec
    assert counts["outcomes"] >= 8
    assert counts["blockers"] >= 2
    assert counts["scenarios"] >= 2
    assert counts["status_history"] > 0
    assert counts["connections"] == 3


@pytest.mark.asyncio
async def test_clear_wipes_everything_but_kept_users(db_session):
    keeper = await _admin(db_session)
    await seed.load_seed_data(db_session, {keeper.id})
    await seed.clear_all_data(db_session, {keeper.id})

    after = await seed.seed_summary(db_session)
    assert after["projects"] == 0
    assert after["tasks"] == 0
    assert after["connections"] == 0
    # The acting admin is preserved so they stay logged in.
    assert after["users"] == 1


@pytest.mark.asyncio
async def test_reseed_endpoint_double_gated(client, db_session, monkeypatch):
    await _admin(db_session)
    admin = _hdr(await _token(client, "admin@example.com", "secret123"))

    monkeypatch.setattr(settings, "DEMO_MODE", False)
    blocked = await client.post("/api/v1/admin/demo/reseed", headers=admin)
    assert blocked.status_code == 403

    monkeypatch.setattr(settings, "DEMO_MODE", True)
    ok = await client.post("/api/v1/admin/demo/reseed", headers=admin)
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["seeded"] is True
    assert body["counts"]["projects"] >= 5
    assert body["password"] and len(body["accounts"]) >= 6

    cleared = await client.post("/api/v1/admin/demo/clear", headers=admin)
    assert cleared.status_code == 200
    assert cleared.json()["counts"]["projects"] == 0


@pytest.mark.asyncio
async def test_reseed_requires_admin(client, db_session, monkeypatch):
    await _admin(db_session)
    admin = _hdr(await _token(client, "admin@example.com", "secret123"))
    monkeypatch.setattr(settings, "DEMO_MODE", True)
    await client.post(
        "/api/v1/auth/register",
        json={"email": "eng@example.com", "password": "pw12345678", "role": "engineer"},
        headers=admin,
    )
    eng = _hdr(await _token(client, "eng@example.com", "pw12345678"))
    denied = await client.post("/api/v1/admin/demo/reseed", headers=eng)
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_public_demo_info_reflects_mode(client, monkeypatch):
    monkeypatch.setattr(settings, "DEMO_MODE", False)
    off = (await client.get("/api/v1/admin/demo/public")).json()
    assert off["demo_mode"] is False
    assert off["accounts"] == []

    monkeypatch.setattr(settings, "DEMO_MODE", True)
    on = (await client.get("/api/v1/admin/demo/public")).json()
    assert on["demo_mode"] is True
    assert on["password"]
    assert len(on["accounts"]) >= 6


@pytest.mark.asyncio
async def test_demo_jira_sync_uses_offline_mock(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "DEMO_MODE", True)
    await _admin(db_session)
    admin = _hdr(await _token(client, "admin@example.com", "secret123"))
    await client.post("/api/v1/admin/demo/reseed", headers=admin)

    conns = (await client.get("/api/v1/connectors/connections", headers=admin)).json()
    jira = next(c for c in conns if c["provider"] == "jira")
    synced = await client.post(
        f"/api/v1/connectors/connections/{jira['id']}/sync", headers=admin
    )
    assert synced.status_code == 200, synced.text
    # The offline mock returns one epic + three stories — the first sync imports them.
    assert synced.json()["created"] >= 1

    # GitHub PR reads also work fully offline.
    github = next(c for c in conns if c["provider"] == "github")
    pulls = await client.get(
        f"/api/v1/connectors/github/{github['id']}/pulls", headers=admin
    )
    assert pulls.status_code == 200
    assert len(pulls.json()) >= 1
