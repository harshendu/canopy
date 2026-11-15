"""Gates — the human side of agent work (docs/AGENT_EXECUTION.md §9.4, §13; gate `ai.work_queue`).

The Reviews inbox reads these; a person decides here. Deciding and reassigning are human-only
(an agent token gets 403 `human_only`); the asking session may withdraw its own question.
"""

from __future__ import annotations

import asyncio
import time
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlmodel import col, select

from app.api.deps import CurrentUser, HumanOnly, SessionDep
from app.api.v1.work import CallerDep, gate_read, http
from app.models.base import ArtifactKind, GateStatus
from app.models.gate import Gate
from app.models.project import Project, Task
from app.models.work import TaskArtifact, WorkEvent
from app.schemas.entities import TaskRead
from app.schemas.work import (
    ArtifactRead,
    GateDecideRequest,
    GateDetail,
    GateRead,
    GateReassignRequest,
    WorkEventRead,
)
from app.services import gates as gate_service
from app.services import work_service
from app.services.access import project_can_edit
from app.services.work_service import WorkError

router = APIRouter()

TRAIL_LIMIT = 60


async def _gate(session: SessionDep, gate_id: int) -> Gate:
    gate = await session.get(Gate, gate_id)
    if gate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gate not found")
    return gate


async def _is_planner(session: SessionDep, user: CurrentUser, gate: Gate) -> bool:
    project = await session.get(Project, gate.project_id)
    return project is not None and await project_can_edit(session, user, project)


@router.get("/gates", response_model=list[GateRead])
async def list_gates(
    session: SessionDep,
    caller: CallerDep,
    status_: Annotated[str | None, Query(alias="status")] = None,
    mine: bool = False,
    project_id: int | None = None,
    task_id: int | None = None,
    kind: str | None = None,
    limit: int = 200,
) -> list[GateRead]:
    """The inbox. `status` defaults to `open` (`all` for every gate); `mine=true` keeps the
    gates the caller may decide (for an agent token: those its issuing person may decide)."""
    if mine:
        rows = await gate_service.gates_for(
            session, caller.user, open_only=(status_ or "open") == "open"
        )
    else:
        stmt = select(Gate)
        wanted = status_ or "open"
        if wanted != "all":
            stmt = stmt.where(Gate.status == wanted)
        rows = list((await session.execute(stmt.order_by(col(Gate.created_at)))).scalars().all())
    if project_id is not None:
        rows = [g for g in rows if g.project_id == project_id]
    if task_id is not None:
        rows = [g for g in rows if g.task_id == task_id]
    if kind:
        rows = [g for g in rows if g.kind == kind]
    return [await gate_read(session, g, caller) for g in rows[: max(1, min(limit, 500))]]


@router.get("/gates/{gate_id}", response_model=GateDetail)
async def get_gate(session: SessionDep, caller: CallerDep, gate_id: int) -> GateDetail:
    """One gate with what a person needs to decide it: the evidence snapshot, the subject
    artifact and the revision before it, the latest hand-off and reviews, and the trail."""
    gate = await _gate(session, gate_id)
    task = await session.get(Task, gate.task_id)
    if task is None or task.id is None:
        raise HTTPException(status_code=404, detail="Task not found")
    subject = (
        await session.get(TaskArtifact, gate.subject_artifact_id)
        if gate.subject_artifact_id else None
    )
    previous = None
    if subject is not None and subject.revision > 1:
        previous = (await session.execute(
            select(TaskArtifact).where(
                TaskArtifact.task_id == task.id, TaskArtifact.kind == subject.kind,
                TaskArtifact.revision == subject.revision - 1,
            )
        )).scalars().first()
    handoff = await work_service.latest_artifact(session, task.id, ArtifactKind.handoff)
    reviews = [
        a for a in (
            await work_service.latest_artifact(session, task.id, ArtifactKind.review),
            await work_service.latest_artifact(session, task.id, ArtifactKind.qa_report),
        ) if a is not None
    ]
    trail = list((await session.execute(
        select(WorkEvent).where(WorkEvent.task_id == task.id)
        .order_by(col(WorkEvent.at).desc(), col(WorkEvent.id).desc()).limit(TRAIL_LIMIT)
    )).scalars().all())
    trail.reverse()
    return GateDetail(
        gate=await gate_read(session, gate, caller),
        task=TaskRead.model_validate(task),
        subject=ArtifactRead.model_validate(subject) if subject is not None else None,
        previous=ArtifactRead.model_validate(previous) if previous is not None else None,
        handoff=ArtifactRead.model_validate(handoff) if handoff is not None else None,
        reviews=[ArtifactRead.model_validate(r) for r in reviews],
        trail=[WorkEventRead.model_validate(e) for e in trail],
    )


