"""OAuth 2.0 (3LO) machinery for Jira, GitHub, and Google.

Builds authorize URLs, exchanges authorization codes for tokens, and refreshes
access tokens. CSRF `state` is a short-lived signed JWT carrying the connection id,
so the flow is stateless (no server-side session needed). The token endpoints
accept an injectable httpx client for testing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt

from app.core.config import settings
from app.models.base import Provider

_STATE_TTL_SECONDS = 600


@dataclass
class OAuthProviderConfig:
    authorize_url: str
    token_url: str
    scopes: str
    client_id: str
    client_secret: str
    extra_authorize_params: dict[str, str] = field(default_factory=dict)


@dataclass
class TokenResponse:
    access_token: str
    refresh_token: str | None
    expires_in: int | None
    raw: dict[str, Any]


def redirect_uri() -> str:
    base = settings.OAUTH_REDIRECT_BASE_URL.rstrip("/")
    return f"{base}{settings.API_V1_PREFIX}/connectors/oauth/callback"


def provider_config(provider: Provider) -> OAuthProviderConfig:
    if provider == Provider.jira:
        return OAuthProviderConfig(
            authorize_url="https://auth.atlassian.com/authorize",
            token_url="https://auth.atlassian.com/oauth/token",
            # write:jira-work lets canopy create/update tickets from a reviewed draft plan
            # (content only — status stays Jira-owned); read scopes drive sync.
            scopes="read:jira-work write:jira-work read:jira-user offline_access",
            client_id=settings.JIRA_OAUTH_CLIENT_ID,
            client_secret=settings.JIRA_OAUTH_CLIENT_SECRET,
            extra_authorize_params={"audience": "api.atlassian.com", "prompt": "consent"},
        )
    if provider == Provider.github:
        return OAuthProviderConfig(
            authorize_url="https://github.com/login/oauth/authorize",
            token_url="https://github.com/login/oauth/access_token",
            scopes="repo read:org",
            client_id=settings.GITHUB_OAUTH_CLIENT_ID,
            client_secret=settings.GITHUB_OAUTH_CLIENT_SECRET,
        )
    if provider == Provider.gdrive:
        return OAuthProviderConfig(
            authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
            token_url="https://oauth2.googleapis.com/token",
            # drive.readonly to read design docs; drive.file to upload export snapshots
            # (drive.file is per-file and non-restricted; drive.readonly is the CASA-restricted
            # one — an Internal Workspace app avoids Google verification entirely).
            scopes=(
                "https://www.googleapis.com/auth/drive.readonly "
                "https://www.googleapis.com/auth/drive.file"
            ),
            client_id=settings.GOOGLE_OAUTH_CLIENT_ID,
            client_secret=settings.GOOGLE_OAUTH_CLIENT_SECRET,
            extra_authorize_params={"access_type": "offline", "prompt": "consent"},
        )
    raise ValueError(f"Unsupported OAuth provider: {provider}")


def build_authorize_url(provider: Provider, state: str) -> str:
    cfg = provider_config(provider)
    params = {
        "client_id": cfg.client_id,
        "redirect_uri": redirect_uri(),
        "scope": cfg.scopes,
        "state": state,
        "response_type": "code",
        **cfg.extra_authorize_params,
    }
    return f"{cfg.authorize_url}?{urlencode(params)}"


def _parse_token(data: dict[str, Any]) -> TokenResponse:
    return TokenResponse(
        access_token=str(data["access_token"]),
        refresh_token=data.get("refresh_token"),
        expires_in=data.get("expires_in"),
        raw=data,
    )


async def _post_token(
    cfg: OAuthProviderConfig, payload: dict[str, str], client: httpx.AsyncClient | None = None
) -> TokenResponse:
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=30.0)
    try:
        resp = await client.post(
            cfg.token_url, data=payload, headers={"Accept": "application/json"}
        )
        resp.raise_for_status()
        return _parse_token(resp.json())
    finally:
        if owns_client:
            await client.aclose()


async def exchange_code(
    provider: Provider, code: str, client: httpx.AsyncClient | None = None
) -> TokenResponse:
    cfg = provider_config(provider)
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri(),
        "client_id": cfg.client_id,
        "client_secret": cfg.client_secret,
    }
    return await _post_token(cfg, payload, client)


async def refresh_access_token(
    provider: Provider, refresh_token: str, client: httpx.AsyncClient | None = None
) -> TokenResponse:
    cfg = provider_config(provider)
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": cfg.client_id,
        "client_secret": cfg.client_secret,
    }
    return await _post_token(cfg, payload, client)


async def fetch_jira_cloud_id(
    access_token: str, client: httpx.AsyncClient | None = None
) -> str | None:
    """Resolve the Atlassian cloudId for the granted site (first accessible resource)."""
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=30.0)
    try:
        resp = await client.get(
            "https://api.atlassian.com/oauth/token/accessible-resources",
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        )
        resp.raise_for_status()
        resources = resp.json()
        if resources:
            return str(resources[0]["id"])
        return None
    finally:
        if owns_client:
            await client.aclose()


@dataclass
class OAuthState:
    """Decoded CSRF state: the connection being authorized, and the user when this is a
    per-user (SSO) connect (`user_id` is None for the shared/service connection flow)."""

    connection_id: int
    user_id: int | None = None


def create_state(connection_id: int, user_id: int | None = None) -> str:
    expire = datetime.now(UTC) + timedelta(seconds=_STATE_TTL_SECONDS)
    payload: dict[str, Any] = {"cid": connection_id, "purpose": "oauth", "exp": expire}
    if user_id is not None:
        payload["uid"] = user_id
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def verify_state(state: str) -> OAuthState | None:
    try:
        payload = jwt.decode(state, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None
    if payload.get("purpose") != "oauth":
        return None
    cid = payload.get("cid")
    if cid is None:
        return None
    uid = payload.get("uid")
    return OAuthState(connection_id=int(cid), user_id=int(uid) if uid is not None else None)
