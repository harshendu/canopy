from dataclasses import asdict

from fastapi import APIRouter, HTTPException, status
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep
from app.connectors import get_connector
from app.connectors.gdrive import GoogleDriveConnector
from app.connectors.github import GitHubConnector
from app.core.crypto import encrypt_token
from app.models.base import Provider
from app.models.integration import Connection
from app.schemas.entities import ConnectionCreate, ConnectionRead
from app.services import sync as sync_service

router = APIRouter()


async def _get_connection(session, connection_id: int) -> Connection:
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


# --- GitHub on-demand reads ---
def _github(connection: Connection, session) -> GitHubConnector:
    if connection.provider != Provider.github:
        raise HTTPException(status_code=400, detail="Not a GitHub connection")
    return get_connector(connection, session)  # type: ignore[return-value]


@router.get("/github/{connection_id}/file")
async def github_read_file(
    session: SessionDep, _: CurrentUser, connection_id: int, path: str
) -> dict:
    connection = await _get_connection(session, connection_id)
    content = await _github(connection, session).read_file(path)
    return {"path": path, "content": content}


@router.get("/github/{connection_id}/pulls")
async def github_list_pulls(
    session: SessionDep, _: CurrentUser, connection_id: int, state: str = "open"
) -> list[dict]:
    connection = await _get_connection(session, connection_id)
    return await _github(connection, session).list_pull_requests(state)


# --- Google Drive on-demand reads ---
def _gdrive(connection: Connection, session) -> GoogleDriveConnector:
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
