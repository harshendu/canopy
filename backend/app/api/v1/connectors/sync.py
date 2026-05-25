"""Pulling external data into canopy: direct sync (planner-gated) + the MCP-orchestrated ingest
twins (issues / pull requests / file upload). Ingest is NOT human-only — a scheduled Claude job
(agent-scope token) may call it (internal, idempotent two-way-door write)."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from app.api.deps import PlannerWriter, SessionDep
from app.api.v1.connectors._shared import get_connection
from app.connectors.base import SyncResult
from app.models.base import Provider
from app.schemas.entities import (
    FileIngestResult,
    IngestIssuesRequest,
    IngestPullRequestsRequest,
    IngestResult,
)
from app.services import file_ingest, ingest
from app.services import sync as sync_service

router = APIRouter()


@router.post("/connections/{connection_id}/sync")
async def trigger_full_sync(session: SessionDep, user: PlannerWriter, connection_id: int) -> dict:
    try:
        result = await sync_service.run_full_sync(session, connection_id, user.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return asdict(result)


@router.post("/connections/{connection_id}/sync/incremental")
async def trigger_incremental_sync(
    session: SessionDep, user: PlannerWriter, connection_id: int
) -> dict:
    try:
        result = await sync_service.run_incremental_sync(session, connection_id, user.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return asdict(result)


@router.post("/connections/{connection_id}/ingest/issues", response_model=IngestResult)
async def ingest_issues(
    session: SessionDep, _: PlannerWriter, connection_id: int, payload: IngestIssuesRequest
) -> SyncResult:
    connection = await get_connection(session, connection_id)
    if connection.provider != Provider.jira:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Not a Jira connection"
        )
    try:
        return await ingest.ingest_issues(session, connection, payload.issues)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/connections/{connection_id}/ingest/pull-requests", response_model=IngestResult)
async def ingest_pull_requests(
    session: SessionDep, _: PlannerWriter, connection_id: int, payload: IngestPullRequestsRequest
) -> SyncResult:
    connection = await get_connection(session, connection_id)
    if connection.provider != Provider.github:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Not a GitHub connection"
        )
    try:
        return await ingest.ingest_pull_requests(session, connection, payload.pull_requests)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/connections/{connection_id}/ingest/file", response_model=FileIngestResult)
async def ingest_file_upload(
    session: SessionDep,
    _: PlannerWriter,
    connection_id: int,
    file: UploadFile = File(...),
) -> FileIngestResult:
    """Upload a JSON or CSV export and ingest it idempotently (entity type inferred from the
    connection's provider). The direct-upload twin of the watched file-drop poll."""
    connection = await get_connection(session, connection_id)
    data = await file.read()
    try:
        return await file_ingest.ingest_file(session, connection, file.filename or "", data)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