@router.post("/gates/{gate_id}/decide", response_model=GateRead)
async def decide_gate(
    session: SessionDep, caller: CallerDep, _human: HumanOnly, gate_id: int,
    payload: GateDecideRequest,
) -> GateRead:
    """Respond to a gate (human-only). The decision routes the task; nothing is ever approved
    by a timeout. `subject_revision` must name the revision you reviewed (`409 stale_subject`)."""
    gate = await _gate(session, gate_id)
    try:
        await gate_service.decide(
            session, gate, caller, decision=payload.decision, note=payload.note,
            option=payload.option, plan=payload.plan, subject_revision=payload.subject_revision,
        )
    except WorkError as exc:
        await session.rollback()
        raise http(exc) from exc
    await session.commit()
    await session.refresh(gate)
    await work_service.notify(gate.project_id, gate.task_id, gate_id=gate.id,
                              decision=gate.decision)
    return await gate_read(session, gate, caller)


@router.post("/gates/{gate_id}/reassign", response_model=GateRead)
async def reassign_gate(
    session: SessionDep, caller: CallerDep, _human: HumanOnly, gate_id: int,
    payload: GateReassignRequest,
) -> GateRead:
    """Hand the decision to named engineers (planners who may edit the project; human-only)."""
    gate = await _gate(session, gate_id)
    if not await _is_planner(session, caller.user, gate):
        raise HTTPException(status_code=403, detail={
            "code": "not_permitted", "message": "Only the project's planners can reassign"})
    try:
        await gate_service.reassign(session, gate, caller, payload.approver_engineer_ids)
    except WorkError as exc:
        await session.rollback()
        raise http(exc) from exc
    await session.commit()
    await session.refresh(gate)
    await work_service.notify(gate.project_id, gate.task_id, gate_id=gate.id)
    return await gate_read(session, gate, caller)


@router.post("/gates/{gate_id}/cancel", response_model=GateRead)
async def cancel_gate(session: SessionDep, caller: CallerDep, gate_id: int) -> GateRead:
    """Withdraw an open gate: whoever asked (their own agent session included), or a planner."""
    gate = await _gate(session, gate_id)
    as_planner = not caller.is_agent and await _is_planner(session, caller.user, gate)
    try:
        await gate_service.cancel(session, gate, caller, as_planner=as_planner)
    except WorkError as exc:
        await session.rollback()
        raise http(exc) from exc
    await session.commit()
    await session.refresh(gate)
    await work_service.notify(gate.project_id, gate.task_id, gate_id=gate.id)
    return await gate_read(session, gate, caller)


@router.get("/gates/{gate_id}/wait", response_model=GateRead)
async def wait_for_gate(
    session: SessionDep, caller: CallerDep, gate_id: int, timeout_s: int = 25
) -> GateRead:
    """Long-poll until the gate is no longer open, or `timeout_s` (≤ 25) passes."""
    deadline = time.monotonic() + max(0, min(timeout_s, 25))
    gate = await _gate(session, gate_id)
    while gate.status == GateStatus.open.value and time.monotonic() < deadline:
        await asyncio.sleep(min(1.0, max(0.0, deadline - time.monotonic())))
        # End the read transaction so the next read sees other requests' commits (MySQL's
        # REPEATABLE READ would otherwise keep showing the first snapshot).
        await session.rollback()
        gate = await _gate(session, gate_id)
    return await gate_read(session, gate, caller)
