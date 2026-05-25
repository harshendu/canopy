"""Integration authorization matrix (audit hardening): who may configure / connect / sync /
export, by role and token scope. Reads stay open to any authenticated user; mutating + external
actions are gated. These tests pin the role gates so the matrix can't silently regress.
"""

import pytest

from app.core.security import hash_password
from app.models.base import Provider, ReadStrategy, UserRole
from app.models.integration import Connection, IntegrationSetting
from app.models.user import User

_ROLES = {
    "admin": UserRole.admin,
    "architect": UserRole.architect,
    "manager": UserRole.engineering_manager,
    "engineer": UserRole.engineer,
    "viewer": UserRole.viewer,
}


async def _seed_users(session) -> None:
    session.add_all(
        [
            User(email=f"{name}@e.com", hashed_password=hash_password("secret123"), role=role)
            for name, role in _ROLES.items()
        ]
    )
    await session.commit()


async def _headers(client, name: str, *, agent: bool = False) -> dict[str, str]:
    resp = await client.post(
        "/api/v1/auth/login", data={"username": f"{name}@e.com", "password": "secret123"}
    )
    token = resp.json()["access_token"]
    if agent:
        # Mint an agent-scope token acting as this user (planner-gated to mint).
        full = {"Authorization": f"Bearer {token}"}
        token = (await client.post("/api/v1/auth/agent-token", json={}, headers=full)).json()[
            "access_token"
        ]
    return {"Authorization": f"Bearer {token}"}


# --- connection lifecycle: admin/architect only (ArchitectWriter) ---
@pytest.mark.asyncio
async def test_create_connection_requires_architect(client, db_session) -> None:
    await _seed_users(db_session)
    body = {"provider": "jira", "name": "j", "config": {}}
    for name in ("viewer", "engineer", "manager"):
        resp = await client.post(
            "/api/v1/connectors/connections", json=body, headers=await _headers(client, name)
        )
        assert resp.status_code == 403, f"{name} should not create connections"
    for name in ("architect", "admin"):
        resp = await client.post(
            "/api/v1/connectors/connections", json=body, headers=await _headers(client, name)
        )
        assert resp.status_code == 201, f"{name} should create connections"


@pytest.mark.asyncio
async def test_delete_connection_requires_architect(client, db_session) -> None:
    await _seed_users(db_session)
    conn = Connection(provider=Provider.jira, name="j", config={})
    db_session.add(conn)
    await db_session.commit()
    eng = await _headers(client, "engineer")
    assert (
        await client.delete(f"/api/v1/connectors/connections/{conn.id}", headers=eng)
    ).status_code == 403


# --- sync: planner only (aligned with ingest); 403 fires before any provider call ---
@pytest.mark.asyncio
async def test_sync_requires_planner(client, db_session) -> None:
    await _seed_users(db_session)
    url = "/api/v1/connectors/connections/999999/sync"  # missing connection
    for name in ("viewer", "engineer"):
        assert (await client.post(url, headers=await _headers(client, name))).status_code == 403
    # A planner passes the gate, then hits the missing-connection 400 (not 403).
    assert (await client.post(url, headers=await _headers(client, "manager"))).status_code == 400


# --- per-user SSO connect: contributor (non-viewer) + allow_user_connect ---
@pytest.mark.asyncio
async def test_connect_me_excludes_viewer_and_requires_policy(client, db_session) -> None:
    await _seed_users(db_session)
    conn = Connection(provider=Provider.jira, name="j", config={})
    db_session.add(conn)
    db_session.add(IntegrationSetting(provider=Provider.jira, allow_user_connect=True))
    await db_session.commit()
    url = f"/api/v1/connectors/oauth/{conn.id}/connect-me"

    assert (await client.post(url, headers=await _headers(client, "viewer"))).status_code == 403
    # An engineer (contributor) may connect their own account.
    assert (await client.post(url, headers=await _headers(client, "engineer"))).status_code == 200


# --- export to Drive: planner + human-only (external write) ---
@pytest.mark.asyncio
async def test_export_to_drive_blocks_viewer_and_agent(client, db_session) -> None:
    await _seed_users(db_session)
    url = "/api/v1/projects/1/export/to-drive"
    body = {"fmt": "pdf", "connection_id": 1}

    # viewer blocked by role.
    assert (
        await client.post(url, json=body, headers=await _headers(client, "viewer"))
    ).status_code == 403
    # an agent-scope token (even for a planner) is blocked by HumanOnly — it's an external write.
    agent = await _headers(client, "architect", agent=True)
    assert (await client.post(url, json=body, headers=agent)).status_code == 403


# --- reads stay open to any authenticated user ---
@pytest.mark.asyncio
async def test_reads_open_to_viewer(client, db_session) -> None:
    await _seed_users(db_session)
    db_session.add(IntegrationSetting(provider=Provider.jira, read_strategy=ReadStrategy.mcp))
    await db_session.commit()
    viewer = await _headers(client, "viewer")
    assert (await client.get("/api/v1/connectors/connections", headers=viewer)).status_code == 200
