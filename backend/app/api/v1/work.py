"""The agent work queue — docs/AGENT_EXECUTION.md §6 to §8 and §13 (gate `ai.work_queue`).

Sessions claim delegated work, read its brief, record a plan, hand off, ask a person, or give the
task back. Agent tokens may do all of that (two-way doors, fenced by the claim); delegating work,
switching a project's intake and taking work back are human-only.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.exc import DBAPIError
from sqlmodel import col, select

from app.api.deps import (
    AgentTokenDep,
    ContributorWriter,
    CurrentUser,
    HumanOnly,
    PlannerWriter,
    SessionDep,
    TokenScopeDep,
)
from app.models.base import (
    ArtifactKind,
    ClaimState,
    GateKind,
    GateStatus,
    TokenScope,
    WorkEventKind,
    utcnow,
)
from app.models.gate import Gate
from app.models.project import Project, Task
from app.models.work import TaskArtifact, WorkClaim, WorkEvent
from app.schemas.entities import TaskRead
from app.schemas.work import (
    AgentsViewResponse,
    AgentsWorkingRead,
    ArtifactCreate,
    ArtifactRead,
    AskRequest,
    ClaimRead,
    ClaimRequest,
    ClaimResponse,
    ComponentsRequest,
    ComponentsResponse,
    DecisionRead,
    DelegationRequest,
    DelegationResponse,
    ExecutionResponse,
    GateRead,
    HeartbeatRequest,
    HeartbeatResponse,
    IntakeRequest,
    IntakeResponse,
    ParkedRead,
    PlanApproval,
    PlanData,
    PlanResponse,
    QueueItemRead,
    QueueResponse,
    ReleaseRequest,
    StageRead,
    SubmitRequest,
    SubmitResponse,
    WorkEventRead,
)
from app.services import policy_service, stage_policy, work_brief, work_queue, work_service
from app.services.access import ensure_project_editable, project_can_edit
from app.services.work_service import Caller, GoverningDecision, WorkError

router = APIRouter()

# How often an unnamed claim retries after losing a race at the database.
CLAIM_RETRIES = 3


async def get_caller(
    session: SessionDep, user: CurrentUser, token: AgentTokenDep, scope: TokenScopeDep
) -> Caller:
    return await work_service.caller_for(
        session, user, token, is_agent=scope == TokenScope.agent
    )


CallerDep = Annotated[Caller, Depends(get_caller)]


def http(exc: WorkError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail())


async def _task(session: SessionDep, task_id: int) -> Task:
    task = await session.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return task


async def _project(session: SessionDep, project_id: int) -> Project:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


def decision_read(d: GoverningDecision) -> DecisionRead:
    return DecisionRead(
        adr_id=d.adr_id, adr=f"ADR-{d.number:04d}", title=d.title, status=d.status,
        reversibility=d.reversibility, why=d.why, decision=d.decision, fitness=d.fitness,
    )


async def gate_read(session: SessionDep, gate: Gate, caller: Caller | None = None) -> GateRead:
    from app.models.user import User
    from app.services import gates as gate_service

    task = await session.get(Task, gate.task_id)
    project = await session.get(Project, gate.project_id)
    requester = (
        await session.get(User, gate.requested_by_user_id) if gate.requested_by_user_id else None
    )
    may = False
    if caller is not None and not caller.is_agent and gate.status == GateStatus.open.value:
        ok, _ = await gate_service.may_decide(session, gate, caller.user)
        may = ok and not (gate.exclude_requester and gate.requested_by_user_id == caller.user_id)
    read = GateRead.model_validate(gate)
    read.task_key = task.key if task is not None else None
    read.task_name = task.name if task is not None else None
    read.project_key = project.key if project is not None else None
    read.requester_name = (requester.full_name or requester.email) if requester else None
    read.age_hours = round(max(0.0, (utcnow() - gate.created_at).total_seconds()) / 3600, 1)
    read.may_decide = may
    read.waiting_for_evidence = gate.status == GateStatus.approved.value and gate.routed_at is None
    return read


async def _may_plan(session: SessionDep, caller: Caller, task: Task) -> bool:
    project = await session.get(Project, task.project_id)
    return project is not None and await project_can_edit(session, caller.user, project)


async def _ensure_planner_or_assignee(session: SessionDep, caller: Caller, task: Task) -> None:
    if await _may_plan(session, caller, task):
        return
    if caller.engineer_id is not None and task.assignee_engineer_id == caller.engineer_id:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": "not_permitted",
                "message": "Only the project's planners or the task's assignee can do this"},
    )


# --------------------------------------------------------------------------- #
# Queue + claims
# --------------------------------------------------------------------------- #


def _queue_item(item: work_service.QueueItem) -> QueueItemRead:
    assert item.task.id is not None and item.project.id is not None
    return QueueItemRead(
        task_id=item.task.id, key=item.task.key, name=item.task.name,
        project_id=item.project.id, project_key=item.project.key, status=item.task.status,
        stage=item.stage, pull=item.pull, rank=item.order[1],
    )


@router.get("/work/queue", response_model=QueueResponse)
async def get_queue(
    session: SessionDep,
    caller: CallerDep,
    role: str = "implementer",
    project_id: int | None = None,
    team_id: int | None = None,
    repo: str | None = None,
) -> QueueResponse:
    """The tasks ready for `role`, best first, and why the rest of the delegated work isn't."""
    result = await work_service.find_work(
        session, caller, role.strip().lower(), project_id=project_id, team_id=team_id, repo=repo
    )
    return QueueResponse(role=role, roles=result.roles,
                         ready=[_queue_item(i) for i in result.ready], reasons=result.reasons)


