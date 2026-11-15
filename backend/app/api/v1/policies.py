"""Stage policies — docs/AGENT_EXECUTION.md §9.1, §13, Appendix A (feature gate `ai.stage_policy`).

Policies belong to a workflow's columns and resolve with them: a project uses its own columns'
policies when it overrides its team's, else the team's, else the workspace template's, else the
built-in default. Reads are open; every write is **human-only** and limited to the people who may
edit the workflow at that scope (project planners · the team's directors and managers · admins
for the template) — an agent must not be able to loosen its own guardrails.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.api.deps import (
    AdminUser,
    ContributorWriter,
    CurrentUser,
    HumanOnly,
    PlannerWriter,
    SessionDep,
    TokenScopeDep,
)
from app.api.v1.tasks import actor_name
from app.core.events import publish
from app.models.base import (
    CANOPY_OWNER,
    TaskType,
    TokenScope,
    UserRole,
    WipEnforcement,
)
from app.models.org import Team
from app.models.project import Project, Task
from app.models.user import User
from app.schemas.policy import (
    PipelineRead,
    PolicyUpdate,
    StageColumnRead,
    TemplateApplyRequest,
    TemplateColumnRead,
    TemplateMoveRead,
    TemplatePreview,
)
from app.services import policy_store, policy_template, stage_policy
from app.services import workflow as workflow_service
from app.services.access import (
    ensure_project_editable,
    ensure_team_manageable,
    project_can_edit,
    team_can_manage,
)
from app.services.workflow import TrackingError, WorkflowView

router = APIRouter()


def pipeline_read(
    view: WorkflowView, pipeline: stage_policy.Pipeline, *, can_edit: bool
) -> PipelineRead:
    columns: list[StageColumnRead] = []
    for stage in pipeline.stages:
        column = view.column(stage.status_name)
        columns.append(StageColumnRead(
            status=stage.status_name, category=stage.category, position=stage.position,
            wip_limit=column.wip_limit if column is not None else None,
            worked_by=stage.worked_by,
            hands_off=stage.hands_off if stage.is_agent_stage else None,
            source=stage.source,
            # The built-in default's stages carry their documents too, so a first edit saves
            # them explicitly instead of silently dropping the default implementer stage.
            policy=stage.policy_doc() if stage.has_policy or stage.source == "default" else None,
        ))
    return PipelineRead(
        scope=view.scope, inherited=view.inherited, workflow_id=view.id, team_id=view.team_id,
        configured=pipeline.configured, wip_enforcement=view.wip_enforcement,
        roles=pipeline.roles(), columns=columns, can_edit=can_edit,
    )


async def _view_pipeline(session: AsyncSession, view: WorkflowView) -> stage_policy.Pipeline:
    policies = await policy_store.policies_of_view(session, view)
    return stage_policy.pipeline_from_policies(view.columns, policies, strict=False)


def _human(scope: TokenScope) -> None:
    if scope == TokenScope.agent:
        raise HTTPException(status_code=403, detail={
            "code": "human_only", "message": "Stage policy is changed by people, in canopy"})


def _inherited(where: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail={
        "code": "workflow_inherited",
        "message": f"{where} has no columns of its own — policies attach to columns. Save its "
                   "columns first, or apply the agentic-delivery template.",
    })


async def _project(session: AsyncSession, project_id: int) -> Project:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


async def _refuse_tracker_owned(session: AsyncSession, project: Project) -> None:
    if await workflow_service.tracker_view(session, project) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={
            "code": "workflow_externally_owned",
            "message": "This project's columns are its tracker's statuses, so the template's "
                       "columns can't be applied — give the tracker's statuses policies instead.",
        })


async def _save_policies(
    session: AsyncSession, user: User, view: WorkflowView, policies: dict[str, Any],
    *, team_id: int | None, project_id: int | None, template: str | None = None,
) -> stage_policy.Pipeline:
    try:
        return await policy_template.save_policies(
            session, user, view, policies, team_id=team_id, project_id=project_id,
            template=template)
    except stage_policy.PolicyError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail={
            "code": "policy_invalid", "message": str(exc), "column": exc.column}) from exc


async def _published(team_id: int | None, project_id: int | None) -> None:
    await publish({"type": "workflow", "team_id": team_id, "project_id": project_id})


# --------------------------------------------------------------------------- #
# Read / replace at each scope
# --------------------------------------------------------------------------- #


@router.get("/projects/{project_id}/workflow/policy", response_model=PipelineRead)
async def get_project_policy(
    session: SessionDep, user: CurrentUser, scope: TokenScopeDep, project_id: int
) -> PipelineRead:
    """The project's pipeline: each column with who works it and its policy, from wherever its
    columns come from (`scope`; `configured` false = the built-in default)."""
    project = await _project(session, project_id)
    view = await workflow_service.resolve_workflow(session, project)
    can_edit = scope != TokenScope.agent and (
        # A mirrored project's statuses are its tracker's; their policies are the project's
        # planners' to set (§17).
        (view.scope in ("project", "tracker") and await project_can_edit(session, user, project))
        or (view.scope == "team" and view.team_id is not None
            and await team_can_manage(session, user, view.team_id))
        or (view.scope == "template" and user.role == UserRole.admin)
    )
    return pipeline_read(view, await _view_pipeline(session, view), can_edit=can_edit)


@router.put("/projects/{project_id}/workflow/policy", response_model=PipelineRead)
async def put_project_policy(
    session: SessionDep, user: PlannerWriter, _human: HumanOnly, project_id: int,
    payload: PolicyUpdate,
) -> PipelineRead:
    """Replace the stage policies of this project's own columns — or, on a mirrored project,
    of its tracker's statuses (stored on the binding, §17). Human-only."""
    project = await _project(session, project_id)
    await ensure_project_editable(session, user, project_id)
    view = await workflow_service.resolve_workflow(session, project)
    if view.scope == "tracker":
        if view.binding_id is None:
            raise _inherited("This project")
    elif view.scope != "project" or view.id is None:
        raise _inherited("This project")
    pipeline = await _save_policies(session, user, view, payload.policies, team_id=None,
                                    project_id=project_id)
    await session.commit()
    await _published(None, project_id)
    return pipeline_read(view, pipeline, can_edit=True)


