"""Initiatives: the program layer above projects. CRUD plus a rollup that aggregates
health (risk / drift / progress / decision backlog) across an initiative's sub-projects."""

from datetime import date

from fastapi import APIRouter, HTTPException, status
from sqlmodel import col, select

from app.api.deps import ArchitectWriter, CurrentUser, FeatureGate, SessionDep
from app.api.v1.projects import open_project_risk_counts, summarize_project
from app.models.activity import ActivityEvent
from app.models.architecture import ArchitectureDecision, DriftEvent
from app.models.base import ADRStatus, ProjectHealth, TaskType, utcnow
from app.models.outcome import Outcome
from app.models.project import (
    Blocker,
    Dependency,
    Initiative,
    Project,
    Task,
    TaskStatusHistory,
)
from app.models.risk_register import RiskItem
from app.models.team import Allocation, Engineer, EngineerAvailability
from app.schemas.entities import (
    CriticalPathHandoff,
    CriticalPathNode,
    ForecastResponse,
    InitiativeCreate,
    InitiativeCriticalPath,
    InitiativeDigest,
    InitiativeRead,
    InitiativeRollup,
    InitiativeUpdate,
    ProjectSummary,
)
from app.services import digest as digest_service
from app.services.burndown import is_done_status
from app.services.capacity import AvailabilitySpan
from app.services.cross_project import CPDep, CPTask, cross_project_critical_path
from app.services.drift import level as drift_level
from app.services.forecast import monte_carlo_forecast, weekly_throughput
from app.services.metadata import normalize_tags
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
    data = payload.model_dump()
    data["tags"] = normalize_tags(data.get("tags") or [])
    initiative = Initiative(**data)
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
    data = payload.model_dump(exclude_unset=True)
    if "tags" in data and data["tags"] is not None:
        data["tags"] = normalize_tags(data["tags"])
    for field, value in data.items():
        setattr(initiative, field, value)
    if "health" in data or "status_note" in data:
        initiative.status_updated_at = utcnow()
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
    availability = [
        AvailabilitySpan(a.engineer_id, a.capacity_factor, a.start_date, a.end_date)
        for a in (await session.execute(select(EngineerAvailability))).scalars().all()
    ]
    today = date.today()
    open_risks_by_project = open_project_risk_counts(
        list((await session.execute(select(RiskItem))).scalars().all())
    )

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
                availability=availability,
                open_risks=open_risks_by_project.get(project.id, 0),
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


@router.get("/{initiative_id}/digest", response_model=InitiativeDigest)
async def initiative_digest(
    session: SessionDep, user: CurrentUser, initiative_id: int
) -> InitiativeDigest:
    """A manage-by-exception weekly health roll-up (leads with what needs attention). Reuses the
    rollup + forecast and adds open blockers + outcomes. Delivery (Slack/email) is a hook over
    this output, not built here (same posture as the alerts digest §I)."""
    rollup = await initiative_rollup(session, user, initiative_id)
    forecast = await initiative_forecast(session, user, initiative_id)

    pids = [p.id for p in rollup.projects]
    open_blockers = 0
    if pids:
        task_ids = [
            t
            for t in (
                await session.execute(select(col(Task.id)).where(col(Task.project_id).in_(pids)))
            ).scalars()
            if t is not None
        ]
        if task_ids:
            open_blockers = len(
                list(
                    (
                        await session.execute(
                            select(Blocker).where(
                                col(Blocker.task_id).in_(task_ids),
                                col(Blocker.resolved_at).is_(None),
                            )
                        )
                    ).scalars()
                )
            )

    outcomes = list(
        (
            await session.execute(
                select(Outcome).where(
                    Outcome.scope_level == "initiative", Outcome.scope_id == initiative_id
                )
            )
        ).scalars()
    )
    at_risk = [
        p.name
        for p in rollup.projects
        if (p.health in (ProjectHealth.at_risk, ProjectHealth.off_track))
        or p.risk_level in ("high", "critical")
    ]
    inputs = digest_service.DigestInputs(
        name=rollup.initiative.name,
        generated_on=date.today(),
        on_track=rollup.on_track,
        target_date=rollup.initiative.target_date,
        project_end=rollup.project_end,
        p85_date=forecast.p85_date,
        forecast_sufficient=forecast.sufficient,
        risk_level=rollup.risk_level,
        drift_level=rollup.drift_level,
        avg_percent_complete=rollup.avg_percent_complete,
        completed_tasks=rollup.completed_tasks,
        total_tasks=rollup.total_tasks,
        open_decisions=rollup.open_decisions,
        open_blockers=open_blockers,
        at_risk_projects=at_risk,
        outcomes=[f"{o.statement} ({o.status})" for o in outcomes],
    )
    attention = digest_service.attention_items(inputs)
    return InitiativeDigest(
        initiative_id=initiative_id,
        name=inputs.name,
        generated_on=inputs.generated_on,
        headline=digest_service.headline(attention),
        on_track=rollup.on_track,
        risk_level=rollup.risk_level,
        drift_level=rollup.drift_level,
        p85_date=forecast.p85_date,
        open_blockers=open_blockers,
        open_decisions=rollup.open_decisions,
        attention=attention,
        outcomes=inputs.outcomes,
        markdown=digest_service.render_markdown(inputs, attention),
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


@router.get(
    "/{initiative_id}/forecast",
    response_model=ForecastResponse,
    dependencies=[FeatureGate("tracking.forecast")],
)
async def initiative_forecast(
    session: SessionDep, _: CurrentUser, initiative_id: int
) -> ForecastResponse:
    """Monte-Carlo completion forecast for the whole initiative — remaining items across all
    sub-projects, against the team's combined weekly throughput."""
    initiative = await session.get(Initiative, initiative_id)
    if initiative is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Initiative not found")
    project_ids = {
        p.id
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
                await session.execute(select(Task).where(col(Task.project_id).in_(project_ids)))
            ).scalars().all()
        )
        if project_ids
        else []
    )
    leaves = [t for t in tasks if t.type != TaskType.summary]
    remaining = sum(1 for t in leaves if t.percent_complete < 100)
    task_ids = {t.id for t in tasks}
    done_dates: list = []
    if task_ids:
        history = (
            await session.execute(
                select(TaskStatusHistory).where(col(TaskStatusHistory.task_id).in_(task_ids))
            )
        ).scalars().all()
        done_dates = sorted(h.changed_at.date() for h in history if is_done_status(h.to_status))
    today = date.today()
    result = monte_carlo_forecast(remaining, weekly_throughput(done_dates, today), today)
    return ForecastResponse(
        scope="initiative",
        id=initiative_id,
        sufficient=result.sufficient,
        reason=result.reason,
        remaining_items=result.remaining_items,
        history_weeks=result.history_weeks,
        trials=result.trials,
        p50_weeks=result.p50_weeks,
        p85_weeks=result.p85_weeks,
        p50_date=result.p50_date,
        p85_date=result.p85_date,
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
