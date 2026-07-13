from datetime import date

from fastapi import APIRouter, HTTPException, status
from sqlmodel import select

from app.api.deps import ArchitectWriter, CurrentUser, SessionDep
from app.api.v1.drift import drift_score_from_events
from app.api.v1.risk import report_for
from app.models.activity import ActivityEvent
from app.models.architecture import ArchitectureDecision, DriftEvent
from app.models.base import RiskScope, RiskStatus, TaskType, utcnow
from app.models.project import Holiday, Project, Task
from app.models.risk_register import RiskItem
from app.models.team import Allocation, Engineer, EngineerAvailability
from app.schemas.entities import (
    HolidayCreate,
    HolidayRead,
    PortfolioResponse,
    ProjectCreate,
    ProjectRead,
    ProjectSummary,
    ProjectUpdate,
)
from app.services.capacity import AvailabilitySpan
from app.services.cascade import delete_project_cascade
from app.services.drift import level as drift_level
from app.services.metadata import normalize_tags

router = APIRouter()


def summarize_project(
    project: Project,
    *,
    tasks: list[Task],
    allocations: list[Allocation],
    engineer_names: dict[int, str],
    adrs: list[ArchitectureDecision],
    drift_events: list[DriftEvent],
    activity_events: list[ActivityEvent],
    today: date,
    availability: list[AvailabilitySpan] | None = None,
    open_risks: int = 0,
) -> ProjectSummary:
    """Build a project's portfolio summary (risk + drift + progress) from loaded rows.

    Shared by the portfolio rollup and the initiative rollup so a project's headline numbers
    are computed in exactly one place. `open_risks` is the count of open register risks
    (the human RAID register) — separate from the computed risk score."""
    assert project.id is not None
    leaves = [t for t in tasks if t.type != TaskType.summary]
    total = len(leaves)
    completed = sum(1 for t in leaves if t.percent_complete >= 100)
    avg = sum(t.percent_complete for t in leaves) / total if total else 0.0
    ends = [t.end for t in tasks if t.end]
    drift = drift_score_from_events(drift_events)
    report = report_for(
        tasks=tasks,
        allocations=allocations,
        engineer_names=engineer_names,
        adrs=adrs,
        project_start=project.start_date,
        project_target=project.target_date,
        today=today,
        drift_score=drift,
        activity_events=activity_events,
        availability=availability,
    )
    return ProjectSummary(
        id=project.id,
        key=project.key,
        name=project.name,
        total_tasks=total,
        completed_tasks=completed,
        avg_percent_complete=round(avg, 1),
        critical_tasks=sum(1 for t in leaves if t.is_critical),
        project_end=max(ends) if ends else None,
        target_date=project.target_date,
        risk_score=report.score,
        risk_level=report.level,
        drift_score=drift,
        drift_level=drift_level(drift),
        tags=project.tags,
        health=project.health,
        status_note=project.status_note,
        open_risks=open_risks,
    )


_OPEN_RISK_STATUSES = {RiskStatus.open, RiskStatus.mitigating}


def open_project_risk_counts(risk_items: list[RiskItem]) -> dict[int, int]:
    """Count open/mitigating project-scoped register risks, keyed by project id."""
    counts: dict[int, int] = {}
    for r in risk_items:
        if r.scope_level == RiskScope.project and r.status in _OPEN_RISK_STATUSES:
            counts[r.scope_id] = counts.get(r.scope_id, 0) + 1
    return counts


@router.get("/portfolio", response_model=PortfolioResponse)
async def portfolio(session: SessionDep, _: CurrentUser) -> PortfolioResponse:
    projects = (await session.execute(select(Project).order_by(Project.name))).scalars().all()

    # Bulk-load the inputs risk scoring needs once, then group in Python (avoids N+1).
    all_allocations = (await session.execute(select(Allocation))).scalars().all()
    all_adrs = (await session.execute(select(ArchitectureDecision))).scalars().all()
    engineer_names = {
        e.id: e.name
        for e in (await session.execute(select(Engineer))).scalars().all()
        if e.id is not None
    }
    allocs_by_project: dict[int, list[Allocation]] = {}
    for a in all_allocations:
        if a.project_id is not None:
            allocs_by_project.setdefault(a.project_id, []).append(a)
    adrs_by_project: dict[int, list[ArchitectureDecision]] = {}
    for adr in all_adrs:
        adrs_by_project.setdefault(adr.project_id, []).append(adr)
    all_drift = (await session.execute(select(DriftEvent))).scalars().all()
    drift_by_project: dict[int, list[DriftEvent]] = {}
    for ev in all_drift:
        drift_by_project.setdefault(ev.project_id, []).append(ev)
    all_activity = (await session.execute(select(ActivityEvent))).scalars().all()
    activity_by_project: dict[int, list[ActivityEvent]] = {}
    for ae in all_activity:
        activity_by_project.setdefault(ae.project_id, []).append(ae)
    open_risks_by_project = open_project_risk_counts(
        list((await session.execute(select(RiskItem))).scalars().all())
    )
    availability = [
        AvailabilitySpan(a.engineer_id, a.capacity_factor, a.start_date, a.end_date)
        for a in (await session.execute(select(EngineerAvailability))).scalars().all()
    ]
    today = date.today()

    summaries: list[ProjectSummary] = []
    for project in projects:
        assert project.id is not None
        tasks = list(
            (
                await session.execute(select(Task).where(Task.project_id == project.id))
            ).scalars().all()
        )
        summaries.append(
            summarize_project(
                project,
                tasks=tasks,
                allocations=allocs_by_project.get(project.id, []),
                engineer_names=engineer_names,
                adrs=adrs_by_project.get(project.id, []),
                drift_events=drift_by_project.get(project.id, []),
                activity_events=activity_by_project.get(project.id, []),
                today=today,
                availability=availability,
                open_risks=open_risks_by_project.get(project.id, 0),
            )
        )
    return PortfolioResponse(projects=summaries)


