"""Agent-token self-service (§A6): any signed-in user mints a bounded token for Claude / the MCP
server, sees their live tokens with expiry, and can revoke one (the JWT stops authenticating).
An agent token cannot mint or revoke tokens (HumanOnly)."""

from datetime import datetime, timedelta

import pytest

from app.core.security import hash_password
from app.models.base import UserRole, utcnow
from app.models.feature import FeatureFlag
from app.models.user import User
from app.services.agent_tokens import AGENT_TOKEN_MAX_MINUTES, token_status


def test_token_status_is_pure() -> None:
    now = datetime(2026, 7, 13, 12, 0, 0)
    future = now + timedelta(days=1)
    past = now - timedelta(days=1)
    assert token_status(future, None, now) == "active"
    assert token_status(past, None, now) == "expired"
    # revoked wins even when not yet expired
    assert token_status(future, now, now) == "revoked"


async def _seed(session, email: str, role: UserRole) -> None:
    session.add(User(email=email, hashed_password=hash_password("secret123"), role=role))
    await session.commit()


async def _full_headers(client, email: str) -> dict[str, str]:
    resp = await client.post(
        "/api/v1/auth/login", data={"username": email, "password": "secret123"}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.mark.asyncio
async def test_any_authenticated_user_can_mint(client, db_session) -> None:
    # A viewer (lowest tier) can still mint a token for their own Claude session.
    await _seed(db_session, "v@e.com", UserRole.viewer)
    headers = await _full_headers(client, "v@e.com")

    minted = await client.post(
        "/api/v1/auth/agent-token", json={"label": "My laptop"}, headers=headers
    )
    assert minted.status_code == 200, minted.text
    body = minted.json()
    assert body["scope"] == "agent"
    assert body["label"] == "My laptop"
    assert body["access_token"]
    assert body["expires_at"]

    # The minted token itself works for a two-way-door read.
    agent_headers = {"Authorization": f"Bearer {body['access_token']}"}
    me = await client.get("/api/v1/auth/me", headers=agent_headers)
    assert me.status_code == 200
    assert me.json()["email"] == "v@e.com"


@pytest.mark.asyncio
async def test_mint_persists_and_lists_with_expiry(client, db_session) -> None:
    await _seed(db_session, "a@e.com", UserRole.architect)
    headers = await _full_headers(client, "a@e.com")

    minted = (
        await client.post("/api/v1/auth/agent-token", json={}, headers=headers)
    ).json()

    listed = await client.get("/api/v1/auth/agent-tokens", headers=headers)
    assert listed.status_code == 200
    tokens = listed.json()
    assert len(tokens) == 1
    assert tokens[0]["id"] == minted["id"]
    assert tokens[0]["label"] == "Agent token"  # default when none given
    assert tokens[0]["status"] == "active"
    assert tokens[0]["issued_at"] and tokens[0]["expires_at"]
    # No secret is ever exposed by the list.
    assert "access_token" not in tokens[0]


@pytest.mark.asyncio
async def test_expiry_is_clamped_to_max(client, db_session) -> None:
    await _seed(db_session, "a@e.com", UserRole.architect)
    headers = await _full_headers(client, "a@e.com")
    minted = (
        await client.post(
            "/api/v1/auth/agent-token", json={"expires_minutes": 999_999}, headers=headers
        )
    ).json()
    assert minted["expires_minutes"] == AGENT_TOKEN_MAX_MINUTES  # 30 days


@pytest.mark.asyncio
async def test_agent_token_cannot_mint_another(client, db_session) -> None:
    await _seed(db_session, "a@e.com", UserRole.architect)
    full = await _full_headers(client, "a@e.com")
    agent_tok = (
        await client.post("/api/v1/auth/agent-token", json={}, headers=full)
    ).json()["access_token"]
    agent = {"Authorization": f"Bearer {agent_tok}"}

    # Minting is HumanOnly — an agent token can't farm fresh tokens to outlive revocation.
    blocked = await client.post("/api/v1/auth/agent-token", json={}, headers=agent)
    assert blocked.status_code == 403


@pytest.mark.asyncio
async def test_revoke_stops_authentication(client, db_session) -> None:
    await _seed(db_session, "a@e.com", UserRole.architect)
    full = await _full_headers(client, "a@e.com")
    minted = (
        await client.post("/api/v1/auth/agent-token", json={}, headers=full)
    ).json()
    agent = {"Authorization": f"Bearer {minted['access_token']}"}

    # Works before revocation.
    assert (await client.get("/api/v1/auth/me", headers=agent)).status_code == 200

    revoked = await client.delete(f"/api/v1/auth/agent-tokens/{minted['id']}", headers=full)
    assert revoked.status_code == 204

    # The JWT is otherwise valid (unexpired, correct signature) but now rejected.
    assert (await client.get("/api/v1/auth/me", headers=agent)).status_code == 401

    # And it shows as revoked in the list.
    tokens = (await client.get("/api/v1/auth/agent-tokens", headers=full)).json()
    assert tokens[0]["status"] == "revoked" and tokens[0]["revoked_at"]


@pytest.mark.asyncio
async def test_cannot_revoke_another_users_token(client, db_session) -> None:
    await _seed(db_session, "a@e.com", UserRole.architect)
    await _seed(db_session, "b@e.com", UserRole.architect)
    a_headers = await _full_headers(client, "a@e.com")
    b_headers = await _full_headers(client, "b@e.com")
    a_token = (
        await client.post("/api/v1/auth/agent-token", json={}, headers=a_headers)
    ).json()

    # B can't revoke A's token (scoped to the owner) — 404, not a silent success.
    resp = await client.delete(
        f"/api/v1/auth/agent-tokens/{a_token['id']}", headers=b_headers
    )
    assert resp.status_code == 404
    # A's token still authenticates.
    a_agent = {"Authorization": f"Bearer {a_token['access_token']}"}
    assert (await client.get("/api/v1/auth/me", headers=a_agent)).status_code == 200


@pytest.mark.asyncio
async def test_feature_gate_blocks_mint_but_not_list(client, db_session) -> None:
    await _seed(db_session, "a@e.com", UserRole.architect)
    headers = await _full_headers(client, "a@e.com")
    # Mint one while the feature is on, then turn it off.
    existing = (
        await client.post("/api/v1/auth/agent-token", json={}, headers=headers)
    ).json()
    db_session.add(FeatureFlag(key="ai.agent_tokens", enabled=False))
    await db_session.commit()

    blocked = await client.post("/api/v1/auth/agent-token", json={}, headers=headers)
    assert blocked.status_code == 403

    # Listing + revoking stay open so a user can still clean up existing tokens.
    listed = await client.get("/api/v1/auth/agent-tokens", headers=headers)
    assert listed.status_code == 200 and len(listed.json()) == 1
    revoked = await client.delete(
        f"/api/v1/auth/agent-tokens/{existing['id']}", headers=headers
    )
    assert revoked.status_code == 204


def test_utcnow_is_naive() -> None:
    # Guards the portability rule the token expiry relies on (asyncpg rejects tz-aware datetimes).
    assert utcnow().tzinfo is None
