"""Initiatives: the program layer above projects. CRUD plus a rollup that aggregates
health (risk / drift / progress / decision backlog) across an initiative's sub-projects."""

from datetime import date

from fastapi import APIRouter, HTTPException, status
from sqlmodel import col, select

from app.api.deps import ArchitectWriter, CurrentUser, SessionDep
from app.api.v1.projects import summarize_project
from app.models.activity import ActivityEvent
from app.models.architecture import ArchitectureDecision, DriftEvent
from app.models.base import ADRStatus, TaskType
from app.models.project import Dependency, Initiative, Project, Task
from app.models.team import Allocation, Engineer
from app.schemas.entities import (
    CriticalPathHandoff,
    CriticalPathNode,
    InitiativeCreate,
    InitiativeCriticalPath,
    InitiativeRead,
    InitiativeRollup,
    InitiativeUpdate,
    ProjectSummary,
)
from app.services.cross_project import CPDep, CPTask, cross_project_critical_path
from app.services.drift import level as drift_level
from app.services.scheduling import CycleError

router = APIRouter()

_OPEN_DECISION_STATUSES = {ADRStatus.proposed, ADRStatus.under_discussion}


@router.get("", response_model=list[InitiativeRead])
async def list_initiatives(session: SessionDep, _: CurrentUser) -> list[Initiative]:
    result = await session.execute(select(Initiative).order_by(col(Initiative.name)))
    return list(result.scalars().all())


@router.post("", response_model=InitiativeRead, status_code=status.HTTP_201_CREATED)
async def create_initiative(
    session: SessionDep, _: ArchitectWriter, payload: InitiativeCreate
) -> Initiative:
    existing = await session.execute(select(Initiative).where(Initiative.key == payload.key))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Initiative key exists")
    initiative = Initiative(**payload.model_dump())
    session.add(initiative)
    await session.commit()
    await session.refresh(initiative)
    return initiative


@router.get("/{initiative_id}", response_model=InitiativeRead)
async def get_initiative(
    session: SessionDep, _: CurrentUser, initiative_id: int
) -> Initiative:
    initiative = await session.get(Initiative, initiative_id)
    if initiative is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Initiative not found")
    return initiative


@router.patch("/{initiative_id}", response_model=InitiativeRead)
async def update_initiative(
    session: SessionDep, _: ArchitectWriter, initiative_id: int, payload: InitiativeUpdate
) -> Initiative:
    initiative = await session.get(Initiative, initiative_id)
    if initiative is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Initiative not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(initiative, field, value)
    await session.commit()
    await session.refresh(initiative)
    return initiative


@router.delete("/{initiative_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_initiative(
    session: SessionDep, _: ArchitectWriter, initiative_id: int
) -> None:
    initiative = await session.get(Initiative, initiative_id)
    if initiative is None:
        return
    # Unlink sub-projects rather than cascade-deleting them (projects outlive initiatives).
    projects = (
        await session.execute(select(Project).where(Project.initiative_id == initiative_id))
    ).scalars().all()
    for project in projects:
        project.initiative_id = None
    await session.delete(initiative)
    await session.commit()