@router.get("", response_model=list[ProjectRead])
async def list_projects(session: SessionDep, _: CurrentUser) -> list[Project]:
    result = await session.execute(select(Project).order_by(Project.name))
    return list(result.scalars().all())


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def create_project(
    session: SessionDep, _: ArchitectWriter, payload: ProjectCreate
) -> Project:
    existing = await session.execute(select(Project).where(Project.key == payload.key))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Project key exists")
    data = payload.model_dump()
    data["tags"] = normalize_tags(data.get("tags") or [])
    project = Project(**data)
    session.add(project)
    await session.commit()
    await session.refresh(project)
    return project


@router.get("/{project_id}", response_model=ProjectRead)
async def get_project(session: SessionDep, _: CurrentUser, project_id: int) -> Project:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


@router.get("/{project_id}/summary", response_model=ProjectSummary)
async def project_summary(
    session: SessionDep, _: CurrentUser, project_id: int
) -> ProjectSummary:
    """One project's portfolio summary (risk + drift + progress), computed the same way as the
    portfolio rollup so the project cockpit's Overview matches the portfolio numbers exactly."""
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    assert project.id is not None
    tasks = list(
        (await session.execute(select(Task).where(Task.project_id == project.id))).scalars().all()
    )
    allocations = list(
        (
            await session.execute(select(Allocation).where(Allocation.project_id == project.id))
        ).scalars().all()
    )
    adrs = list(
        (
            await session.execute(
                select(ArchitectureDecision).where(ArchitectureDecision.project_id == project.id)
            )
        ).scalars().all()
    )
    drift_events = list(
        (
            await session.execute(select(DriftEvent).where(DriftEvent.project_id == project.id))
        ).scalars().all()
    )
    activity_events = list(
        (
            await session.execute(
                select(ActivityEvent).where(ActivityEvent.project_id == project.id)
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
    open_risks = open_project_risk_counts(
        list((await session.execute(select(RiskItem))).scalars().all())
    ).get(project.id, 0)
    return summarize_project(
        project,
        tasks=tasks,
        allocations=allocations,
        engineer_names=engineer_names,
        adrs=adrs,
        drift_events=drift_events,
        activity_events=activity_events,
        today=date.today(),
        availability=availability,
        open_risks=open_risks,
    )


@router.patch("/{project_id}", response_model=ProjectRead)
async def update_project(
    session: SessionDep, _: ArchitectWriter, project_id: int, payload: ProjectUpdate
) -> Project:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    data = payload.model_dump(exclude_unset=True)
    if "tags" in data and data["tags"] is not None:
        data["tags"] = normalize_tags(data["tags"])
    for field, value in data.items():
        setattr(project, field, value)
    if "health" in data or "status_note" in data:
        project.status_updated_at = utcnow()
    await session.commit()
    await session.refresh(project)
    return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(session: SessionDep, _: ArchitectWriter, project_id: int) -> None:
    # Clear the project's whole object graph (tasks, schedule, decisions, architecture,
    # governance, drafts, referencing scenario rows) in FK-safe order first — a bare delete
    # 500s on Postgres/MySQL for any non-empty project.
    await delete_project_cascade(session, project_id)
    await session.commit()


# --- Scheduling calendar: holidays ---
@router.get("/{project_id}/holidays", response_model=list[HolidayRead])
async def list_holidays(session: SessionDep, _: CurrentUser, project_id: int) -> list[Holiday]:
    result = await session.execute(select(Holiday).where(Holiday.project_id == project_id))
    return list(result.scalars().all())


@router.post(
    "/{project_id}/holidays", response_model=HolidayRead, status_code=status.HTTP_201_CREATED
)
async def create_holiday(
    session: SessionDep, _: ArchitectWriter, project_id: int, payload: HolidayCreate
) -> Holiday:
    holiday = Holiday(project_id=project_id, day=payload.day, name=payload.name)
    session.add(holiday)
    await session.commit()
    await session.refresh(holiday)
    return holiday


@router.delete("/{project_id}/holidays/{holiday_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_holiday(
    session: SessionDep, _: ArchitectWriter, project_id: int, holiday_id: int
) -> None:
    holiday = await session.get(Holiday, holiday_id)
    if holiday is not None:
        await session.delete(holiday)
        await session.commit()
