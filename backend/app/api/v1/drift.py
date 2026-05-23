"""Architecture drift: the queue, the scan that populates it, and reconciliation.

Detection itself is pure (app/services/drift.py). The scan loads the *declared*
architecture from the DB and combines it with *observed* signals supplied by the caller
(the Drift Sentinel subagent reads code and posts what it found), then upserts drift
events. Reconciling an event closes the loop: accept -> auto-propose an ADR, reject ->
open a revert task, false-positive -> learn a per-project suppression.
"""

from fastapi import APIRouter, HTTPException, status
from sqlmodel import col, select

from app.api.deps import ArchitectWriter, CurrentUser, SessionDep
from app.api.v1.architecture import _next_number, _set_component_links
from app.models.architecture import (
    ADRComponentLink,
    ArchitectureComponent,
    ArchitectureDecision,
    ComponentLink,
    DriftEvent,
    DriftSuppression,
)
from app.models.base import ADRStatus, TaskType
from app.models.project import Project, Task
from app.schemas.entities import (
    DriftEventRead,
    DriftReconcileRequest,
    DriftReconcileResponse,
    DriftResponse,
    DriftScanRequest,
)
from app.services.drift import (
    DriftInputs,
    ImplicitSignal,
    level,
    run_detection,
    score_kinds,
)

router = APIRouter()


def drift_score_from_events(events: list[DriftEvent]) -> int:
    """Score derived from the currently *open* drift events (so the queue and the score
    always agree). Shared with the portfolio rollup."""
    return score_kinds([e.kind for e in events if e.status == "open"])


async def _project_or_404(session: SessionDep, project_id: int) -> Project:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


async def _declared_inputs(session: SessionDep, project_id: int) -> DriftInputs:
    components = list(
        (
            await session.execute(
                select(ArchitectureComponent).where(
                    ArchitectureComponent.project_id == project_id
                )
            )
        ).scalars().all()
    )
    names = {c.id: c.name for c in components if c.id is not None}
    component_ids = set(names)

    links = (await session.execute(select(ComponentLink))).scalars().all()
    declared = {
        (link.source_id, link.target_id)
        for link in links
        if link.source_id in component_ids and link.target_id in component_ids
    }

    accepted = list(
        (
            await session.execute(
                select(ArchitectureDecision).where(
                    ArchitectureDecision.project_id == project_id,
                    ArchitectureDecision.status == ADRStatus.accepted,
                )
            )
        ).scalars().all()
    )
    adr_components: dict[int, list[int]] = {}
    if accepted:
        adr_ids = [a.id for a in accepted if a.id is not None]
        for row in (
            await session.execute(
                select(ADRComponentLink).where(col(ADRComponentLink.adr_id).in_(adr_ids))
            )
        ).scalars().all():
            adr_components.setdefault(row.adr_id, []).append(row.component_id)
    accepted_adrs = [
        (a.number, a.title, adr_components.get(a.id, [])) for a in accepted if a.id is not None
    ]
    return DriftInputs(
        component_names=names, declared_edges=declared, accepted_adrs=accepted_adrs
    )


async def _events(session: SessionDep, project_id: int) -> list[DriftEvent]:
    rows = await session.execute(
        select(DriftEvent).where(DriftEvent.project_id == project_id).order_by(col(DriftEvent.id))
    )
    return list(rows.scalars().all())


def _response(project_id: int, events: list[DriftEvent]) -> DriftResponse:
    score = drift_score_from_events(events)
    # Open events first, then most recent.
    ordered = sorted(events, key=lambda e: (e.status != "open", -(e.id or 0)))
    return DriftResponse(
        project_id=project_id,
        score=score,
        level=level(score),
        events=[DriftEventRead.model_validate(e) for e in ordered],
    )


@router.get("/projects/{project_id}/drift", response_model=DriftResponse)
async def get_drift(session: SessionDep, _: CurrentUser, project_id: int) -> DriftResponse:
    await _project_or_404(session, project_id)
    return _response(project_id, await _events(session, project_id))


@router.post("/projects/{project_id}/drift/scan", response_model=DriftResponse)
async def scan_drift(
    session: SessionDep, _: ArchitectWriter, project_id: int, payload: DriftScanRequest
) -> DriftResponse:
    await _project_or_404(session, project_id)
    inputs = await _declared_inputs(session, project_id)
    inputs.actual_edges = {(s, t) for s, t in payload.actual_edges}
    inputs.inactive_component_ids = set(payload.inactive_component_ids)
    inputs.implicit_signals = [
        ImplicitSignal(
            kind=s.kind,
            summary=s.summary,
            suspected_cause=s.suspected_cause,
            component_id=s.component_id,
        )
        for s in payload.implicit_signals
    ]
    suppressed = {
        row.rule_key
        for row in (
            await session.execute(
                select(DriftSuppression).where(DriftSuppression.project_id == project_id)
            )
        ).scalars().all()
    }

    report = run_detection(inputs, suppressed)
    existing = {e.rule_key: e for e in await _events(session, project_id)}
    found_keys: set[str] = set()
    for f in report.findings:
        found_keys.add(f.rule_key)
        event = existing.get(f.rule_key)
        if event is None:
            session.add(
                DriftEvent(
                    project_id=project_id,
                    kind=f.kind,
                    rule_key=f.rule_key,
                    summary=f.summary,
                    detail=f.detail,
                    suspected_cause=f.suspected_cause,
                    affected_component_ids=f.affected_component_ids,
                    status="open",
                )
            )
        else:  # refresh wording; preserve triage status
            event.kind = f.kind
            event.summary = f.summary
            event.detail = f.detail
            event.suspected_cause = f.suspected_cause
            event.affected_component_ids = f.affected_component_ids
    # An open event whose drift is no longer detected has resolved itself — drop it.
    for key, event in existing.items():
        if key not in found_keys and event.status == "open":
            await session.delete(event)
    await session.commit()
    return _response(project_id, await _events(session, project_id))


@router.post(
    "/projects/{project_id}/drift/{event_id}/reconcile", response_model=DriftReconcileResponse
)
async def reconcile_drift(
    session: SessionDep,
    _: ArchitectWriter,
    project_id: int,
    event_id: int,
    payload: DriftReconcileRequest,
) -> DriftReconcileResponse:
    event = await session.get(DriftEvent, event_id)
    if event is None or event.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Drift event not found")

    created_adr_id: int | None = None
    created_task_id: int | None = None

    if payload.action == "accepted":
        adr = ArchitectureDecision(
            project_id=project_id,
            number=await _next_number(session, project_id),
            title=event.summary[:200],
            context=event.detail,
            status=ADRStatus.proposed,
        )
        session.add(adr)
        await session.flush()
        assert adr.id is not None
        await _set_component_links(session, adr.id, event.affected_component_ids)
        created_adr_id = adr.id
        event.status = "accepted"
    elif payload.action == "rejected":
        task = Task(
            project_id=project_id,
            name=f"Revert drift: {event.summary}"[:200],
            type=TaskType.task,
        )
        session.add(task)
        await session.flush()
        created_task_id = task.id
        event.status = "rejected"
    elif payload.action == "false_positive":
        session.add(DriftSuppression(project_id=project_id, rule_key=event.rule_key))
        event.status = "false_positive"
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="action must be accepted | rejected | false_positive",
        )

    await session.commit()
    await session.refresh(event)
    return DriftReconcileResponse(
        event=DriftEventRead.model_validate(event),
        created_adr_id=created_adr_id,
        created_task_id=created_task_id,
    )