@router.get("/teams/{team_id}/workflow/policy", response_model=PipelineRead)
async def get_team_policy(
    session: SessionDep, user: CurrentUser, scope: TokenScopeDep, team_id: int
) -> PipelineRead:
    if await session.get(Team, team_id) is None:
        raise HTTPException(status_code=404, detail="Team not found")
    view = await workflow_service.team_workflow(session, team_id)
    can_edit = scope != TokenScope.agent and not view.inherited and await team_can_manage(
        session, user, team_id)
    return pipeline_read(view, await _view_pipeline(session, view), can_edit=can_edit)


@router.put("/teams/{team_id}/workflow/policy", response_model=PipelineRead)
async def put_team_policy(
    session: SessionDep, user: ContributorWriter, _human: HumanOnly, team_id: int,
    payload: PolicyUpdate,
) -> PipelineRead:
    """Replace the stage policies of the team's columns, shared by its projects (human-only;
    the team's directors and managers)."""
    if await session.get(Team, team_id) is None:
        raise HTTPException(status_code=404, detail="Team not found")
    await ensure_team_manageable(session, user, team_id)
    view = await workflow_service.team_workflow(session, team_id)
    if view.inherited or view.id is None:
        raise _inherited("This team")
    pipeline = await _save_policies(session, user, view, payload.policies, team_id=team_id,
                                    project_id=None)
    await session.commit()
    await _published(team_id, None)
    return pipeline_read(view, pipeline, can_edit=True)


@router.get("/workflows/template/policy", response_model=PipelineRead)
async def get_template_policy(
    session: SessionDep, user: CurrentUser, scope: TokenScopeDep
) -> PipelineRead:
    view = await workflow_service.template_workflow(session)
    can_edit = scope != TokenScope.agent and view.id is not None and user.role == UserRole.admin
    return pipeline_read(view, await _view_pipeline(session, view), can_edit=can_edit)


@router.put("/workflows/template/policy", response_model=PipelineRead)
async def put_template_policy(
    session: SessionDep, user: AdminUser, _human: HumanOnly, payload: PolicyUpdate
) -> PipelineRead:
    view = await workflow_service.template_workflow(session)
    if view.id is None:
        raise _inherited("The workspace template")
    pipeline = await _save_policies(session, user, view, payload.policies, team_id=None,
                                    project_id=None)
    await session.commit()
    await _published(None, None)
    return pipeline_read(view, pipeline, can_edit=True)


