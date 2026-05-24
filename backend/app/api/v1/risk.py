"""Risk dashboard: a leading-indicator risk score + drillable breakdown, plus a
mitigation log. The ORM→signals adapter (`report_for`) is shared with the portfolio
rollup so a project's card and its Risk tab agree."""

from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.api.deps import CurrentUser, PlannerWriter, SessionDep
from app.models.activity import ActivityEvent
from app.models.architecture import ArchitectureDecision
from app.models.base import ActivityKind, ADRStatus, TaskType
from app.models.project import Project, RiskMitigation, RiskSnapshot, Task
from app.models.team import Allocation
from app.schemas.entities import (
    RiskFamilyRead,
    RiskIndicatorRead,
    RiskMitigationCreate,
    RiskMitigationRead,
    RiskMitigationUpdate,
    RiskResponse,
    RiskSnapshotRead,
)
from app.services.capacity import AllocationSpan, AvailabilitySpan, over_allocated_weeks
from app.services.metadata import is_high_uncertainty
from app.services.risk import RiskReport, RiskSignals, compute_risk

router = APIRouter()

STUCK_AFTER_DAYS = 14


def _quality_signals(events: list[ActivityEvent]) -> tuple[bool, int, int]:
    """(quality_available, build_failures, net_open_incidents) from activity events."""
    build_failures = sum(1 for e in events if e.kind == ActivityKind.build_failure)
    opened = sum(1 for e in events if e.kind == ActivityKind.incident_open)
    closed = sum(1 for e in events if e.kind == ActivityKind.incident_close)
    return bool(events), build_failures, max(0, opened - closed)


def report_for(
    *,
    tasks: list[Task],
    allocations: list[Allocation],
    engineer_names: dict[int, str],
    adrs: list[ArchitectureDecision],
    project_start: date | None,
    project_target: date | None,
    today: date,
    drift_score: int = 0,
    activity_events: list[ActivityEvent] | None = None,
    availability: list[AvailabilitySpan] | None = None,
) -> RiskReport:
    """Adapt loaded ORM rows into pure RiskSignals and score them."""
    quality_available, build_failures, open_incidents = _quality_signals(activity_events or [])
    leaves = [t for t in tasks if t.type != TaskType.summary and t.id is not None]
    deadline_violations = [
        (t.id, t.name)
        for t in leaves
        if t.id is not None and t.deadline and t.end and t.end > t.deadline
    ]
    drifted = [
        (t.id, t.name)
        for t in leaves
        if t.id is not None and t.baseline_end is not None and t.end != t.baseline_end
    ]
    high_uncertainty = [
        (t.id, t.name)
        for t in leaves
        if t.id is not None
        and t.estimate_optimistic is not None
        and t.estimate_likely is not None
        and t.estimate_pessimistic is not None
        and is_high_uncertainty(
            t.estimate_optimistic, t.estimate_likely, t.estimate_pessimistic
        )
    ]
    critical = [t for t in leaves if t.is_critical]

    over_allocations: list[tuple[str, str, float]] = []
    if allocations:
        starts = [a.start_date for a in allocations if a.start_date]
        ends = [a.end_date for a in allocations if a.end_date]
        win_start = project_start or (min(starts) if starts else today)
        win_end = project_target or (max(ends) if ends else win_start + timedelta(weeks=8))
        if win_end < win_start:
            win_end = win_start
        over_allocations = [
            (engineer_names.get(o.engineer_id, f"#{o.engineer_id}"), o.week.isoformat(), o.percent)
            for o in over_allocated_weeks(
                [
                    AllocationSpan(a.engineer_id, a.percent_allocation, a.start_date, a.end_date)
                    for a in allocations
                ],
                availability or [],
                win_start,
                win_end,
            )
        ]

    deferred_overdue = [
        (a.number, a.title)
        for a in adrs
        if a.status == ADRStatus.deferred and (a.decide_by is None or a.decide_by < today)
    ]
    stuck = [
        (a.number, a.title)
        for a in adrs
        if a.status == ADRStatus.under_discussion
        and (today - a.created_at.date()).days > STUCK_AFTER_DAYS
    ]

    return compute_risk(
        RiskSignals(
            deadline_violations=deadline_violations,
            drifted_tasks=drifted,
            critical_task_count=len(critical),
            critical_zero_float_count=sum(1 for t in critical if t.total_float == 0),
            high_uncertainty_tasks=high_uncertainty,
            over_allocations=over_allocations,
            deferred_overdue=deferred_overdue,
            stuck_decisions=stuck,
            drift_score=drift_score,
            quality_available=quality_available,
            build_failures=build_failures,
            open_incidents=open_incidents,
        )
    )


async def run_risk_snapshots(session: AsyncSession) -> int:
    """Capture a risk snapshot for every project — the worker's nightly sweep, so the risk
    timeline (§Q2) is a real trend instead of only-on-demand points. Returns the count."""
    projects = (await session.execute(select(Project))).scalars().all()
    count = 0
    for project in projects:
        if project.id is None:
            continue
        report = await _compute_report(session, project)
        session.add(RiskSnapshot(project_id=project.id, score=report.score, level=report.level))
        count += 1
    await session.commit()
    return count


