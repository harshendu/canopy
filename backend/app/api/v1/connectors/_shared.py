"""Shared helpers for the connectors routers: connection lookup + per-provider connector access."""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors import get_connector
from app.connectors.gdrive import GoogleDriveConnector
from app.connectors.github import GitHubConnector
from app.connectors.jira import JiraConnector
from app.models.base import Provider
from app.models.integration import Connection


async def get_connection(session: AsyncSession, connection_id: int) -> Connection:
    connection = await session.get(Connection, connection_id)
    if connection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")
    return connection


def jira_connector(connection: Connection, session: AsyncSession) -> JiraConnector:
    if connection.provider != Provider.jira:
        raise HTTPException(status_code=400, detail="Not a Jira connection")
    return get_connector(connection, session)  # type: ignore[return-value]


def github_connector(connection: Connection, session: AsyncSession) -> GitHubConnector:
    if connection.provider != Provider.github:
        raise HTTPException(status_code=400, detail="Not a GitHub connection")
    return get_connector(connection, session)  # type: ignore[return-value]


def gdrive_connector(connection: Connection, session: AsyncSession) -> GoogleDriveConnector:
    if connection.provider != Provider.gdrive:
        raise HTTPException(status_code=400, detail="Not a Google Drive connection")
    return get_connector(connection, session)  # type: ignore[return-value]
