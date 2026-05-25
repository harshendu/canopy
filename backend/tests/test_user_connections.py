"""Per-user SSO (Phase 2): a user's own OAuth credential, attached to a shared Connection.

Covers credential resolution (user-first reads, write attribution + fallback to shared), the
EffectiveCredential view, and the connect-me / callback endpoints. A narrow-access user's pull
must stay non-destructive — each per-user credential keeps its own watermark.
"""

from urllib.parse import parse_qs, urlparse

import pytest

from app.connectors import oauth
from app.connectors.base import EffectiveCredential
from app.connectors.oauth import TokenResponse
from app.core.crypto import decrypt_token, encrypt_token
from app.core.security import hash_password
from app.models.base import Provider, ReadStrategy, UserRole, WriteStrategy
from app.models.integration import Connection, IntegrationSetting, UserConnection
from app.models.user import User
from app.services import integration_policy


async def _connection(session, *, token: str | None = None) -> Connection:
    conn = Connection(
        provider=Provider.jira,
        name="jira",
        config={"project_id": 1, "base_url": "https://x", "jira_project_key": "P"},
        encrypted_token=encrypt_token(token) if token else None,
    )
    session.add(conn)
    await session.flush()
    return conn


async def _user(session, email: str = "u@e.com") -> User:
    user = User(email=email, hashed_password=hash_password("secret123"), role=UserRole.engineer)
    session.add(user)
    await session.flush()
    return user


async def _user_conn(session, conn: Connection, user: User, *, token: str | None = "ut") -> None:
    session.add(
        UserConnection(
            connection_id=conn.id,
            user_id=user.id,
            encrypted_token=encrypt_token(token) if token else None,
        )
    )
    await session.flush()


async def _allow(session, provider: Provider, *, allow: bool = True) -> None:
    session.add(IntegrationSetting(provider=provider, allow_user_connect=allow))
    await session.flush()


# --- EffectiveCredential view ---
@pytest.mark.asyncio
async def test_effective_credential_layers_user_token_over_shared_config(db_session) -> None:
    conn = await _connection(db_session, token="shared")
    uc = UserConnection(connection_id=conn.id, user_id=1, encrypted_token=encrypt_token("mine"))
    db_session.add(uc)
    await db_session.flush()

    ec = EffectiveCredential(conn, uc)
    assert ec.provider == Provider.jira
    assert ec.config == conn.config  # target config comes from the shared connection
    assert ec.encrypted_token == uc.encrypted_token  # token comes from the user
    # writes (token rotation / watermark) persist on the UserConnection row, not the Connection
    ec.watermark = "2026-01-01"
    ec.encrypted_token = encrypt_token("rotated")
    assert uc.watermark == "2026-01-01"
    assert decrypt_token(uc.encrypted_token) == "rotated"
    assert conn.watermark is None


# --- read resolution (user-first) ---
@pytest.mark.asyncio
async def test_read_prefers_user_then_shared(db_session) -> None:
    conn = await _connection(db_session, token="shared")
    await _allow(db_session, Provider.jira)
    user = await _user(db_session)
    await _user_conn(db_session, conn, user)

    as_user = await integration_policy.resolve_read_credential(db_session, conn, user.id)
    assert isinstance(as_user, EffectiveCredential)

    # background read (no user) uses the shared connection
    background = await integration_policy.resolve_read_credential(db_session, conn, None)
    assert background is conn

    # a user without their own credential falls back to the shared connection
    other = await _user(db_session, "other@e.com")
    fallback = await integration_policy.resolve_read_credential(db_session, conn, other.id)
    assert fallback is conn


@pytest.mark.asyncio
async def test_read_ignores_user_credential_when_connect_disabled(db_session) -> None:
    conn = await _connection(db_session, token="shared")
    await _allow(db_session, Provider.jira, allow=False)
    user = await _user(db_session)
    await _user_conn(db_session, conn, user)

    resolved = await integration_policy.resolve_read_credential(db_session, conn, user.id)
    assert resolved is conn  # policy off → shared only


