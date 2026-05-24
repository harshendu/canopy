"""Link Jira tickets to canopy projects/initiatives.

An architect links a Jira ticket (initiative/epic/story) to a canopy Project or Initiative;
canopy maps the ticket plus its descendant subtree into canopy entities (idempotently). Writes
are planner-gated; status stays Jira-owned. See `app/services/jira_linking.py` and USER_FLOWS §J9.
"""

from typing import Literal

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, PlannerWriter, SessionDep
from app.models.integration import JiraLink
from app.schemas.entities import JiraLinkCreate, JiraLinkRead, JiraLinkSyncResult
from app.services import jira_linking

router = APIRouter()


@router.get("/jira-links", response_model=list[JiraLinkRead])
async def list_jira_links(
    session: SessionDep,
    _: CurrentUser,
    target_type: Literal["project", "initiative"],
    target_id: int,
) -> list[JiraLink]:
    return await jira_linking.list_links(session, target_type=target_type, target_id=target_id)


@router.post("/jira-links", response_model=JiraLinkSyncResult, status_code=status.HTTP_201_CREATED)
async def create_jira_link(
    session: SessionDep, _: PlannerWriter, payload: JiraLinkCreate
) -> JiraLinkSyncResult:
    try:
        return await jira_linking.create_or_sync_link(
            session,
            connection_id=payload.connection_id,
            jira_key=payload.jira_key,
            target_type=payload.target_type,
            target_id=payload.target_id,
        )
    except jira_linking.JiraLinkError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/jira-links/{link_id}/resync", response_model=JiraLinkSyncResult)
async def resync_jira_link(
    session: SessionDep, _: PlannerWriter, link_id: int
) -> JiraLinkSyncResult:
    try:
        return await jira_linking.resync_link(session, link_id)
    except jira_linking.JiraLinkError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete("/jira-links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_jira_link(session: SessionDep, _: PlannerWriter, link_id: int) -> None:
    await jira_linking.delete_link(session, link_id)
