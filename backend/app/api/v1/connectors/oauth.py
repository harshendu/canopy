"""OAuth 2.0 (3LO) flows: shared/service-connection authorize (architect), per-user SSO connect
(contributor + allow_user_connect), and the provider redirect callback (unauthenticated — trust
comes from the signed `state`)."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlmodel import select

from app.api.deps import ArchitectWriter, ContributorWriter, SessionDep
from app.api.v1.connectors._shared import get_connection
from app.connectors import oauth
from app.core.config import settings
from app.core.crypto import encrypt_token
from app.models.base import Provider, utcnow
from app.models.integration import Connection, UserConnection
from app.services import integration_policy

router = APIRouter()


@router.get("/oauth/{connection_id}/authorize")
async def oauth_authorize(
    session: SessionDep, _: ArchitectWriter, connection_id: int
) -> dict[str, str]:
    """Return the provider authorize URL for the **shared/service** connection (admin flow)."""
    connection = await get_connection(session, connection_id)
    state = oauth.create_state(connection_id)
    return {"authorize_url": oauth.build_authorize_url(connection.provider, state)}


@router.post("/oauth/{connection_id}/connect-me")
async def oauth_connect_me(
    session: SessionDep, user: ContributorWriter, connection_id: int
) -> dict[str, str]:
    """Per-user SSO: authorize the caller's **own** account against this integration. Open to any
    contributor (non-viewer) when the admin's `allow_user_connect` policy permits it. The signed
    `state` carries the user id so the (unauthenticated) callback binds tokens to a
    `UserConnection`."""
    connection = await get_connection(session, connection_id)
    setting = await integration_policy.get_setting(session, connection.provider)
    if not setting.allow_user_connect:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"per-user connect is disabled for {connection.provider.value}",
        )
    assert user.id is not None
    state = oauth.create_state(connection_id, user_id=user.id)
    return {"authorize_url": oauth.build_authorize_url(connection.provider, state)}


async def _apply_jira_site(connection: Connection, access_token: str) -> None:
    """Resolve the Atlassian site for a token and stamp it on the (shared) connection config if
    not already set — so a per-user connect can bootstrap a token-less integration's target."""
    if connection.config.get("cloud_id"):
        return
    cloud_id = await oauth.fetch_jira_cloud_id(access_token)
    if cloud_id:
        connection.config = {
            **connection.config,
            "auth_type": "oauth",
            "cloud_id": cloud_id,
            "base_url": f"https://api.atlassian.com/ex/jira/{cloud_id}",
        }


@router.get("/oauth/callback")
async def oauth_callback(session: SessionDep, code: str, state: str) -> RedirectResponse:
    """Provider redirect target: validate state, exchange the code, store tokens — on the shared
    connection, or (when `state` carries a user id) on that user's `UserConnection`."""
    decoded = oauth.verify_state(state)
    if decoded is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid OAuth state")
    connection = await session.get(Connection, decoded.connection_id)
    if connection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")

    tokens = await oauth.exchange_code(connection.provider, code)
    expires_at = utcnow() + timedelta(seconds=tokens.expires_in) if tokens.expires_in else None

    if decoded.user_id is None:
        # Shared/service connection.
        connection.encrypted_token = encrypt_token(tokens.access_token)
        if tokens.refresh_token:
            connection.encrypted_refresh_token = encrypt_token(tokens.refresh_token)
        connection.token_expires_at = expires_at
        if connection.provider == Provider.jira:
            await _apply_jira_site(connection, tokens.access_token)
    else:
        # Per-user SSO: bind tokens to the caller's UserConnection (created on connect-me).
        user_conn = (
            await session.execute(
                select(UserConnection).where(
                    UserConnection.connection_id == decoded.connection_id,
                    UserConnection.user_id == decoded.user_id,
                )
            )
        ).scalar_one_or_none()
        if user_conn is None:
            user_conn = UserConnection(
                connection_id=decoded.connection_id, user_id=decoded.user_id
            )
            session.add(user_conn)
        user_conn.encrypted_token = encrypt_token(tokens.access_token)
        if tokens.refresh_token:
            user_conn.encrypted_refresh_token = encrypt_token(tokens.refresh_token)
        user_conn.token_expires_at = expires_at
        user_conn.active = True
        if connection.provider == Provider.jira:
            await _apply_jira_site(connection, tokens.access_token)

    await session.commit()
    target = (
        f"{settings.FRONTEND_BASE_URL.rstrip('/')}/connectors?connected={decoded.connection_id}"
    )
    return RedirectResponse(url=target)
