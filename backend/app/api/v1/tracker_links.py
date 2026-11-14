"""Tracker links: link one item of any work tracker (an initiative/epic/story) and its
descendants to a canopy project or initiative; canopy maps the subtree idempotently. Writes are
planner-gated; status stays the tracker's. `/jira-links` is the pre-tracker alias, kept for one
release. See `app/services/tracker_links.py` and USER_FLOWS §J9.
"""

from typing import Literal

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, PlannerWriter, SessionDep
from app.connectors.tracker import tracker_class
from app.models.integration import Connection, TrackerBinding
from app.schemas.entities import TrackerLinkCreate, TrackerLinkRead, TrackerLinkSyncResult
from app.services import tracker_links
from app.services.access import ensure_initiative_editable, ensure_project_editable
from app.services.links import tracker_item_url
from app.services.tracker_sync import LinkMapResult

router = APIRouter()


def link_read(binding: TrackerBinding, connection: Connection | None) -> TrackerLinkRead:
    assert binding.id is not None
    scope = binding.scope or {}
    root_key = str(scope.get("root_key") or "")
    return TrackerLinkRead(
        id=binding.id,
        connection_id=binding.connection_id,
        provider=str(binding.provider),
        root_id=str(scope.get("root_id") or ""),
        root_key=root_key,
        root_type=scope.get("root_type"),
        target_type=binding.target_type,
        target_id=binding.target_id,
        url=tracker_item_url(connection, binding.provider, root_key) if root_key else None,
        last_synced_at=binding.last_synced_at,
        created_at=binding.created_at,
    )


async def _result(
    session: SessionDep, binding: TrackerBinding, mapped: LinkMapResult
) -> TrackerLinkSyncResult:
    return TrackerLinkSyncResult(
        link=link_read(binding, await session.get(Connection, binding.connection_id)),
        projects_created=mapped.projects_created,
        projects_linked=mapped.projects_linked,
        tasks_created=mapped.tasks_created,
        tasks_updated=mapped.tasks_updated,
        skipped=mapped.skipped,
        created_project_ids=mapped.created_project_ids,
        notes=mapped.notes,
    )


async def _ensure_editable(
    session: SessionDep, user: PlannerWriter, target_type: str, target_id: int
) -> None:
    if target_type == "project":
        await ensure_project_editable(session, user, target_id)
    else:
        await ensure_initiative_editable(session, user, target_id)


@router.get("/tracker-links", response_model=list[TrackerLinkRead])
async def list_tracker_links(
    session: SessionDep,
    _: CurrentUser,
    target_type: Literal["project", "initiative"],
    target_id: int,
) -> list[TrackerLinkRead]:
    rows = await tracker_links.list_links(session, target_type=target_type, target_id=target_id)
    out: list[TrackerLinkRead] = []
    for b in rows:
        if tracker_class(b.provider) is not None:
            out.append(link_read(b, await session.get(Connection, b.connection_id)))
    return out


@router.post(
    "/tracker-links", response_model=TrackerLinkSyncResult, status_code=status.HTTP_201_CREATED
)
async def create_tracker_link(
    session: SessionDep, user: PlannerWriter, payload: TrackerLinkCreate
) -> TrackerLinkSyncResult:
    await _ensure_editable(session, user, payload.target_type, payload.target_id)
    try:
        binding, mapped = await tracker_links.create_or_sync(
            session,
            connection_id=payload.connection_id,
            root_key=payload.root_key,
            target_type=payload.target_type,
            target_id=payload.target_id,
        )
    except tracker_links.TrackerLinkError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return await _result(session, binding, mapped)


@router.post("/tracker-links/{link_id}/resync", response_model=TrackerLinkSyncResult)
async def resync_tracker_link(
    session: SessionDep, user: PlannerWriter, link_id: int
) -> TrackerLinkSyncResult:
    binding = await session.get(TrackerBinding, link_id)
    if binding is None or binding.scope_kind != "subtree":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Link not found")
    await _ensure_editable(session, user, binding.target_type, binding.target_id)
    try:
        binding, mapped = await tracker_links.resync(session, link_id)
    except tracker_links.TrackerLinkError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return await _result(session, binding, mapped)


@router.delete("/tracker-links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tracker_link(session: SessionDep, user: PlannerWriter, link_id: int) -> None:
    binding = await session.get(TrackerBinding, link_id)
    if binding is None or binding.scope_kind != "subtree":
        return
    await _ensure_editable(session, user, binding.target_type, binding.target_id)
    await tracker_links.unlink(session, link_id)