@pytest.mark.asyncio
async def test_read_none_when_not_direct(db_session) -> None:
    conn = await _connection(db_session, token="shared")
    db_session.add(IntegrationSetting(provider=Provider.jira, read_strategy=ReadStrategy.mcp))
    await db_session.flush()
    assert await integration_policy.resolve_read_credential(db_session, conn, None) is None


# --- write resolution (attribution, fallback to shared) ---
@pytest.mark.asyncio
async def test_write_prefers_user_then_shared_then_none(db_session) -> None:
    conn = await _connection(db_session, token="shared")
    await _allow(db_session, Provider.jira)
    user = await _user(db_session)
    await _user_conn(db_session, conn, user)

    cred, reason = await integration_policy.resolve_write_credential(db_session, conn, user.id)
    assert isinstance(cred, EffectiveCredential) and reason == "user"

    other = await _user(db_session, "other@e.com")
    cred, reason = await integration_policy.resolve_write_credential(db_session, conn, other.id)
    assert cred is conn and reason == "shared"


@pytest.mark.asyncio
async def test_write_blocked_when_no_credentials(db_session) -> None:
    conn = await _connection(db_session, token=None)  # token-less integration definition
    await _allow(db_session, Provider.jira)
    user = await _user(db_session)
    cred, reason = await integration_policy.resolve_write_credential(db_session, conn, user.id)
    assert cred is None and "no usable" in reason


@pytest.mark.asyncio
async def test_write_blocked_by_mcp_policy(db_session) -> None:
    conn = await _connection(db_session, token="shared")
    db_session.add(IntegrationSetting(provider=Provider.jira, write_strategy=WriteStrategy.mcp))
    await db_session.flush()
    cred, reason = await integration_policy.resolve_write_credential(db_session, conn, 1)
    assert cred is None and "MCP" in reason


# --- connect-me / callback endpoints ---
async def _token(client, email: str) -> dict[str, str]:
    resp = await client.post(
        "/api/v1/auth/login", data={"username": email, "password": "secret123"}
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.mark.asyncio
async def test_connect_me_requires_allow_user_connect(client, db_session) -> None:
    conn = await _connection(db_session)
    await _user(db_session)
    await db_session.commit()
    headers = await _token(client, "u@e.com")

    blocked = await client.post(f"/api/v1/connectors/oauth/{conn.id}/connect-me", headers=headers)
    assert blocked.status_code == 403

    db_session.add(IntegrationSetting(provider=Provider.jira, allow_user_connect=True))
    await db_session.commit()
    ok = await client.post(f"/api/v1/connectors/oauth/{conn.id}/connect-me", headers=headers)
    assert ok.status_code == 200
    state = parse_qs(urlparse(ok.json()["authorize_url"]).query)["state"][0]
    decoded = oauth.verify_state(state)
    assert decoded is not None and decoded.connection_id == conn.id


@pytest.mark.asyncio
async def test_callback_binds_tokens_to_user_connection(client, db_session, monkeypatch) -> None:
    conn = await _connection(db_session)
    user = await _user(db_session)
    db_session.add(IntegrationSetting(provider=Provider.jira, allow_user_connect=True))
    await db_session.commit()

    async def fake_exchange(provider, code, client=None):
        return TokenResponse(
            access_token="user-at", refresh_token="user-rt", expires_in=3600, raw={}
        )

    async def fake_cloud(access_token, client=None):
        return "cloud-1"

    monkeypatch.setattr("app.connectors.oauth.exchange_code", fake_exchange)
    monkeypatch.setattr("app.connectors.oauth.fetch_jira_cloud_id", fake_cloud)

    state = oauth.create_state(conn.id, user_id=user.id)
    resp = await client.get(f"/api/v1/connectors/oauth/callback?code=abc&state={state}")
    assert resp.status_code in (200, 302, 307)

    from sqlmodel import select

    uc = (
        await db_session.execute(
            select(UserConnection).where(
                UserConnection.connection_id == conn.id, UserConnection.user_id == user.id
            )
        )
    ).scalar_one()
    assert uc.authorized and decrypt_token(uc.encrypted_token) == "user-at"
    # the shared connection's site config is bootstrapped from the first token, but its token isn't
    await db_session.refresh(conn)
    assert conn.config.get("cloud_id") == "cloud-1"
    assert conn.encrypted_token is None
