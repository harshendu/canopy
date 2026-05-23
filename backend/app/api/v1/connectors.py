from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.api.deps import CurrentUser, SessionDep
from app.connectors import get_connector, oauth
from app.connectors.gdrive import GoogleDriveConnector
from app.connectors.github import GitHubConnector
from app.connectors.jira import JiraConnector
from app.core.config import settings
from app.core.crypto import encrypt_token
from app.models.base import Provider
from app.models.integration import Connection, PullRequest
from app.schemas.entities import ConnectionCreate, ConnectionRead, PullRequestRead
from app.services import sync as sync_service

router = APIRouter()


async def _get_connection(session: AsyncSession, connection_id: int) -> Connection:
    connection = await session.get(Connection, connection_id)
    if connection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")
    return connection


@router.get("/connections", response_model=list[ConnectionRead])
async def list_connections(session: SessionDep, _: CurrentUser) -> list[Connection]:
    result = await session.execute(select(Connection))
    return list(result.scalars().all())


@router.post("/connections", response_model=ConnectionRead, status_code=status.HTTP_201_CREATED)
async def create_connection(
    session: SessionDep, _: CurrentUser, payload: ConnectionCreate
) -> Connection:
    connection = Connection(
        provider=payload.provider,
        name=payload.name,
        config=payload.config,
        encrypted_token=encrypt_token(payload.token) if payload.token else None,
        encrypted_refresh_token=(
            encrypt_token(payload.refresh_token) if payload.refresh_token else None
        ),
    )
    session.add(connection)
    await session.commit()
    await session.refresh(connection)
    return connection


@router.delete("/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connection(session: SessionDep, _: CurrentUser, connection_id: int) -> None:
    connection = await session.get(Connection, connection_id)
    if connection is not None:
        await session.delete(connection)
        await session.commit()


@router.post("/connections/{connection_id}/sync")
async def trigger_full_sync(session: SessionDep, _: CurrentUser, connection_id: int) -> dict:
    result = await sync_service.run_full_sync(session, connection_id)
    return asdict(result)


@router.post("/connections/{connection_id}/sync/incremental")
async def trigger_incremental_sync(
    session: SessionDep, _: CurrentUser, connection_id: int
) -> dict:
    result = await sync_service.run_incremental_sync(session, connection_id)
    return asdict(result)


# --- OAuth 2.0 (3LO) flows ---
@router.get("/oauth/{connection_id}/authorize")
async def oauth_authorize(
    session: SessionDep, _: CurrentUser, connection_id: int
) -> dict[str, str]:
    """Return the provider authorize URL to redirect the browser to (state is signed)."""
    connection = await _get_connection(session, connection_id)
    state = oauth.create_state(connection_id)
    return {"authorize_url": oauth.build_authorize_url(connection.provider, state)}


@router.get("/oauth/callback")
async def oauth_callback(session: SessionDep, code: str, state: str) -> RedirectResponse:
    """Provider redirect target: validate state, exchange the code, store tokens."""
    connection_id = oauth.verify_state(state)
    if connection_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid OAuth state")
    connection = await session.get(Connection, connection_id)
    if connection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")

    tokens = await oauth.exchange_code(connection.provider, code)
    connection.encrypted_token = encrypt_token(tokens.access_token)
    if tokens.refresh_token:
        connection.encrypted_refresh_token = encrypt_token(tokens.refresh_token)
    if tokens.expires_in:
        connection.token_expires_at = datetime.now(UTC) + timedelta(seconds=tokens.expires_in)

    if connection.provider == Provider.jira:
        cloud_id = await oauth.fetch_jira_cloud_id(tokens.access_token)
        if cloud_id:
            connection.config = {
                **connection.config,
                "auth_type": "oauth",
                "cloud_id": cloud_id,
                "base_url": f"https://api.atlassian.com/ex/jira/{cloud_id}",
            }

    await session.commit()
    target = f"{settings.FRONTEND_BASE_URL.rstrip('/')}/connectors?connected={connection_id}"
    return RedirectResponse(url=target)


# --- Jira Agile + history ---
def _jira(connection: Connection, session: AsyncSession) -> JiraConnector:
    if connection.provider != Provider.jira:
        raise HTTPException(status_code=400, detail="Not a Jira connection")
    return get_connector(connection, session)  # type: ignore[return-value]


@router.get("/jira/{connection_id}/boards")
async def jira_list_boards(
    session: SessionDep, _: CurrentUser, connection_id: int
) -> list[dict[str, Any]]:
    connection = await _get_connection(session, connection_id)
    return await _jira(connection, session).list_boards()


@router.get("/jira/{connection_id}/sprints")
async def jira_list_sprints(
    session: SessionDep, _: CurrentUser, connection_id: int, board_id: int, state: str = "active"
) -> list[dict[str, Any]]:
    connection = await _get_connection(session, connection_id)
    return await _jira(connection, session).list_sprints(board_id, state)


@router.post("/jira/{connection_id}/history")
async def jira_sync_history(
    session: SessionDep, _: CurrentUser, connection_id: int, issue_key: str
) -> dict[str, int]:
    connection = await _get_connection(session, connection_id)
    added = await _jira(connection, session).sync_status_history(issue_key)
    return {"added": added}


# --- GitHub on-demand reads ---
def _github(connection: Connection, session: AsyncSession) -> GitHubConnector:
    if connection.provider != Provider.github:
        raise HTTPException(status_code=400, detail="Not a GitHub connection")
    return get_connector(connection, session)  # type: ignore[return-value]


@router.get("/github/{connection_id}/file")
async def github_read_file(
    session: SessionDep, _: CurrentUser, connection_id: int, path: str
) -> dict[str, Any]:
    connection = await _get_connection(session, connection_id)
    content = await _github(connection, session).read_file(path)
    return {"path": path, "content": content}


@router.get("/github/{connection_id}/pulls")
async def github_list_pulls(
    session: SessionDep, _: CurrentUser, connection_id: int, state: str = "open"
) -> list[dict[str, Any]]:
    connection = await _get_connection(session, connection_id)
    return await _github(connection, session).list_pull_requests(state)


@router.get("/github/cached-prs", response_model=list[PullRequestRead])
async def github_cached_prs(
    session: SessionDep, _: CurrentUser, repo: str | None = None
) -> list[PullRequest]:
    stmt = select(PullRequest)
    if repo is not None:
        stmt = stmt.where(PullRequest.repo == repo)
    result = await session.execute(stmt.order_by(col(PullRequest.number)))
    return list(result.scalars().all())


# --- Google Drive on-demand reads ---
def _gdrive(connection: Connection, session: AsyncSession) -> GoogleDriveConnector:
    if connection.provider != Provider.gdrive:
        raise HTTPException(status_code=400, detail="Not a Google Drive connection")
    return get_connector(connection, session)  # type: ignore[return-value]


@router.get("/gdrive/{connection_id}/docs")
async def gdrive_list_docs(
    session: SessionDep, _: CurrentUser, connection_id: int, query: str | None = None
) -> list[dict]:
    connection = await _get_connection(session, connection_id)
    return await _gdrive(connection, session).list_design_docs(query)


@router.get("/gdrive/{connection_id}/docs/{file_id}")
async def gdrive_read_doc(
    session: SessionDep, _: CurrentUser, connection_id: int, file_id: str
) -> dict:
    connection = await _get_connection(session, connection_id)
    content = await _gdrive(connection, session).export_doc(file_id)
    return {"file_id": file_id, "content": content}
