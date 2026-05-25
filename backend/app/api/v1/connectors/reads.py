"""On-demand provider reads (open to any authenticated user): Jira Agile + status history + the
epic→doc field mapping/harvest, GitHub file/PR reads, and Google Drive doc reads. The doc-field
mapping save + harvest write canopy state, so they're planner-gated."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from sqlmodel import col, select

from app.api.deps import CurrentUser, PlannerWriter, SessionDep
from app.api.v1.connectors._shared import (
    gdrive_connector,
    get_connection,
    github_connector,
    jira_connector,
)
from app.models.integration import PullRequest
from app.schemas.entities import (
    DocFieldMapping,
    EpicDocSampleResponse,
    HarvestDocsResult,
    PullRequestRead,
)
from app.services import doc_graph

router = APIRouter()


# --- Jira Agile + history ---
@router.get("/jira/{connection_id}/boards")
async def jira_list_boards(
    session: SessionDep, _: CurrentUser, connection_id: int
) -> list[dict[str, Any]]:
    connection = await get_connection(session, connection_id)
    return await jira_connector(connection, session).list_boards()


@router.get("/jira/{connection_id}/sprints")
async def jira_list_sprints(
    session: SessionDep, _: CurrentUser, connection_id: int, board_id: int, state: str = "active"
) -> list[dict[str, Any]]:
    connection = await get_connection(session, connection_id)
    return await jira_connector(connection, session).list_sprints(board_id, state)


@router.post("/jira/{connection_id}/history")
async def jira_sync_history(
    session: SessionDep, _: PlannerWriter, connection_id: int, issue_key: str
) -> dict[str, int]:
    connection = await get_connection(session, connection_id)
    added = await jira_connector(connection, session).sync_status_history(issue_key)
    return {"added": added}


# --- Jira epic → document field mapping (the AI-driven, one-time setup) ---
@router.get("/jira/{connection_id}/doc-fields/sample", response_model=EpicDocSampleResponse)
async def jira_doc_field_sample(
    session: SessionDep, _: CurrentUser, connection_id: int, limit: int = 5
) -> dict:
    """Fetch a sample of epics' URL-bearing fields + remote links so an agent can propose a
    field→kind mapping (which Jira field holds the PRD, the design, the tech-design, etc.)."""
    try:
        return await doc_graph.analyze_epic_doc_fields(session, connection_id, limit=limit)
    except doc_graph.DocGraphError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/jira/{connection_id}/doc-field-mapping", response_model=DocFieldMapping)
async def jira_get_doc_field_mapping(
    session: SessionDep, _: CurrentUser, connection_id: int
) -> dict:
    """The doc field mapping currently configured on this Jira connection."""
    connection = await get_connection(session, connection_id)
    return doc_graph.get_mapping(connection)


@router.post("/jira/{connection_id}/doc-field-mapping", response_model=DocFieldMapping)
async def jira_set_doc_field_mapping(
    session: SessionDep, _: PlannerWriter, connection_id: int, payload: DocFieldMapping
) -> dict:
    """Save the confirmed field→kind mapping on the connection (a one-time admin step)."""
    try:
        return await doc_graph.set_mapping(
            session,
            connection_id,
            mappings=[m.model_dump() for m in payload.mappings],
            parse_description_links=payload.parse_description_links,
            parse_remote_links=payload.parse_remote_links,
        )
    except doc_graph.DocGraphError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/jira/{connection_id}/harvest-docs", response_model=HarvestDocsResult)
async def jira_harvest_docs(
    session: SessionDep, _: PlannerWriter, connection_id: int
) -> HarvestDocsResult:
    """Harvest doc links from every synced epic and attach them to the canopy entity each
    epic maps to (a summary task or a project)."""
    try:
        result = await doc_graph.harvest(session, connection_id)
    except doc_graph.DocGraphError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return HarvestDocsResult(
        references_created=result.references_created,
        references_updated=result.references_updated,
        skipped=result.skipped,
        epics_scanned=result.epics_scanned,
        notes=result.notes,
    )


# --- GitHub on-demand reads ---
@router.get("/github/{connection_id}/file")
async def github_read_file(
    session: SessionDep, _: CurrentUser, connection_id: int, path: str
) -> dict[str, Any]:
    connection = await get_connection(session, connection_id)
    content = await github_connector(connection, session).read_file(path)
    return {"path": path, "content": content}


@router.get("/github/{connection_id}/pulls")
async def github_list_pulls(
    session: SessionDep, _: CurrentUser, connection_id: int, state: str = "open"
) -> list[dict[str, Any]]:
    connection = await get_connection(session, connection_id)
    return await github_connector(connection, session).list_pull_requests(state)


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
@router.get("/gdrive/{connection_id}/docs")
async def gdrive_list_docs(
    session: SessionDep, _: CurrentUser, connection_id: int, query: str | None = None
) -> list[dict]:
    connection = await get_connection(session, connection_id)
    return await gdrive_connector(connection, session).list_design_docs(query)


@router.get("/gdrive/{connection_id}/docs/{file_id}")
async def gdrive_read_doc(
    session: SessionDep, _: CurrentUser, connection_id: int, file_id: str
) -> dict:
    connection = await get_connection(session, connection_id)
    content = await gdrive_connector(connection, session).export_doc(file_id)
    return {"file_id": file_id, "content": content}