@router.post("/work/claims", response_model=ClaimResponse)
async def create_claim(
    session: SessionDep,
    caller: CallerDep,
    _writer: ContributorWriter,
    payload: ClaimRequest,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ClaimResponse:
    """Claim a named task or the next ready one; returns the claim **and the brief**. With
    nothing ready: `claim: null`, `retry_after_s` and the reasons (`wait_s` ≤ 25 long-polls)."""
    agent = payload.agent
    info = work_service.AgentInfo(
        label=agent.label if agent else None,
        runner=agent.runner if agent else None,
        session_ref=agent.session_ref if agent else None,
    )
    deadline = time.monotonic() + payload.wait_s
    claim: WorkClaim | None = None
    contended = 0
    while True:
        try:
            claim = await work_service.claim_work(
                session, caller, payload.role, task_id=payload.task_id,
                project_id=payload.project_id, team_id=payload.team_id, repo=payload.repo,
                agent=info, idempotency_key=idempotency_key,
            )
            await session.commit()
        except WorkError as exc:
            await session.rollback()
            raise http(exc) from exc
        except DBAPIError as exc:
            # Lost a race at the database (a lock timeout or a deadlock the database broke):
            # nothing was kept. A named task is someone else's; otherwise try again.
            await session.rollback()
            contended += 1
            if payload.task_id is not None or contended > CLAIM_RETRIES:
                raise HTTPException(status_code=409, detail={
                    "code": "already_claimed", "retryable": True,
                    "message": "Another session claimed this work at the same moment",
                }) from exc
            await asyncio.sleep(0.05 * contended)
            continue
        remaining = deadline - time.monotonic()
        if claim is not None or payload.task_id is not None or remaining <= 0:
            break
        await asyncio.sleep(min(2.0, remaining))
    if claim is None:
        queue = await work_service.find_work(
            session, caller, payload.role.strip().lower(), project_id=payload.project_id,
            team_id=payload.team_id, repo=payload.repo,
        )
        return ClaimResponse(claim=None, retry_after_s=30, reasons=queue.reasons)
    task = await _task(session, claim.task_id)
    await work_service.notify(task.project_id, task.id, claim_id=claim.id)
    brief = await work_brief.build_brief(session, task, claim=claim)
    return ClaimResponse(claim=ClaimRead.model_validate(claim), brief=brief)


@router.get("/work/claims", response_model=list[ClaimRead])
async def list_claims(
    session: SessionDep,
    caller: CallerDep,
    task_id: int | None = None,
    state: str | None = None,
    project_id: int | None = None,
    mine: bool = False,
) -> list[WorkClaim]:
    """Read claims. `mine=true&state=active` is the claim the calling token holds."""
    stmt = select(WorkClaim)
    if task_id is not None:
        stmt = stmt.where(WorkClaim.task_id == task_id)
    if state is not None:
        stmt = stmt.where(WorkClaim.state == state)
    if project_id is not None:
        ids = select(col(Task.id)).where(col(Task.project_id) == project_id)
        stmt = stmt.where(col(WorkClaim.task_id).in_(ids))
    if mine:
        stmt = stmt.where(WorkClaim.user_id == caller.user_id)
        stmt = stmt.where(
            WorkClaim.agent_token_id == caller.token_id
            if caller.token_id is not None
            else col(WorkClaim.agent_token_id).is_(None)
        )
    return list((await session.execute(stmt.order_by(col(WorkClaim.id).desc()))).scalars().all())


@router.get("/work/claims/{claim_id}", response_model=ClaimRead)
async def get_claim(session: SessionDep, _: CurrentUser, claim_id: int) -> WorkClaim:
    try:
        return await work_service.get_claim(session, claim_id)
    except WorkError as exc:
        raise http(exc) from exc


@router.post("/work/claims/{claim_id}/heartbeat", response_model=HeartbeatResponse)
async def heartbeat(
    session: SessionDep, caller: CallerDep, claim_id: int, payload: HeartbeatRequest
) -> HeartbeatResponse:
    """Renew the lease; returns `continue`, or `stop` with the reason (taken over, undelegated,
    intake off, cancelled, claim no longer active)."""
    try:
        claim = await work_service.get_claim(session, claim_id)
        directive = await work_service.heartbeat(
            session, claim, caller, note=payload.note,
            steps=[s.model_dump() for s in payload.steps] if payload.steps is not None else None,
        )
    except WorkError as exc:
        raise http(exc) from exc
    if directive.directive == "continue":
        if payload.branch:
            claim.branch = payload.branch
        if payload.pr_url:
            claim.pr_url = payload.pr_url
    await session.commit()
    return HeartbeatResponse(
        directive="stop" if directive.directive == "stop" else "continue",
        reason=directive.reason,
        lease_expires_at=directive.lease_expires_at,
        heartbeat_interval_s=directive.heartbeat_interval_s,
    )


@router.post("/work/claims/{claim_id}/artifacts", response_model=PlanResponse)
async def add_claim_artifact(
    session: SessionDep, caller: CallerDep, claim_id: int, payload: ArtifactCreate
) -> PlanResponse:
    """Add a `plan` (answers with the decisions that govern the paths it touches and whether a
    person must approve it) or a `note` under a claim."""
    try:
        claim = await work_service.get_claim(session, claim_id)
        if payload.kind == "plan":
            data = PlanData.model_validate(payload.data).model_dump()
            result = await work_service.submit_plan(
                session, claim, caller, body=payload.body or data["approach"], data=data,
                title=payload.title,
            )
            await session.commit()
            plan_task = await _task(session, claim.task_id)
            await work_service.notify(plan_task.project_id, claim.task_id,
                                      gate_id=result.gate.id if result.gate else None)
            return PlanResponse(
                artifact=ArtifactRead.model_validate(result.artifact),
                governing_decisions=[decision_read(d) for d in result.binding],
                fitness_rules=[
                    {**rule, "adr": f"ADR-{d.number:04d}"}
                    for d in result.binding for rule in d.fitness
                ],
                unsettled=[decision_read(d) for d in result.unsettled],
                approval=PlanApproval(
                    required=result.approval_required, reasons=result.reasons,
                    gate_id=result.gate.id if result.gate is not None else None,
                ),
            )
        work_service.ensure_holder(claim, caller)
        await work_service.renew(session, claim)
        task = await _task(session, claim.task_id)
        artifact = await work_service.add_artifact(
            session, task, ArtifactKind.note, body=payload.body, data=payload.data,
            title=payload.title, caller=caller, claim=claim,
        )
    except WorkError as exc:
        await session.rollback()
        raise http(exc) from exc
    except ValueError as exc:  # pydantic validation of the plan data
        await session.rollback()
        raise HTTPException(
            status_code=422, detail={"code": "bad_plan", "message": str(exc)}
        ) from exc
    await session.commit()
    return PlanResponse(artifact=ArtifactRead.model_validate(artifact), governing_decisions=[],
                        unsettled=[], approval=PlanApproval(required=False))


@router.post("/work/claims/{claim_id}/gates", response_model=GateRead)
async def ask_human(
    session: SessionDep, caller: CallerDep, claim_id: int, payload: AskRequest
) -> GateRead:
    """Ask a person: a `question` (it needs an answer) or an `escalation` (it should not go on).
    Ends the claim; the task is held until a person responds in the Reviews inbox."""
    try:
        claim = await work_service.get_claim(session, claim_id)
        gate = await work_service.ask_human(
            session, claim, caller, kind=GateKind(payload.kind), title=payload.title,
            prompt=payload.prompt,
            options=[o.model_dump() for o in payload.options], allow_text=payload.allow_text,
        )
    except WorkError as exc:
        await session.rollback()
        raise http(exc) from exc
    await session.commit()
    await work_service.notify(gate.project_id, gate.task_id, gate_id=gate.id)
    return await gate_read(session, gate, caller)


@router.post("/work/claims/{claim_id}/submit", response_model=SubmitResponse)
async def submit(
    session: SessionDep, caller: CallerDep, claim_id: int, payload: SubmitRequest
) -> SubmitResponse:
    """Hand off: canopy evaluates the target column's entry checks, then advances the task,
    returns it for rework, or opens a gate. A refusal (`checks_failed`) lists what's missing;
    the claim stays yours."""
    if (payload.handoff is None) == (payload.review is None):
        raise HTTPException(status_code=422, detail={
            "code": "bad_submit", "message": "Send exactly one of handoff or review"})
    try:
        claim = await work_service.get_claim(session, claim_id)
        if payload.handoff is not None:
            data: dict[str, Any] = payload.handoff.model_dump()
            result = await work_service.submit_work(
                session, claim, caller, kind=ArtifactKind.handoff,
                body=payload.handoff.body or payload.handoff.summary, data=data,
                to_status=payload.to_status, usage=payload.usage,
            )
        else:
            assert payload.review is not None
            review = payload.review
            result = await work_service.submit_work(
                session, claim, caller, kind=ArtifactKind(review.kind),
                body=review.body, data=review.model_dump(), verdict=review.verdict,
                to_status=payload.to_status, usage=payload.usage,
            )
    except WorkError as exc:
        await session.rollback()
        if exc.code == "checks_failed":
            # Nothing was saved, but the refusal is part of the decision log, and asking still
            # proves the session is alive. (The rollback expired the caller's rows.)
            await session.refresh(caller.user)
            if caller.token is not None:
                await session.refresh(caller.token)
            held = await session.get(WorkClaim, claim_id)
            refused = await session.get(Task, held.task_id) if held is not None else None
            if held is not None and refused is not None:
                with contextlib.suppress(WorkError):
                    await work_service.renew(session, held)
                work_service.record_event(
                    session, kind=WorkEventKind.checks_evaluated,
                    project_id=refused.project_id, task_id=refused.id, caller=caller,
                    claim_id=held.id, data=exc.extra.get("evaluation") or {},
                )
                await session.commit()
        raise http(exc) from exc
    await session.commit()
    await session.refresh(result.task)
    await work_service.notify(result.task.project_id, result.task.id, claim_id=claim_id)
    return SubmitResponse(
        claim=ClaimRead.model_validate(result.claim), task=TaskRead.model_validate(result.task),
        moved_to=result.moved_to,
        gate=await gate_read(session, result.gate, caller) if result.gate is not None else None,
        evaluation=result.evaluation, warnings=result.warnings,
    )


@router.post("/work/claims/{claim_id}/release", response_model=ClaimRead)
async def release(
    session: SessionDep, caller: CallerDep, claim_id: int, payload: ReleaseRequest
) -> WorkClaim:
    """Give the task back with a note for the next session — or say a person is needed
    (`needs_human`: an escalation gate opens). A planner may release anyone's claim."""
    try:
        claim = await work_service.get_claim(session, claim_id)
        task = await _task(session, claim.task_id)
        holder = claim.user_id == caller.user_id and claim.agent_token_id == caller.token_id
        as_planner = not holder and not caller.is_agent and await _may_plan(session, caller, task)
        await work_service.release_work(
            session, claim, caller, reason=payload.reason, note=payload.note,
            needs_human=payload.needs_human, as_planner=as_planner,
        )
    except WorkError as exc:
        await session.rollback()
        raise http(exc) from exc
    await session.commit()
    await session.refresh(claim)
    await work_service.notify(task.project_id, task.id, claim_id=claim.id)
    return claim


# --------------------------------------------------------------------------- #
# Task-level reads and writes
# --------------------------------------------------------------------------- #


@router.get("/tasks/{task_id}/brief")
async def get_brief(
    session: SessionDep, _: CurrentUser, task_id: int, role: str | None = None
) -> dict[str, Any]:
    """The brief, without claiming (after compaction, on resume, or a person previewing it)."""
    task = await _task(session, task_id)
    active = await session.get(WorkClaim, task.active_claim_id) if task.active_claim_id else None
    return await work_brief.build_brief(session, task, role, claim=active if role is None else None)


@router.get("/tasks/{task_id}/advance-check")
async def advance_check(
    session: SessionDep,
    caller: CallerDep,
    task_id: int,
    to_status: str | None = None,
    with_handoff: bool = False,
) -> dict[str, Any]:
    """Dry run of the policy evaluation: could this task enter `to_status` (default: the column
    after its current one) right now? The same function a hand-off uses. `with_handoff` counts
    a new hand-off as attached — what `submit_work` does before it evaluates — so a session
    sees what it still needs rather than the hand-off it hasn't sent yet."""
    task = await _task(session, task_id)
    project = await _project(session, task.project_id)
    pipeline = await policy_service.resolve_pipeline(session, project)
    current = pipeline.stage(task.status)
    target = pipeline.stage(to_status) if to_status else (
        pipeline.next_after(current) if current is not None else None
    )
    if target is None:
        raise HTTPException(status_code=422, detail={"code": "unknown_status",
                                                     "message": "No such target column"})
    from app.services import gates as gate_service

    rules = await gate_service.attestation_facts(session, task, current or target, {})
    ctx = await policy_service.evaluation_context(
        session, task, pipeline, actor="agent" if caller.is_agent else "human",
        current=caller.actor_fact(), extra_rules=rules,
    )
    if with_handoff:
        revision = max((a.revision for a in ctx.artifacts if a.kind == "handoff"), default=0)
        ctx = dataclasses.replace(ctx, artifacts=[
            *ctx.artifacts,
            stage_policy.ArtifactFact(kind="handoff", revision=revision + 1, created_at=utcnow()),
        ])
    return stage_policy.evaluate(target, ctx).to_dict()


@router.get("/tasks/{task_id}/execution", response_model=ExecutionResponse)
async def execution(
    session: SessionDep, caller: CallerDep, task_id: int
) -> ExecutionResponse:
    """The task's agent-work timeline: claims, artifacts, gates and events, plus its stage, the
    exit contract and (for a delegated task) why it isn't moving."""
    task = await _task(session, task_id)
    project = await _project(session, task.project_id)
    pipeline = await policy_service.resolve_pipeline(session, project)
    stage = pipeline.stage(task.status)
    claims = (await session.execute(
        select(WorkClaim).where(WorkClaim.task_id == task_id).order_by(col(WorkClaim.id))
    )).scalars().all()
    artifacts = (await session.execute(
        select(TaskArtifact).where(TaskArtifact.task_id == task_id)
        .order_by(col(TaskArtifact.id))
    )).scalars().all()
    gates = (await session.execute(
        select(Gate).where(Gate.task_id == task_id).order_by(col(Gate.id))
    )).scalars().all()
    events = (await session.execute(
        select(WorkEvent).where(WorkEvent.task_id == task_id).order_by(col(WorkEvent.at),
                                                                       col(WorkEvent.id))
    )).scalars().all()
    readiness: dict[str, Any] | None = None
    if task.delegation:
        work = await work_service.load_project_work(session, project, task_ids=[task_id])
        facts = await work_service.caller_facts(session, caller, project)
        verdicts = {}
        for role in pipeline.roles():
            verdict = await work_service.readiness_of(
                session, work, task, role, facts, caller.actor_fact(), utcnow()
            )
            verdicts[role] = {"ready": verdict.ready, "reason": verdict.reason,
                              "stage": verdict.stage, "detail": verdict.detail}
        readiness = {"intake": project.agent_intake, "by_role": verdicts}
    active = next((c for c in claims if c.id == task.active_claim_id), None)
    return ExecutionResponse(
        task_id=task_id,
        delegation=task.delegation,
        stage=stage.status_name if stage else task.status,
        worked_by=stage.worked_by if stage else None,
        active_claim=ClaimRead.model_validate(active) if active is not None else None,
        claims=[ClaimRead.model_validate(c) for c in claims],
        artifacts=[ArtifactRead.model_validate(a) for a in artifacts],
        gates=[await gate_read(session, g, caller) for g in gates],
        events=[WorkEventRead.model_validate(e) for e in events],
        exit_contract=work_brief.exit_contract(pipeline, stage) if stage is not None else None,
        readiness=readiness,
    )


@router.get("/tasks/{task_id}/artifacts", response_model=list[ArtifactRead])
async def list_artifacts(
    session: SessionDep, _: CurrentUser, task_id: int, kind: str | None = None
) -> list[TaskArtifact]:
    stmt = select(TaskArtifact).where(TaskArtifact.task_id == task_id)
    if kind:
        stmt = stmt.where(TaskArtifact.kind == kind)
    return list((await session.execute(stmt.order_by(col(TaskArtifact.id)))).scalars().all())


@router.post("/tasks/{task_id}/artifacts", response_model=ArtifactRead)
async def add_task_artifact(
    session: SessionDep, caller: CallerDep, _writer: ContributorWriter, task_id: int,
    payload: ArtifactCreate,
) -> TaskArtifact:
    """A person adds a `note` (guidance for the next attempt) or a new `plan` revision. Outside a
    claim a plan revision is human-only: an agent writes plans through its claim, where the
    checkpoint is evaluated."""
    task = await _task(session, task_id)
    if payload.kind == "plan" and caller.is_agent:
        raise HTTPException(status_code=403, detail={
            "code": "human_only", "message": "Agents record plans through their claim"})
    await _ensure_planner_or_assignee(session, caller, task)
    data = payload.data
    if payload.kind == "plan":
        try:
            data = PlanData.model_validate(payload.data).model_dump()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"code": "bad_plan",
                                                         "message": str(exc)}) from exc
    artifact = await work_service.add_artifact(
        session, task, ArtifactKind(payload.kind), body=payload.body, data=data,
        title=payload.title, caller=caller,
    )
    await session.commit()
    await work_service.notify(task.project_id, task.id)
    return artifact


