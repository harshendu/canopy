from datetime import timedelta

import httpx
import pytest

from app.connectors import oauth
from app.connectors.github import GitHubConnector
from app.connectors.oauth import TokenResponse
from app.core.config import settings
from app.core.crypto import decrypt_token, encrypt_token
from app.models.base import Provider, utcnow
from app.models.integration import Connection


def test_state_roundtrip():
    state = oauth.create_state(42)
    assert oauth.verify_state(state) == 42


def test_state_rejects_tampered_token():
    assert oauth.verify_state("not-a-jwt") is None


def test_build_authorize_url_contains_params(monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_OAUTH_CLIENT_ID", "client-123")
    url = oauth.build_authorize_url(Provider.github, "state-xyz")
    assert "github.com/login/oauth/authorize" in url
    assert "client_id=client-123" in url
    assert "state=state-xyz" in url
    assert "response_type=code" in url
    assert "scope=" in url


@pytest.mark.asyncio
async def test_exchange_code_parses_tokens():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"access_token": "at", "refresh_token": "rt", "expires_in": 3600},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    tokens = await oauth.exchange_code(Provider.gdrive, "the-code", client=client)
    await client.aclose()
    assert tokens.access_token == "at"
    assert tokens.refresh_token == "rt"
    assert tokens.expires_in == 3600


@pytest.mark.asyncio
async def test_connector_refreshes_expired_token(db_session, monkeypatch):
    connection = Connection(
        provider=Provider.github,
        name="gh",
        config={"owner": "acme", "repo": "platform"},
        encrypted_token=encrypt_token("old-access"),
        encrypted_refresh_token=encrypt_token("old-refresh"),
        token_expires_at=utcnow() - timedelta(hours=1),
    )
    db_session.add(connection)
    await db_session.flush()

    async def fake_refresh(provider, refresh_token, client=None):
        assert refresh_token == "old-refresh"
        return TokenResponse(
            access_token="new-access", refresh_token="new-refresh", expires_in=3600, raw={}
        )

    monkeypatch.setattr("app.connectors.oauth.refresh_access_token", fake_refresh)

    connector = GitHubConnector(connection, db_session)
    await connector.ensure_fresh_token()

    assert decrypt_token(connection.encrypted_token) == "new-access"
    assert decrypt_token(connection.encrypted_refresh_token) == "new-refresh"  # rotated
    assert connection.token_expires_at > utcnow()  # naive UTC, see models.base.utcnow


@pytest.mark.asyncio
async def test_connector_skips_refresh_when_token_fresh(db_session, monkeypatch):
    connection = Connection(
        provider=Provider.github,
        name="gh",
        encrypted_token=encrypt_token("still-good"),
        encrypted_refresh_token=encrypt_token("rt"),
        token_expires_at=utcnow() + timedelta(hours=2),
    )
    db_session.add(connection)
    await db_session.flush()

    async def boom(*args, **kwargs):  # pragma: no cover - must not be called
        raise AssertionError("refresh should not run for a fresh token")

    monkeypatch.setattr("app.connectors.oauth.refresh_access_token", boom)

    connector = GitHubConnector(connection, db_session)
    await connector.ensure_fresh_token()
    assert decrypt_token(connection.encrypted_token) == "still-good"
