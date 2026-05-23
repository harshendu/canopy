"""Risk dashboard: a leading-indicator risk score + drillable breakdown, plus a
mitigation log. The ORM→signals adapter (`report_for`) is shared with the portfolio
rollup so a project's card and its Risk tab agree."""

from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, status
from sqlmodel import select

from app.api.deps import CurrentUser, PlannerWriter, SessionDep
from app.models.architecture import ArchitectureDecision
from app.models.base import ADRStatus, TaskType
from app.models.project import Project, RiskMitigation, Task
from app.models.team import Allocation
from app.schemas.entities import (
    RiskFamilyRead,
    RiskIndicatorRead,
    RiskMitigationCreate,
    RiskMitigationRead,
    RiskMitigationUpdate,
    RiskResponse,
)
from app.services.capacity import AllocationSpan, weekly_capacity
from app.services.risk import RiskReport, RiskSignals, compute_risk

router = APIRouter()

STUCK_AFTER_DAYS = 14


def report_for(
    *,
    tasks: list[Task],
    allocations: list[Allocation],
    engineer_names: dict[int, str],
    adrs: list[ArchitectureDecision],
    project_start: date | None,
    project_target: date | None,
    today: date,
) -> RiskReport:
    """Adapt loaded ORM rows into pure RiskSignals and score them."""
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
    critical = [t for t in leaves if t.is_critical]

    over_allocations: list[tuple[str, str, float]] = []
    if allocations:
        starts = [a.start_date for a in allocations if a.start_date]
        ends = [a.end_date for a in allocations if a.end_date]
        win_start = project_start or (min(starts) if starts else today)
        win_end = project_target or (max(ends) if ends else win_start + timedelta(weeks=8))
        if win_end < win_start:
            win_end = win_start
        grid = weekly_capacity(
            [
                AllocationSpan(a.engineer_id, a.percent_allocation, a.start_date, a.end_date)
                for a in allocations
            ],
            win_start,
            win_end,
        )
        for eng_id, by_week in grid.items():
            for week, pct in by_week.items():
                if pct > 100:
                    over_allocations.append(
                        (engineer_names.get(eng_id, f"#{eng_id}"), week.isoformat(), pct)
                    )

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
            over_allocations=over_allocations,
            deferred_overdue=deferred_overdue,
            stuck_decisions=stuck,
        )
    )


async def _mitigations(session: SessionDep, project_id: int) -> list[RiskMitigation]:
    rows = await session.execute(
        select(RiskMitigation).where(RiskMitigation.project_id == project_id)
    )
    return list(rows.scalars().all())


@router.get("/projects/{project_id}/risk", response_model=RiskResponse)
async def project_risk(session: SessionDep, _: CurrentUser, project_id: int) -> RiskResponse:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    tasks = list(
        (await session.execute(select(Task).where(Task.project_id == project_id))).scalars().all()
    )
    allocations = list(
        (
            await session.execute(select(Allocation).where(Allocation.project_id == project_id))
        ).scalars().all()
    )
    from app.models.team import Engineer  # local import avoids an unused top-level dep

    engineer_names = {
        e.id: e.name
        for e in (await session.execute(select(Engineer))).scalars().all()
        if e.id is not None
    }
    adrs = list(
        (
            await session.execute(
                select(ArchitectureDecision).where(
                    ArchitectureDecision.project_id == project_id
                )
            )
        ).scalars().all()
    )

    report = report_for(
        tasks=tasks,
        allocations=allocations,
        engineer_names=engineer_names,
        adrs=adrs,
        project_start=project.start_date,
        project_target=project.target_date,
        today=date.today(),
    )
    mitigations = await _mitigations(session, project_id)
    return RiskResponse(
        project_id=project_id,
        score=report.score,
        level=report.level,
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
