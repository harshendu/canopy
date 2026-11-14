"""Board workflows (USER_FLOWS §C9): the ordered status columns, their categories and WIP limits.

A project's board resolves project override → team → workspace template → built-in default
(`app/services/workflow.py`). Reads are open; writes are scoped:

- a **team** workflow — the team's directors and managers (or an admin);
- a **project** override — planners who may edit the project;
- the **workspace template** — admins.

Core (ungated): every native project has a workflow, and `POST /tasks` uses it for the first
status. Status *changes* are moves (`POST /tasks/{id}/move`), gated by `tracking.native`.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.api.deps import AdminUser, ContributorWriter, CurrentUser, PlannerWriter, SessionDep
from app.api.v1.tasks import actor_name
from app.core.events import publish
from app.models.base import StatusCategory, WipEnforcement
from app.models.org import Team
from app.models.project import Project
from app.models.workflow import Workflow, WorkflowStatus
from app.schemas.entities import WorkflowColumnRead, WorkflowRead, WorkflowUpdate
from app.services import workflow as workflow_service
from app.services.access import ensure_project_editable, ensure_team_manageable
from app.services.workflow import ColumnInput, TrackingError, WorkflowView

router = APIRouter()


def workflow_read(view: WorkflowView) -> WorkflowRead:
    return WorkflowRead(
        id=view.id,
        scope=view.scope,
        team_id=view.team_id,
        project_id=view.project_id,
        name=view.name,
        wip_enforcement=WipEnforcement(view.wip_enforcement),
        inherited=view.inherited,
        columns=[
            WorkflowColumnRead(
                name=c.name,
                category=StatusCategory(c.category),
                position=c.position,
                wip_limit=c.wip_limit,
            )
            for c in view.columns
        ],
    )


def _inputs(payload: WorkflowUpdate) -> list[ColumnInput]:
    return [
        ColumnInput(
            name=c.name,
            category=c.category.value,
            wip_limit=c.wip_limit,
            previous_name=c.previous_name,
        )
        for c in payload.columns
    ]


async def _save(
    session: AsyncSession,
    *,
    team_id: int | None,
    project_id: int | None,
    payload: WorkflowUpdate,
    actor: str,
) -> WorkflowRead:
    try:
        view = await workflow_service.save_workflow(
            session,
            team_id=team_id,
            project_id=project_id,
            name=payload.name,
            wip_enforcement=payload.wip_enforcement.value,
            columns=_inputs(payload),
            move_tasks_to=payload.move_tasks_to,
            actor=actor,
        )
    except TrackingError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail()) from exc
    await session.commit()
    await publish({"type": "workflow", "team_id": team_id, "project_id": project_id})
    return workflow_read(view)


async def _project(session: AsyncSession, project_id: int) -> Project:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


async def _team(session: AsyncSession, team_id: int) -> Team:
    team = await session.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    return team


async def _refuse_tracker_owned(session: SessionDep, project: Project) -> None:
    view = await workflow_service.tracker_view(session, project)
    if view is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "workflow_externally_owned",
                "message": f"This project's columns come from its tracker ({view.name}); "
                "change them there — canopy picks them up on the next full sync.",
            },
        )


@router.get("/projects/{project_id}/workflow", response_model=WorkflowRead)
async def get_project_workflow(
    session: SessionDep, _: CurrentUser, project_id: int
) -> WorkflowRead:
    """The workflow this project's board uses (`inherited` = its team's or the template)."""
    project = await _project(session, project_id)
    return workflow_read(await workflow_service.resolve_workflow(session, project))


@router.put("/projects/{project_id}/workflow", response_model=WorkflowRead)
async def put_project_workflow(
    session: SessionDep, user: PlannerWriter, project_id: int, payload: WorkflowUpdate
) -> WorkflowRead:
    """Give this project its own columns, overriding its team's (use only when it must
    differ). Removing a column that holds tasks needs `move_tasks_to`. A mirrored project's
    columns are its tracker's statuses — edit those in the tracker (409)."""
    project = await _project(session, project_id)
    await ensure_project_editable(session, user, project_id)
    await _refuse_tracker_owned(session, project)
    return await _save(
        session, team_id=None, project_id=project_id, payload=payload, actor=actor_name(user)
    )


@router.delete("/projects/{project_id}/workflow", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project_workflow(
    session: SessionDep, user: PlannerWriter, project_id: int
) -> None:
    """Drop the project's override; its board goes back to the team's (or the template's)
    columns. Tasks keep their statuses — any the inherited workflow lacks show as extra
    columns until moved."""
    await _project(session, project_id)
    await ensure_project_editable(session, user, project_id)
    row = (
        await session.execute(select(Workflow).where(Workflow.project_id == project_id))
    ).scalars().first()
    if row is None:
        return
    for column in (
        await session.execute(select(WorkflowStatus).where(WorkflowStatus.workflow_id == row.id))
    ).scalars().all():
        await session.delete(column)
    await session.flush()
    await session.delete(row)
    await session.commit()
    await publish({"type": "workflow", "team_id": None, "project_id": project_id})


@router.get("/teams/{team_id}/workflow", response_model=WorkflowRead)
async def get_team_workflow(session: SessionDep, _: CurrentUser, team_id: int) -> WorkflowRead:
    """The columns every project of the team shares (`inherited` = the workspace template)."""
    await _team(session, team_id)
    return workflow_read(await workflow_service.team_workflow(session, team_id))


@router.put("/teams/{team_id}/workflow", response_model=WorkflowRead)
async def put_team_workflow(
    session: SessionDep, user: ContributorWriter, team_id: int, payload: WorkflowUpdate
) -> WorkflowRead:
    """Set the team's board columns and WIP limits, shared by all its projects (except those
    with their own override). The team's directors and managers, or an admin."""
    await _team(session, team_id)
    await ensure_team_manageable(session, user, team_id)
    return await _save(
        session, team_id=team_id, project_id=None, payload=payload, actor=actor_name(user)
    )


@router.get("/workflows/template", response_model=WorkflowRead)
async def get_workflow_template(session: SessionDep, _: CurrentUser) -> WorkflowRead:
    """The workspace default that teams and team-less projects start from."""
    return workflow_read(await workflow_service.template_workflow(session))


@router.put("/workflows/template", response_model=WorkflowRead)
async def put_workflow_template(
    session: SessionDep, user: AdminUser, payload: WorkflowUpdate
) -> WorkflowRead:
    return await _save(
        session, team_id=None, project_id=None, payload=payload, actor=actor_name(user)
    )
