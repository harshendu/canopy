"""Retrospectives & postmortems. A project retro auto-seeds its body from project state
(milestones, schedule variance, drift, ADR churn — pure renderer in services/retro.py);
both kinds gather a comment thread and can mint follow-up tasks or propose ADRs."""

from datetime import date

from fastapi import APIRouter, HTTPException, status
from sqlmodel import col, select

from app.api.deps import ContributorWriter, CurrentUser, PlannerWriter, SessionDep
from app.api.v1.architecture import _next_number, _set_component_links
from app.models.architecture import ArchitectureDecision
from app.models.base import ADRStatus, RetrospectiveKind, TaskType
from app.models.project import Milestone, Project, Task
from app.models.retro import Retrospective, RetrospectiveComment
from app.schemas.entities import (
    RetroFollowUpRequest,
    RetroFollowUpResponse,
    RetrospectiveCommentCreate,
    RetrospectiveCommentRead,
    RetrospectiveCreate,
    RetrospectiveDetail,
    RetrospectiveRead,
    RetrospectiveUpdate,
)
from app.services.retro import RetroInputs, generate_project_retro

router = APIRouter()


async def _project_or_404(session: SessionDep, project_id: int) -> Project:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


async def _retro_or_404(
    session: SessionDep, project_id: int, retro_id: int
) -> Retrospective:
    retro = await session.get(Retrospective, retro_id)
    if retro is None or retro.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Retrospective not found")
    return retro


async def _seed_project_retro(session: SessionDep, project: Project) -> str:
    assert project.id is not None
    tasks = list(
        (await session.execute(select(Task).where(Task.project_id == project.id))).scalars().all()
    )
    leaves = [t for t in tasks if t.type != TaskType.summary]
    milestones = list(
        (
            await session.execute(select(Milestone).where(Milestone.project_id == project.id))
        ).scalars().all()
    )
    from app.models.architecture import DriftEvent  # local import keeps the module graph flat

    open_drift = len(
        [
            e
            for e in (
                await session.execute(
                    select(DriftEvent).where(DriftEvent.project_id == project.id)
                )
            ).scalars().all()
            if e.status == "open"
        ]
    )
    adrs = list(
        (
            await session.execute(
                select(ArchitectureDecision).where(
                    ArchitectureDecision.project_id == project.id
                )
            )
        ).scalars().all()
    )
    inputs = RetroInputs(
        project_name=project.name,
        generated_on=date.today(),
        completed_milestones=[
            f"{m.name} ({m.target_date})" if m.target_date else m.name
            for m in milestones
            if m.status.lower() in {"hit", "done"}
        ],
        total_tasks=len(leaves),
        completed_tasks=sum(1 for t in leaves if t.percent_complete >= 100),
        drifted_tasks=sum(
            1 for t in leaves if t.baseline_end is not None and t.end != t.baseline_end
        ),
        open_drift_events=open_drift,
        adr_total=len(adrs),
        adr_accepted=sum(1 for a in adrs if a.status == ADRStatus.accepted),
        adr_superseded=sum(1 for a in adrs if a.status == ADRStatus.superseded),
    )
    return generate_project_retro(inputs)


@router.get("/projects/{project_id}/retrospectives", response_model=list[RetrospectiveRead])
async def list_retrospectives(
    session: SessionDep, _: CurrentUser, project_id: int
) -> list[Retrospective]:
    result = await session.execute(
        select(Retrospective)
        .where(Retrospective.project_id == project_id)
        .order_by(col(Retrospective.id).desc())
    )
    return list(result.scalars().all())


@router.post(
    "/projects/{project_id}/retrospectives",
    response_model=RetrospectiveRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_retrospective(
    session: SessionDep, _: PlannerWriter, project_id: int, payload: RetrospectiveCreate
) -> Retrospective:
    project = await _project_or_404(session, project_id)
    if payload.kind == RetrospectiveKind.project_retro:
        title = payload.title or f"{project.name} retrospective"
        body = payload.body or await _seed_project_retro(session, project)
    else:
        title = payload.title or "Incident postmortem"
        body = payload.body or (
            "# Incident postmortem\n\n## Timeline\n\n## Impact\n\n"
            "## Root cause\n\n## Action items\n"
        )
    retro = Retrospective(
        project_id=project_id,
        kind=payload.kind,
        title=title,
        body=body,
        affected_component_ids=payload.affected_component_ids,
    )
    session.add(retro)
    await session.commit()
    await session.refresh(retro)
    return retro


@router.get(
    "/projects/{project_id}/retrospectives/{retro_id}", response_model=RetrospectiveDetail
)
async def get_retrospective(
    session: SessionDep, _: CurrentUser, project_id: int, retro_id: int
) -> RetrospectiveDetail:
    retro = await _retro_or_404(session, project_id, retro_id)
    comments = list(
        (
            await session.execute(
                select(RetrospectiveComment)
                .where(RetrospectiveComment.retrospective_id == retro_id)
                .order_by(col(RetrospectiveComment.id))
            )
        ).scalars().all()
    )
    return RetrospectiveDetail(
        **RetrospectiveRead.model_validate(retro).model_dump(),
        comments=[RetrospectiveCommentRead.model_validate(c) for c in comments],
    )


@router.patch(
    "/projects/{project_id}/retrospectives/{retro_id}", response_model=RetrospectiveRead
)
async def update_retrospective(
    session: SessionDep,
    _: PlannerWriter,
    project_id: int,
    retro_id: int,
    payload: RetrospectiveUpdate,
) -> Retrospective:
    retro = await _retro_or_404(session, project_id, retro_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(retro, field, value)
    await session.commit()
    await session.refresh(retro)
    return retro


@router.post(
    "/projects/{project_id}/retrospectives/{retro_id}/comments",
    response_model=RetrospectiveCommentRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_retrospective_comment(
    session: SessionDep,
    _: ContributorWriter,
    project_id: int,
    retro_id: int,
    payload: RetrospectiveCommentCreate,
) -> RetrospectiveComment:
    await _retro_or_404(session, project_id, retro_id)
    comment = RetrospectiveComment(
        retrospective_id=retro_id,
        body=payload.body,
        engineer_id=payload.engineer_id,
        author_name=payload.author_name,
    )
    session.add(comment)
    await session.commit()
    await session.refresh(comment)
    return comment


@router.post(
    "/projects/{project_id}/retrospectives/{retro_id}/follow-up",
    response_model=RetroFollowUpResponse,
)
async def retrospective_follow_up(
    session: SessionDep,
    _: PlannerWriter,
    project_id: int,
    retro_id: int,
    payload: RetroFollowUpRequest,
) -> RetroFollowUpResponse:
    retro = await _retro_or_404(session, project_id, retro_id)
    if payload.action == "task":
        task = Task(project_id=project_id, name=payload.title[:200], type=TaskType.task)
        session.add(task)
        await session.flush()
        task_id = task.id
        await session.commit()
        return RetroFollowUpResponse(created_task_id=task_id)
    if payload.action == "adr":
        adr = ArchitectureDecision(
            project_id=project_id,
            number=await _next_number(session, project_id),
            title=payload.title[:200],
            context=f"Follow-up from retrospective: {retro.title}",
            status=ADRStatus.proposed,
        )
        session.add(adr)
        await session.flush()
        assert adr.id is not None
        await _set_component_links(session, adr.id, retro.affected_component_ids)
        adr_id = adr.id
        await session.commit()
        return RetroFollowUpResponse(created_adr_id=adr_id)
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST, detail="action must be task | adr"
    )