async def _mitigations(session: SessionDep, project_id: int) -> list[RiskMitigation]:
    rows = await session.execute(
        select(RiskMitigation).where(RiskMitigation.project_id == project_id)
    )
    return list(rows.scalars().all())


async def _compute_report(session: SessionDep, project: Project) -> RiskReport:
    """Load everything risk scoring needs for one project and score it."""
    from app.api.v1.drift import drift_score_from_events
    from app.models.architecture import DriftEvent
    from app.models.team import Engineer, EngineerAvailability

    project_id = project.id
    tasks = list(
        (await session.execute(select(Task).where(Task.project_id == project_id))).scalars().all()
    )
    allocations = list(
        (
            await session.execute(select(Allocation).where(Allocation.project_id == project_id))
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
    adrs = list(
        (
            await session.execute(
                select(ArchitectureDecision).where(ArchitectureDecision.project_id == project_id)
            )
        ).scalars().all()
    )
    drift_events = list(
        (
            await session.execute(select(DriftEvent).where(DriftEvent.project_id == project_id))
        ).scalars().all()
    )
    activity_events = list(
        (
            await session.execute(
                select(ActivityEvent).where(ActivityEvent.project_id == project_id)
            )
        ).scalars().all()
    )
    return report_for(
        tasks=tasks,
        allocations=allocations,
        engineer_names=engineer_names,
        adrs=adrs,
        project_start=project.start_date,
        project_target=project.target_date,
        today=date.today(),
        drift_score=drift_score_from_events(drift_events),
        activity_events=activity_events,
        availability=availability,
    )


@router.get("/projects/{project_id}/risk", response_model=RiskResponse)
async def project_risk(session: SessionDep, _: CurrentUser, project_id: int) -> RiskResponse:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    report = await _compute_report(session, project)
    mitigations = await _mitigations(session, project_id)
    return RiskResponse(
        project_id=project_id,
        score=report.score,
        level=report.level,
        confidence=report.confidence,
        confidence_note=report.confidence_note,
        families=[
            RiskFamilyRead(
                key=f.key,
                label=f.label,
                available=f.available,
                score=f.score,
                weight=f.weight,
                indicators=[
                    RiskIndicatorRead(
                        key=i.key,
                        label=i.label,
                        score=i.score,
                        summary=i.summary,
                        details=i.details,
                    )
                    for i in f.indicators
                ],
            )
            for f in report.families
        ],
        mitigations=[RiskMitigationRead.model_validate(m) for m in mitigations],
    )


@router.get("/projects/{project_id}/risk/timeline", response_model=list[RiskSnapshotRead])
async def risk_timeline(
    session: SessionDep, _: CurrentUser, project_id: int, limit: int = 12
) -> list[RiskSnapshot]:
    """The last `limit` risk snapshots, oldest→newest, for the trend sparkline (§Q2)."""
    rows = await session.execute(
        select(RiskSnapshot)
        .where(RiskSnapshot.project_id == project_id)
        .order_by(col(RiskSnapshot.id).desc())
        .limit(limit)
    )
    snapshots = list(rows.scalars().all())
    snapshots.reverse()
    return snapshots


@router.post(
    "/projects/{project_id}/risk/snapshot",
    response_model=RiskSnapshotRead,
    status_code=status.HTTP_201_CREATED,
)
async def capture_risk_snapshot(
    session: SessionDep, _: PlannerWriter, project_id: int
) -> RiskSnapshot:
    """Capture the current risk score for the timeline (run on demand / nightly)."""
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    report = await _compute_report(session, project)
    snapshot = RiskSnapshot(project_id=project_id, score=report.score, level=report.level)
    session.add(snapshot)
    await session.commit()
    await session.refresh(snapshot)
    return snapshot


@router.post(
    "/projects/{project_id}/risk/mitigations",
    response_model=RiskMitigationRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_mitigation(
    session: SessionDep, _: PlannerWriter, project_id: int, payload: RiskMitigationCreate
) -> RiskMitigation:
    mitigation = RiskMitigation(project_id=project_id, **payload.model_dump())
    session.add(mitigation)
    await session.commit()
    await session.refresh(mitigation)
    return mitigation


@router.patch(
    "/projects/{project_id}/risk/mitigations/{mitigation_id}",
    response_model=RiskMitigationRead,
)
async def update_mitigation(
    session: SessionDep,
    _: PlannerWriter,
    project_id: int,
    mitigation_id: int,
    payload: RiskMitigationUpdate,
) -> RiskMitigation:
    mitigation = await session.get(RiskMitigation, mitigation_id)
    if mitigation is None or mitigation.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mitigation not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(mitigation, field, value)
    await session.commit()
    await session.refresh(mitigation)
    return mitigation


@router.delete(
    "/projects/{project_id}/risk/mitigations/{mitigation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_mitigation(
    session: SessionDep, _: PlannerWriter, project_id: int, mitigation_id: int
) -> None:
    mitigation = await session.get(RiskMitigation, mitigation_id)
    if mitigation is not None and mitigation.project_id == project_id:
        await session.delete(mitigation)
        await session.commit()