@router.get("/{initiative_id}/rollup", response_model=InitiativeRollup)
async def initiative_rollup(
    session: SessionDep, _: CurrentUser, initiative_id: int
) -> InitiativeRollup:
    initiative = await session.get(Initiative, initiative_id)
    if initiative is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Initiative not found")

    projects = list(
        (
            await session.execute(
                select(Project)
                .where(Project.initiative_id == initiative_id)
                .order_by(col(Project.name))
            )
        ).scalars().all()
    )
    engineer_names = {
        e.id: e.name
        for e in (await session.execute(select(Engineer))).scalars().all()
        if e.id is not None
    }
    today = date.today()

    summaries: list[ProjectSummary] = []
    open_decisions = 0
    for project in projects:
        assert project.id is not None
        tasks = list(
            (
                await session.execute(select(Task).where(Task.project_id == project.id))
            ).scalars().all()
        )
        allocations = list(
            (
                await session.execute(
                    select(Allocation).where(Allocation.project_id == project.id)
                )
            ).scalars().all()
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
        drift_events = list(
            (
                await session.execute(
                    select(DriftEvent).where(DriftEvent.project_id == project.id)
                )
            ).scalars().all()
        )
        activity_events = list(
            (
                await session.execute(
                    select(ActivityEvent).where(ActivityEvent.project_id == project.id)
                )
            ).scalars().all()
        )
        open_decisions += sum(1 for a in adrs if a.status in _OPEN_DECISION_STATUSES)
        summaries.append(
            summarize_project(
                project,
                tasks=tasks,
                allocations=allocations,
                engineer_names=engineer_names,
                adrs=adrs,
                drift_events=drift_events,
                activity_events=activity_events,
                today=today,
            )
        )

    total_tasks = sum(s.total_tasks for s in summaries)
    completed_tasks = sum(s.completed_tasks for s in summaries)
    avg = (
        sum(s.avg_percent_complete * s.total_tasks for s in summaries) / total_tasks
        if total_tasks
        else 0.0
    )
    ends = [s.project_end for s in summaries if s.project_end]
    project_end = max(ends) if ends else None
    # The riskiest / most-drifted sub-project drives the initiative's headline numbers.
    risk_score = max((s.risk_score for s in summaries), default=0)
    drift_score = max((s.drift_score for s in summaries), default=0)
    on_track: bool | None = None
    if initiative.target_date is not None and project_end is not None:
        on_track = project_end <= initiative.target_date

    return InitiativeRollup(
        initiative=InitiativeRead.model_validate(initiative),
        projects=summaries,
        total_tasks=total_tasks,
        completed_tasks=completed_tasks,
        avg_percent_complete=round(avg, 1),
        project_end=project_end,
        risk_score=risk_score,
        risk_level=summaries_level(summaries, risk_score, "risk"),
        drift_score=drift_score,
        drift_level=drift_level(drift_score),
        open_decisions=open_decisions,
        on_track=on_track,
    )


@router.get("/{initiative_id}/critical-path", response_model=InitiativeCriticalPath)
async def initiative_critical_path(
    session: SessionDep, _: CurrentUser, initiative_id: int
) -> InitiativeCriticalPath:
    """The critical path across the initiative's sub-projects, including cross-project hand-offs.

    Built over the union of the initiative's tasks + dependencies (intra- and cross-project)
    with the same CPM as per-project scheduling — a structural critical path in working days."""
    initiative = await session.get(Initiative, initiative_id)
    if initiative is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Initiative not found")

    project_keys = {
        p.id: p.key
        for p in (
            await session.execute(
                select(Project).where(Project.initiative_id == initiative_id)
            )
        ).scalars().all()
        if p.id is not None
    }
    tasks = (
        list(
            (
                await session.execute(
                    select(Task).where(col(Task.project_id).in_(set(project_keys)))
                )
            ).scalars().all()
        )
        if project_keys
        else []
    )
    task_names = {t.id: t.name for t in tasks if t.id is not None}
    task_ids = set(task_names)
    deps = [
        d
        for d in (await session.execute(select(Dependency))).scalars().all()
        if d.predecessor_id in task_ids and d.successor_id in task_ids
    ]

    try:
        result = cross_project_critical_path(
            [
                CPTask(
                    id=t.id,
                    project_id=t.project_id,
                    duration=t.duration,
                    is_summary=t.type == TaskType.summary,
                )
                for t in tasks
                if t.id is not None
            ],
            [CPDep(d.predecessor_id, d.successor_id, d.type.value, d.lag) for d in deps],
        )
    except CycleError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return InitiativeCriticalPath(
        initiative_id=initiative_id,
        total_working_days=result.total_working_days,
        spans_projects=result.spans_projects,
        tasks=[
            CriticalPathNode(
                task_id=n.task_id,
                name=task_names.get(n.task_id, f"#{n.task_id}"),
                project_id=n.project_id,
                project_key=project_keys.get(n.project_id, f"#{n.project_id}"),
                es=n.es,
                ef=n.ef,
                duration=n.duration,
            )
            for n in result.nodes
        ],
        handoffs=[
            CriticalPathHandoff(
                predecessor_id=h.predecessor_id,
                successor_id=h.successor_id,
                from_project_key=project_keys.get(h.from_project_id, f"#{h.from_project_id}"),
                to_project_key=project_keys.get(h.to_project_id, f"#{h.to_project_id}"),
            )
            for h in result.handoffs
        ],
    )


def summaries_level(summaries: list[ProjectSummary], score: int, which: str) -> str:
    """The level string belonging to the sub-project that owns the max score (so the
    initiative's level matches its riskiest/most-drifted project rather than re-deriving)."""
    for s in summaries:
        value = s.risk_score if which == "risk" else s.drift_score
        level = s.risk_level if which == "risk" else s.drift_level
        if value == score:
            return level
    return "low"