@router.get("/artifacts/{artifact_id}", response_model=ArtifactRead)
async def get_artifact(session: SessionDep, _: CurrentUser, artifact_id: int) -> TaskArtifact:
    artifact = await session.get(TaskArtifact, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return artifact


@router.post("/tasks/{task_id}/delegation", response_model=DelegationResponse)
async def set_delegation(
    session: SessionDep, caller: CallerDep, _writer: ContributorWriter, _human: HumanOnly,
    task_id: int, payload: DelegationRequest,
) -> DelegationResponse:
    """Delegate a task to agents, or take it back (human-only: a planner who may edit the
    project, or the task's assignee). Returns advice when the task is a poor candidate."""
    task = await _task(session, task_id)
    await _ensure_planner_or_assignee(session, caller, task)
    try:
        hints = await work_service.set_delegation(session, task, caller, payload.delegation)
    except WorkError as exc:
        await session.rollback()
        raise http(exc) from exc
    await session.commit()
    await session.refresh(task)
    await work_service.notify(task.project_id, task.id)
    return DelegationResponse(task=TaskRead.model_validate(task), hints=hints)


@router.post("/tasks/{task_id}/take-over", response_model=TaskRead)
async def take_over(
    session: SessionDep, caller: CallerDep, _writer: ContributorWriter, _human: HumanOnly,
    task_id: int,
) -> Task:
    """A person takes the task back: undelegated, active claims stopped, open gates closed."""
    task = await _task(session, task_id)
    await _ensure_planner_or_assignee(session, caller, task)
    await work_service.take_over(session, task, caller)
    await session.commit()
    await session.refresh(task)
    await work_service.notify(task.project_id, task.id)
    return task


@router.get("/tasks/{task_id}/components", response_model=ComponentsResponse)
async def get_components(session: SessionDep, _: CurrentUser, task_id: int) -> ComponentsResponse:
    await _task(session, task_id)
    return ComponentsResponse(
        task_id=task_id, component_ids=await work_service.task_component_ids(session, task_id)
    )


@router.put("/tasks/{task_id}/components", response_model=ComponentsResponse)
async def put_components(
    session: SessionDep, caller: CallerDep, _writer: ContributorWriter, task_id: int,
    payload: ComponentsRequest,
) -> ComponentsResponse:
    """Declare the architecture components a task touches (how the brief finds the decisions
    that govern it). Planners, the assignee, or the session holding the task's claim."""
    task = await _task(session, task_id)
    holder = False
    if task.active_claim_id is not None:
        claim = await session.get(WorkClaim, task.active_claim_id)
        holder = claim is not None and claim.user_id == caller.user_id and (
            claim.agent_token_id == caller.token_id
        )
    if not holder:
        await _ensure_planner_or_assignee(session, caller, task)
    try:
        ids = await work_service.set_components(session, task, payload.component_ids, caller)
    except WorkError as exc:
        await session.rollback()
        raise http(exc) from exc
    await session.commit()
    return ComponentsResponse(task_id=task_id, component_ids=ids)


# --------------------------------------------------------------------------- #
# Project: intake + the Agents view
# --------------------------------------------------------------------------- #


@router.post("/projects/{project_id}/agent-intake", response_model=IntakeResponse)
async def set_intake(
    session: SessionDep, caller: CallerDep, user: PlannerWriter, _human: HumanOnly,
    project_id: int, payload: IntakeRequest,
) -> IntakeResponse:
    """Switch agent intake off / on / paused (human-only, planners who may edit the project).
    `off` is the kill switch: every active claim is stopped at its next heartbeat."""
    project = await _project(session, project_id)
    await ensure_project_editable(session, user, project_id)
    try:
        stopped = await work_service.set_intake(session, project, caller, payload.state)
    except WorkError as exc:
        await session.rollback()
        raise http(exc) from exc
    await session.commit()
    await work_service.notify(project_id)
    return IntakeResponse(project_id=project_id, agent_intake=project.agent_intake,
                          stopped=stopped)


@router.get("/projects/{project_id}/agents", response_model=AgentsViewResponse)
async def agents_view(
    session: SessionDep, caller: CallerDep, project_id: int
) -> AgentsViewResponse:
    """The project's agent work at a glance: intake, who works which column, what's ready by
    role, who is working, what waits on people, and what is parked."""
    project = await _project(session, project_id)
    pipeline = await policy_service.resolve_pipeline(session, project)
    ready: dict[str, list[QueueItemRead]] = {}
    reasons: dict[str, int] = {}
    view_caller = Caller(user=caller.user, token=None, is_agent=False,
                         engineer_id=caller.engineer_id)
    for role in pipeline.roles():
        result = await work_service.find_work(session, view_caller, role, project_id=project_id)
        ready[role] = [_queue_item(i) for i in result.ready]
        for reason, count in result.reasons.items():
            reasons[reason] = max(reasons.get(reason, 0), count)
    now = utcnow()
    task_ids = select(col(Task.id)).where(col(Task.project_id) == project_id)
    working: list[AgentsWorkingRead] = []
    for claim in (await session.execute(
        select(WorkClaim).where(col(WorkClaim.task_id).in_(task_ids),
                                WorkClaim.state == ClaimState.active.value)
        .order_by(col(WorkClaim.claimed_at))
    )).scalars().all():
        task = await session.get(Task, claim.task_id)
        working.append(AgentsWorkingRead(
            claim=ClaimRead.model_validate(claim),
            task_key=task.key if task else None, task_name=task.name if task else "",
            heartbeat_age_s=max(0, int((now - claim.heartbeat_at).total_seconds())),
        ))
    open_gates = (await session.execute(
        select(Gate).where(Gate.project_id == project_id, Gate.status == GateStatus.open.value)
        .order_by(col(Gate.created_at))
    )).scalars().all()
    waiting = [await gate_read(session, g, caller) for g in open_gates
               if not (g.kind == GateKind.escalation.value and g.origin == "system")]
    parked: list[ParkedRead] = []
    for gate in open_gates:
        if gate.kind == GateKind.escalation.value and gate.origin == "system" and gate.id:
            task = await session.get(Task, gate.task_id)
            if task is not None and task.id is not None:
                parked.append(ParkedRead(task_id=task.id, key=task.key, name=task.name,
                                         gate_id=gate.id))
    delegated = len((await session.execute(
        select(Task.id).where(Task.project_id == project_id, col(Task.delegation).is_not(None))
    )).scalars().all())
    return AgentsViewResponse(
        project_id=project_id, agent_intake=project.agent_intake,
        can_manage=not caller.is_agent and await project_can_edit(session, caller.user, project),
        configured=pipeline.configured,
        stages=[StageRead(status=s.status_name, category=s.category, worked_by=s.worked_by,
                          source=s.source) for s in pipeline.stages],
        ready=ready, reasons=reasons, working=working, waiting=waiting, parked=parked,
        delegated=delegated,
    )


def readiness_reasons() -> list[str]:
    return [v for k, v in vars(work_queue).items() if k.startswith("REASON_")]