# --------------------------------------------------------------------------- #
# The agentic-delivery template (Appendix A)
# --------------------------------------------------------------------------- #


async def _cards_by_status(session: AsyncSession, project_ids: list[int]) -> dict[str, int]:
    """Canopy-owned cards per status (casefolded) — what a column change moves."""
    if not project_ids:
        return {}
    rows = (await session.execute(
        select(Task.status).where(
            col(Task.project_id).in_(project_ids), Task.status_owner == CANOPY_OWNER,
            Task.type != TaskType.summary,
        )
    )).scalars().all()
    counts: dict[str, int] = {}
    for status_name in rows:
        if status_name:
            counts[status_name.casefold()] = counts.get(status_name.casefold(), 0) + 1
    return counts


def _unknown_status(exc: policy_template.UnknownStatusError) -> HTTPException:
    return HTTPException(status_code=422, detail={"code": "unknown_status", "message": str(exc)})


async def _apply_template(
    session: AsyncSession, user: User, scope: TokenScope, payload: TemplateApplyRequest, *,
    team_id: int | None, project_id: int | None,
) -> TemplatePreview:
    columns, policies = stage_policy.agentic_delivery_template()
    current = await workflow_service.current_view(session, team_id=team_id, project_id=project_id)
    try:
        moves = policy_template.suggest_moves(current.columns, columns, payload.move_tasks_to)
    except policy_template.UnknownStatusError as exc:
        raise _unknown_status(exc) from exc
    project_ids = [p.id for p in await workflow_service.projects_using_scope(
        session, team_id=team_id, project_id=project_id) if p.id is not None]
    counts = await _cards_by_status(session, project_ids)
    preview = TemplatePreview(
        template=stage_policy.TEMPLATE_KEY,
        columns=[TemplateColumnRead(name=name, category=category,
                                    worked_by=(policies.get(name) or {}).get("worked_by"),
                                    policy=policies.get(name))
                 for name, category in columns],
        current_columns=[c.name for c in current.columns],
        moves=[TemplateMoveRead(from_status=old, to_status=new,
                                tasks=counts.get(old.casefold(), 0))
               for old, new in moves.items()],
        wip_enforcement=WipEnforcement.block.value,
    )
    if payload.dry_run:
        return preview
    _human(scope)
    try:
        view, pipeline = await policy_template.apply_template(
            session, user, actor=actor_name(user), team_id=team_id, project_id=project_id,
            move_tasks_to=payload.move_tasks_to)
    except TrackingError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail()) from exc
    except stage_policy.PolicyError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail={
            "code": "policy_invalid", "message": str(exc), "column": exc.column}) from exc
    await session.commit()
    await _published(team_id, project_id)
    preview.applied = True
    preview.pipeline = pipeline_read(view, pipeline, can_edit=True)
    return preview


@router.post("/projects/{project_id}/workflow/apply-template", response_model=TemplatePreview)
async def apply_project_template(
    session: SessionDep, user: PlannerWriter, scope: TokenScopeDep, project_id: int,
    payload: TemplateApplyRequest,
) -> TemplatePreview:
    """Preview (`dry_run`, the default), then save, the Appendix A columns and policies as this
    project's own: where each current column's cards go, and WIP enforcement `block`. Saving is
    human-only."""
    project = await _project(session, project_id)
    await ensure_project_editable(session, user, project_id)
    await _refuse_tracker_owned(session, project)
    return await _apply_template(session, user, scope, payload, team_id=None,
                                 project_id=project_id)


@router.post("/teams/{team_id}/workflow/apply-template", response_model=TemplatePreview)
async def apply_team_template(
    session: SessionDep, user: ContributorWriter, scope: TokenScopeDep, team_id: int,
    payload: TemplateApplyRequest,
) -> TemplatePreview:
    """The same for a team's shared columns (its directors and managers)."""
    if await session.get(Team, team_id) is None:
        raise HTTPException(status_code=404, detail="Team not found")
    await ensure_team_manageable(session, user, team_id)
    return await _apply_template(session, user, scope, payload, team_id=team_id,
                                 project_id=None)
