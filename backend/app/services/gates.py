"""Gates: blocking requests for a human decision — docs/AGENT_EXECUTION.md §9.4.

**The only writer** of `Gate.status` and `Gate.decision` (`tests/test_work_invariants.py`).
Deciding is human-only (the API refuses agent tokens; there is no MCP tool for it). Who may
decide follows the gate's approver rule, widened over time by escalation (the project owner,
then the initiative's owners, then the team's directors); with `exclude_requester` the person
whose token the producing agent ran under can't approve. A decision names the subject revision
the approver looked at (`409 stale_subject` otherwise) and routes the task: approve → onward,
request changes → rework, reject → cancelled, answer / retry → ready again, take over →
undelegated. Nothing is ever approved by a timeout. A gate may also be satisfied by evidence: a
GitHub approval from someone other than the requester, or the merge.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.models.architecture import ArchitectureComponent
from app.models.base import (
    CANOPY_OWNER,
    ActorKind,
    ArtifactKind,
    ClaimOutcome,
    ClaimState,
    DecidedVia,
    Delegation,
    GateDecision,
    GateKind,
    GateStatus,
    TeamRole,
    UserRole,
    WorkEventKind,
    utcnow,
)
from app.models.gate import Gate
from app.models.integration import PullRequest
from app.models.leadership import InitiativeLead
from app.models.org import TeamMember
from app.models.project import Project, Task
from app.models.team import Engineer
from app.models.user import User
from app.models.work import TaskArtifact, WorkClaim, WorkEvent
from app.services import flow, policy_service, pr_signals, stage_policy, work_service
from app.services.access import project_can_edit
from app.services.org import project_team_id
from app.services.stage_policy import ConditionFacts, DecisionFact, DecisionSpec, StageDef
from app.services.work_service import Caller, WorkError, record_event
from app.services.workflow import TrackingError, category_of_task, move_task

if TYPE_CHECKING:
    from app.services.work_service import GoverningDecision

APPROVAL_DECISIONS = [
    GateDecision.approve.value,
    GateDecision.approve_with_conditions.value,
    GateDecision.request_changes.value,
    GateDecision.reject.value,
    GateDecision.take_over.value,
]
ALLOWED: dict[str, list[str]] = {
    GateKind.plan_approval.value: [GateDecision.approve.value, GateDecision.edit_and_approve.value,
                                   *APPROVAL_DECISIONS[1:]],
    GateKind.handoff_approval.value: APPROVAL_DECISIONS,
    GateKind.signoff.value: APPROVAL_DECISIONS,
    GateKind.question.value: [GateDecision.answer.value, GateDecision.take_over.value,
                              GateDecision.reject.value],
    GateKind.escalation.value: [GateDecision.retry.value, GateDecision.take_over.value,
                                GateDecision.reject.value],
}
STATUS_OF: dict[str, str] = {
    GateDecision.approve.value: GateStatus.approved.value,
    GateDecision.edit_and_approve.value: GateStatus.approved.value,
    GateDecision.approve_with_conditions.value: GateStatus.approved.value,
    GateDecision.request_changes.value: GateStatus.changes_requested.value,
    GateDecision.reject.value: GateStatus.rejected.value,
    GateDecision.answer.value: GateStatus.answered.value,
    GateDecision.retry.value: GateStatus.answered.value,
    GateDecision.take_over.value: GateStatus.cancelled.value,
    GateDecision.cancelled.value: GateStatus.cancelled.value,
}
NOTE_REQUIRED = {GateDecision.request_changes.value, GateDecision.reject.value,
                 GateDecision.retry.value}
MAX_ESCALATION_LEVEL = 3


def allowed_for(kind: str) -> list[str]:
    return list(ALLOWED.get(kind, APPROVAL_DECISIONS))


# --------------------------------------------------------------------------- #
# Opening
# --------------------------------------------------------------------------- #


async def _pr_snapshot(session: AsyncSession, task_id: int) -> dict[str, Any] | None:
    pr = await policy_service.latest_pull_request(session, task_id)
    if pr is None:
        return None
    return {
        "repo": pr.repo, "number": pr.number, "url": pr.url, "state": pr.state,
        "merged": pr.merged, "head_sha": pr.head_sha, "checks_state": pr.checks_state,
        "review_decision": pr.review_decision, "approved_by": list(pr.approved_by or []),
        "changed_lines": (int(pr.additions or 0) + int(pr.deletions or 0))
        if pr.additions is not None or pr.deletions is not None else None,
    }


async def open_gate(
    session: AsyncSession,
    task: Task,
    *,
    kind: GateKind | str,
    origin: str,
    stage: str | None,
    title: str,
    prompt: str | None = None,
    options: Sequence[dict[str, str]] = (),
    allow_text: bool = True,
    reasons: Sequence[str] = (),
    claim: WorkClaim | None = None,
    caller: Caller | None = None,
    subject: TaskArtifact | None = None,
    decision: DecisionSpec | None = None,
    evidence: dict[str, Any] | None = None,
    on_approve: str | None = None,
    on_changes: str | None = None,
    on_reject: str | None = None,
) -> Gate:
    """Open a gate on `task` (it is held until a person decides)."""
    assert task.id is not None
    kind_value = kind.value if isinstance(kind, GateKind) else str(kind)
    spec = decision or DecisionSpec(
        kind=kind_value,
        approvers="project_planners",
        exclude_requester=kind_value not in (GateKind.question.value, GateKind.escalation.value),
    )
    now = utcnow()
    requester = claim.user_id if claim is not None else (caller.user_id if caller else None)
    exclude = spec.exclude_requester and kind_value not in (
        GateKind.question.value, GateKind.escalation.value,
    )
    gate = Gate(
        task_id=task.id,
        project_id=task.project_id,
        kind=kind_value,
        origin=origin,
        stage=stage,
        title=title[:200],
        prompt=prompt,
        options=[{"value": str(o.get("value") or o.get("label") or ""),
                  "label": str(o.get("label") or o.get("value") or "")} for o in options][:10],
        allow_text=allow_text,
        allowed_decisions=allowed_for(kind_value),
        reasons=list(reasons),
        evidence={**(evidence or {}), "pull_request": await _pr_snapshot(session, task.id)},
        subject_artifact_id=subject.id if subject is not None else None,
        requested_by_claim_id=claim.id if claim is not None else None,
        requested_by_user_id=requester,
        approvers=("assignee_or_planners" if kind_value == GateKind.question.value
                   else spec.approvers),
        approver_engineer_ids=list(spec.approver_engineer_ids),
        exclude_requester=exclude,
        satisfied_by=list(spec.satisfied_by),
        remind_at=now + timedelta(hours=spec.remind_after_hours),
        escalate_at=now + timedelta(hours=spec.escalate_after_hours),
        on_approve=on_approve or spec.on_approve,
        on_changes=on_changes or spec.on_changes,
        on_reject=on_reject or spec.on_reject,
    )
    session.add(gate)
    await session.flush()
    if exclude and requester is not None and not await _anyone_else_may_decide(session, gate):
        gate.exclude_requester = False
        gate.evidence = {**gate.evidence, "self_approval_allowed": "no one else may decide"}
    record_event(session, kind=WorkEventKind.gate_opened, project_id=task.project_id,
                 task_id=task.id, caller=caller,
                 actor_kind=None if caller else ActorKind.system.value,
                 claim_id=claim.id if claim else None, gate_id=gate.id,
                 data={"kind": kind_value, "origin": origin, "reasons": list(reasons)})
    return gate


async def open_column_gate(
    session: AsyncSession,
    task: Task,
    stage: StageDef,
    *,
    caller: Caller | None,
    claim: WorkClaim | None,
    evidence: dict[str, Any] | None,
) -> Gate | None:
    """The task entered a decision column. When the decision's conditions match (or always),
    open its gate; otherwise the task passes straight through to `on_approve`."""
    spec = stage.decision or DecisionSpec()
    reasons = await checkpoint_reasons(session, task, spec.when)
    if not reasons:
        project = await session.get(Project, task.project_id)
        assert project is not None
        pipeline = await policy_service.resolve_pipeline(session, project)
        target = pipeline.stage(spec.on_approve) or pipeline.next_after(stage)
        if target is not None:
            await _move(session, task, target.status_name, author="canopy",
                        actor_kind=ActorKind.system.value)
        return None
    handoff = await work_service.latest_artifact(session, task.id or 0, ArtifactKind.handoff)
    return await open_gate(
        session, task, kind=spec.kind, origin="column", stage=stage.status_name,
        title=f"{stage.status_name}: {task.key or task.name}",
        prompt=(handoff.body[:4000] if handoff is not None else None), reasons=reasons,
        claim=claim, caller=caller, subject=handoff, decision=spec, evidence=evidence,
    )


# --------------------------------------------------------------------------- #
# Conditions (must a person look?)
# --------------------------------------------------------------------------- #


async def agent_done_count(session: AsyncSession, project_id: int) -> int:
    """Tasks in the project that reached done after agent work (for `probation:N`)."""
    done_ids = [
        t.id for t in (
            await session.execute(select(Task).where(Task.project_id == project_id))
        ).scalars().all()
        if t.id is not None and category_of_task(t) == flow.DONE
    ]
    if not done_ids:
        return 0
    rows = (
        await session.execute(
            select(WorkClaim.task_id).where(
                col(WorkClaim.task_id).in_(done_ids),
                WorkClaim.outcome == ClaimOutcome.advanced.value,
            )
        )
    ).scalars().all()
    return len(set(rows))


async def checkpoint_reasons(
    session: AsyncSession,
    task: Task,
    conditions: Sequence[str],
    *,
    artifact: TaskArtifact | None = None,
    component_ids: Sequence[int] | None = None,
    binding: Sequence[GoverningDecision] | None = None,
    unsettled: Sequence[GoverningDecision] | None = None,
) -> list[str]:
    """Evaluate a checkpoint's / decision's conditions from stored facts, once. The reasons that
    matched are stored on the gate, so a later change in the data can't flip the outcome."""
    assert task.id is not None
    if not conditions or list(conditions) == ["never"]:
        return []
    if component_ids is None:
        component_ids = await work_service.task_component_ids(session, task.id)
    if binding is None or unsettled is None:
        binding, unsettled = await work_service.decisions_for(session, task, component_ids)
    comps = (
        await session.execute(
            select(ArchitectureComponent).where(
                col(ArchitectureComponent.id).in_(list(component_ids) or [-1])
            )
        )
    ).scalars().all()
    data = (artifact.data or {}) if artifact is not None else {}
    criteria = 0
    spec_ok = False
    if task.spec_id is not None:
        from app.models.spec import Spec, SpecCriterion

        spec = await session.get(Spec, task.spec_id)
        spec_ok = spec is not None and str(
            spec.status.value if hasattr(spec.status, "value") else spec.status
        ) in ("approved", "in_progress", "verified")
        criteria = len(
            (await session.execute(
                select(SpecCriterion.id).where(SpecCriterion.spec_id == task.spec_id)
            )).scalars().all()
        )
    facts = ConditionFacts(
        governing=[DecisionFact(d.adr_id, d.number, d.title, d.status, d.reversibility)
                   for d in binding],
        unsettled=[DecisionFact(d.adr_id, d.number, d.title, d.status, d.reversibility)
                   for d in unsettled],
        high_criticality=[c.name for c in comps if (c.criticality or "").lower() == "high"],
        spec_approved=spec_ok,
        criteria_count=criteria,
        plan_confidence=str(data.get("confidence")) if data.get("confidence") else None,
        change_classes=[str(c) for c in data.get("change_classes") or []],
        affected_paths=len(data.get("affected_paths") or []),
        task_duration_days=task.duration,
        tags=[t.lower() for t in task.tags or []],
        agent_done_count=await agent_done_count(session, task.project_id)
        if any(c.startswith("probation") for c in conditions) else 0,
    )
    return stage_policy.matched_conditions(conditions, facts)


async def attestation_facts(
    session: AsyncSession, task: Task, stage: StageDef, data: dict[str, Any]
) -> tuple[list[str], dict[str, str], dict[str, str]]:
    """The Definition-of-Done rule keys this hand-off must attest, what it attests, and each
    rule's enforcement (an unattested `block` rule refuses the hand-off, §10)."""
    from app.services import rules as rules_service

    rules = await rules_service.attestation_rules(session, task, stage)
    attested = {
        str(a.get("rule_key")): str(a.get("status") or "")
        for a in data.get("attestations") or [] if a.get("rule_key")
    }
    return [r.key for r in rules], attested, {r.key: r.enforcement for r in rules}


# --------------------------------------------------------------------------- #
# Who may decide
# --------------------------------------------------------------------------- #


async def _engineer_ids(session: AsyncSession, user: User) -> set[int]:
    rows = (await session.execute(select(Engineer.id).where(Engineer.user_id == user.id))
            ).scalars().all()
    return {r for r in rows if r is not None}


async def may_decide(session: AsyncSession, gate: Gate, user: User) -> tuple[bool, str | None]:
    """(may, why not). Admins may always decide; separation of duties is checked separately."""
    if not user.is_active:
        return False, "inactive"
    task = await session.get(Task, gate.task_id)
    project = await session.get(Project, gate.project_id)
    if task is None or project is None:
        return False, "missing"
    if user.role == UserRole.admin:
        return True, None
    engineers = await _engineer_ids(session, user)
    planner = await project_can_edit(session, user, project)
    rule = gate.approvers
    allowed = False
    if rule in ("project_planners", "assignee_or_planners"):
        allowed = planner
    if rule in ("assignee", "assignee_or_planners"):
        allowed = allowed or (task.assignee_engineer_id in engineers)
    if rule == "project_owner":
        allowed = project.owner_engineer_id in engineers
    if rule == "engineers":
        allowed = bool(engineers & {int(e) for e in gate.approver_engineer_ids or []})
    if rule == "initiative_leads" or (gate.escalation_level >= 2 and not allowed):
        allowed = allowed or await _is_initiative_lead(session, project, engineers)
    if rule == "team_directors" or (gate.escalation_level >= 3 and not allowed):
        allowed = allowed or await _is_team_director(session, project, engineers)
    if gate.escalation_level >= 1 and not allowed:
        allowed = project.owner_engineer_id in engineers
    return (True, None) if allowed else (False, "not_an_approver")


async def _is_initiative_lead(session: AsyncSession, project: Project, engineers: set[int]) -> bool:
    if project.initiative_id is None or not engineers:
        return False
    rows = (
        await session.execute(
            select(InitiativeLead.engineer_id).where(
                InitiativeLead.initiative_id == project.initiative_id
            )
        )
    ).scalars().all()
    return bool(engineers & set(rows))


async def _is_team_director(session: AsyncSession, project: Project, engineers: set[int]) -> bool:
    team_id = await project_team_id(session, project)
    if team_id is None or not engineers:
        return False
    rows = (
        await session.execute(
            select(TeamMember.engineer_id).where(
                TeamMember.team_id == team_id, TeamMember.role == TeamRole.director
            )
        )
    ).scalars().all()
    return bool(engineers & set(rows))


async def _anyone_else_may_decide(session: AsyncSession, gate: Gate) -> bool:
    users = (
        await session.execute(select(User).where(col(User.is_active).is_(True)))
    ).scalars().all()
    for user in users:
        if user.id == gate.requested_by_user_id:
            continue
        ok, _ = await may_decide(session, gate, user)
        if ok:
            return True
    return False


# --------------------------------------------------------------------------- #
# Deciding + routing
# --------------------------------------------------------------------------- #


async def _move(
    session: AsyncSession, task: Task, to_status: str, *, author: str, actor_kind: str
) -> bool:
    if task.status_owner != CANOPY_OWNER:
        return False
    try:
        await move_task(session, task, to_status=to_status, author=author, actor_kind=actor_kind)
    except TrackingError:
        return False
    return True


async def _pipeline(session: AsyncSession, task: Task) -> stage_policy.Pipeline:
    project = await session.get(Project, task.project_id)
    assert project is not None
    return await policy_service.resolve_pipeline(session, project)


async def route_approved(session: AsyncSession, gate: Gate, *, author: str) -> bool:
    """Move an approved gate's task on — when the target column's checks pass. Otherwise it
    waits in place ("approved — waiting for evidence") and a later PR event retries."""
    task = await session.get(Task, gate.task_id)
    if task is None or gate.routed_at is not None:
        return False
    if gate.kind == GateKind.plan_approval.value:
        gate.routed_at = utcnow()  # the work continues in place
        return True
    pipeline = await _pipeline(session, task)
    stage = pipeline.stage(gate.stage) or pipeline.stage(task.status)
    target = pipeline.stage(gate.on_approve) if gate.on_approve else (
        pipeline.next_after(stage) if stage is not None else None
    )
    if target is None:
        gate.routed_at = utcnow()
        return True
    ctx = await policy_service.evaluation_context(session, task, pipeline, actor="system")
    evaluation = stage_policy.evaluate(target, ctx)
    if not evaluation.allowed:
        gate.evidence = {**(gate.evidence or {}), "waiting_for": evaluation.to_dict()}
        return False
    if await _move(session, task, target.status_name, author=author,
                   actor_kind=ActorKind.system.value):
        gate.routed_at = utcnow()
        record_event(session, kind=WorkEventKind.advanced, project_id=task.project_id,
                     task_id=task.id, actor_kind=ActorKind.system.value, gate_id=gate.id,
                     data={"from": stage.status_name if stage else task.status,
                           "to": target.status_name, "via": "gate"})
        if target.is_decision_column:
            await open_column_gate(session, task, target, caller=None, claim=None,
                                   evidence=evaluation.to_dict())
        return True
    return False


async def rework_rounds(session: AsyncSession, task: Task, stage_name: str) -> int:
    """Times the task was sent back to `stage_name` since the last "retry with guidance"."""
    assert task.id is not None
    resets = await work_service.attempt_resets(session, [task.id])
    since = resets.get(task.id)
    rows = (
        await session.execute(
            select(WorkEvent).where(
                WorkEvent.task_id == task.id, WorkEvent.kind == WorkEventKind.returned.value
            )
        )
    ).scalars().all()
    key = stage_name.casefold()
    return sum(
        1 for e in rows
        if str((e.data or {}).get("stage") or "").casefold() == key
        and (since is None or e.at >= since)
    )


async def _route_changes(session: AsyncSession, gate: Gate, task: Task, *, author: str) -> None:
    pipeline = await _pipeline(session, task)
    stage = pipeline.stage(gate.stage) or pipeline.stage(task.status)
    if gate.origin == "checkpoint" or stage is None:
        target_name = gate.stage or task.status
    else:
        target = pipeline.stage(gate.on_changes) if gate.on_changes else pipeline.rework_target(
            stage
        )
        target_name = target.status_name if target is not None else task.status
    if target_name and (task.status or "").casefold() != target_name.casefold():
        await _move(session, task, target_name, author=author, actor_kind=ActorKind.human.value)
    record_event(session, kind=WorkEventKind.returned, project_id=task.project_id,
                 task_id=task.id, actor_kind=ActorKind.human.value, gate_id=gate.id,
                 data={"from": gate.stage, "to": target_name, "stage": target_name,
                       "note": gate.response_note})
    target_stage = pipeline.stage(target_name)
    if target_stage is not None and target_stage.is_agent_stage:
        rounds = await rework_rounds(session, task, target_stage.status_name)
        if rounds > target_stage.max_rework:
            await open_gate(
                session, task, kind=GateKind.escalation, origin="system",
                stage=target_stage.status_name,
                title=f"The review loop on {task.key or task.name} is not converging",
                prompt=f"Sent back to {target_stage.status_name} {rounds} times.",
                reasons=[f"Returned for rework more than {target_stage.max_rework} times"],
            )


async def _route_reject(session: AsyncSession, gate: Gate, task: Task, *, author: str,
                        caller: Caller | None) -> None:
    pipeline = await _pipeline(session, task)
    target = pipeline.stage(gate.on_reject) if gate.on_reject else pipeline.first_of(
        flow.CANCELLED
    )
    await work_service.supersede_claims(session, task, "cancelled", caller)
    if target is not None:
        await _move(session, task, target.status_name, author=author,
                    actor_kind=ActorKind.human.value)


def _finish(gate: Gate, decision: str, *, via: str, user: User | None, label: str | None,
            note: str | None, data: dict[str, Any] | None) -> None:
    gate.decision = decision
    gate.status = STATUS_OF.get(decision, GateStatus.cancelled.value)
    gate.decided_via = via
    gate.decided_by_user_id = user.id if user is not None else None
    gate.decided_by_label = label or (user.full_name or user.email if user is not None else None)
    gate.decided_at = utcnow()
    gate.response_note = note
    gate.response_data = data or {}


async def decide(
    session: AsyncSession,
    gate: Gate,
    caller: Caller,
    *,
    decision: str,
    note: str | None = None,
    option: str | None = None,
    plan: dict[str, Any] | None = None,
    subject_revision: int | None = None,
) -> Gate:
    """A person's response (human-only — the API refuses agent tokens). Raises WorkError."""
    if gate.status != GateStatus.open.value:
        raise WorkError("gate_closed", "This gate was already decided", 409, status=gate.status)
    if decision not in (gate.allowed_decisions or allowed_for(gate.kind)):
        raise WorkError("decision_not_allowed", f"{decision!r} isn't a response to this gate",
                        422, allowed=list(gate.allowed_decisions or []))
    ok, why = await may_decide(session, gate, caller.user)
    if not ok:
        raise WorkError("not_an_approver", "You can't decide this gate", 403, reason=why)
    if gate.exclude_requester and gate.requested_by_user_id == caller.user_id:
        raise WorkError("self_approval_blocked",
                        "The person whose token produced this work can't approve it", 403)
    clean_note = (note or "").strip() or None
    if decision in NOTE_REQUIRED and not clean_note:
        raise WorkError("note_required", "Say what should change (a note is required)", 422)
    task = await session.get(Task, gate.task_id)
    assert task is not None and task.id is not None
    if gate.subject_artifact_id is not None:
        subject = await session.get(TaskArtifact, gate.subject_artifact_id)
        latest = (
            await work_service.latest_artifact(session, task.id, ArtifactKind(subject.kind))
            if subject is not None else None
        )
        if subject is not None and (
            (subject_revision is not None and subject_revision != subject.revision)
            or (latest is not None and latest.revision != subject.revision)
        ):
            raise WorkError("stale_subject",
                            "The work changed since you opened it — review the latest revision",
                            409, subject_revision=latest.revision if latest else None)
    data: dict[str, Any] = {}
    if decision == GateDecision.answer.value:
        values = [str(o.get("value")) for o in gate.options or []]
        if option is not None and values and option not in values:
            raise WorkError("bad_option", "That isn't one of the options", 422, options=values)
        if option is None and not clean_note:
            raise WorkError("answer_required", "Pick an option or write an answer", 422)
        if option is None and not gate.allow_text:
            raise WorkError("answer_required", "Pick one of the options", 422)
        data = {"option": option}
    if decision == GateDecision.edit_and_approve.value:
        if gate.kind != GateKind.plan_approval.value or not plan:
            raise WorkError("plan_required", "Edit-and-approve needs your version of the plan",
                            422)
        revised = await work_service.add_artifact(
            session, task, ArtifactKind.plan, body=str(plan.get("body") or ""),
            data={k: v for k, v in plan.items() if k != "body"}, caller=caller,
            title=str(plan.get("title") or "") or None,
        )
        gate.subject_artifact_id = revised.id
        data = {"revision": revised.revision}
    _finish(gate, decision, via=DecidedVia.canopy.value, user=caller.user, label=None,
            note=clean_note, data=data)
    record_event(session, kind=WorkEventKind.gate_decided, project_id=task.project_id,
                 task_id=task.id, caller=caller, gate_id=gate.id,
                 data={"decision": decision, "status": gate.status, "via": "canopy",
                       "note": clean_note})
    author = caller.name
    if gate.status == GateStatus.approved.value:
        await route_approved(session, gate, author=author)
    elif decision == GateDecision.request_changes.value:
        await _route_changes(session, gate, task, author=author)
    elif decision == GateDecision.reject.value:
        await _route_reject(session, gate, task, author=author, caller=caller)
    elif decision == GateDecision.take_over.value:
        await work_service.take_over(session, task, caller)
    if decision != GateDecision.take_over.value:
        gate.routed_at = gate.routed_at or (utcnow() if gate.status != GateStatus.approved.value
                                            else None)
    return gate


async def cancel(session: AsyncSession, gate: Gate, caller: Caller, *, as_planner: bool) -> Gate:
    """Withdraw an open gate — the person (or session) who asked, or a planner."""
    if gate.status != GateStatus.open.value:
        raise WorkError("gate_closed", "This gate was already decided", 409)
    if not as_planner and gate.requested_by_user_id != caller.user_id:
        raise WorkError("not_requester", "Only who asked (or a planner) can withdraw it", 403)
    _finish(gate, GateDecision.cancelled.value, via=DecidedVia.canopy.value, user=caller.user,
            label=None, note="withdrawn", data={})
    record_event(session, kind=WorkEventKind.gate_decided, project_id=gate.project_id,
                 task_id=gate.task_id, caller=caller, gate_id=gate.id,
                 data={"decision": GateDecision.cancelled.value, "status": gate.status})
    return gate


async def reassign(
    session: AsyncSession, gate: Gate, caller: Caller, engineer_ids: Sequence[int]
) -> Gate:
    """Hand the decision to named engineers (a planner, human-only). Escalation still widens
    it over time; separation of duties still applies."""
    if gate.status != GateStatus.open.value:
        raise WorkError("gate_closed", "This gate was already decided", 409)
    wanted = sorted({int(e) for e in engineer_ids})
    found = set(
        (await session.execute(select(Engineer.id).where(col(Engineer.id).in_(wanted))))
        .scalars().all()
    )
    missing = [e for e in wanted if e not in found]
    if missing:
        raise WorkError("unknown_engineer", f"No such engineers: {missing}", 422)
    previous = {"approvers": gate.approvers, "engineer_ids": list(gate.approver_engineer_ids or [])}
    gate.approvers = "engineers"
    gate.approver_engineer_ids = wanted
    record_event(session, kind=WorkEventKind.gate_reassigned, project_id=gate.project_id,
                 task_id=gate.task_id, caller=caller, gate_id=gate.id,
                 data={"from": previous, "to": wanted})
    return gate


async def close_open_gates(
    session: AsyncSession, task: Task, *, reason: str, caller: Caller | None = None,
    via: DecidedVia = DecidedVia.policy, unless_stage: str | None = None,
) -> int:
    """Close every open gate on a task because it left the queue (undelegated, taken over,
    merged ahead) — or, with `unless_stage`, the gates that held it in another column (a person
    moved the card)."""
    rows = [
        gate for gate in (
            await session.execute(
                select(Gate).where(Gate.task_id == task.id, Gate.status == GateStatus.open.value)
            )
        ).scalars().all()
        if unless_stage is None or (gate.stage or "").casefold() != unless_stage.casefold()
    ]
    for gate in rows:
        _finish(gate, GateDecision.cancelled.value, via=via.value,
                user=caller.user if caller else None, label=None, note=reason, data={})
        record_event(session, kind=WorkEventKind.gate_decided, project_id=task.project_id,
                     task_id=task.id, caller=caller,
                     actor_kind=None if caller else ActorKind.system.value, gate_id=gate.id,
                     data={"decision": GateDecision.cancelled.value, "reason": reason})
    return len(rows)


# --------------------------------------------------------------------------- #
# Time: reminders and escalation
# --------------------------------------------------------------------------- #


async def sweep(session: AsyncSession, now: datetime | None = None) -> int:
    """Escalate gates past their threshold: the project owner, then the initiative's owners,
    then the team's directors may decide too. Never approves anything. Commits."""
    now = now or utcnow()
    rows = (
        await session.execute(
            select(Gate).where(
                Gate.status == GateStatus.open.value, col(Gate.escalate_at).is_not(None),
                col(Gate.escalate_at) <= now,
            )
        )
    ).scalars().all()
    count = 0
    for gate in rows:
        if gate.escalation_level >= MAX_ESCALATION_LEVEL or gate.escalate_at is None:
            continue
        step = (gate.escalate_at - gate.created_at) if gate.created_at else timedelta(hours=24)
        gate.escalation_level += 1
        gate.escalate_at = now + max(step, timedelta(hours=1))
        record_event(session, kind=WorkEventKind.gate_escalated, project_id=gate.project_id,
                     task_id=gate.task_id, actor_kind=ActorKind.system.value, gate_id=gate.id,
                     data={"level": gate.escalation_level})
        count += 1
    await session.commit()
    return count


async def gates_for(session: AsyncSession, user: User, *, open_only: bool = True) -> list[Gate]:
    """Open gates this person may decide (for /me and the inbox's "mine" filter)."""
    stmt = select(Gate)
    if open_only:
        stmt = stmt.where(Gate.status == GateStatus.open.value)
    out: list[Gate] = []
    for gate in (await session.execute(stmt.order_by(col(Gate.created_at)))).scalars().all():
        ok, _ = await may_decide(session, gate, user)
        if ok and not (gate.exclude_requester and gate.requested_by_user_id == user.id):
            out.append(gate)
    return out


# --------------------------------------------------------------------------- #
# Evidence from GitHub: PR approvals and merges
# --------------------------------------------------------------------------- #


async def _user_for_login(session: AsyncSession, login: str) -> User | None:
    engineer = (
        await session.execute(select(Engineer).where(Engineer.github_login == login))
    ).scalars().first()
    if engineer is None or engineer.user_id is None:
        return None
    return await session.get(User, engineer.user_id)


@dataclass
class PullRequestEffects:
    satisfied: int = 0
    routed: int = 0
    merged_ahead: bool = False


async def on_pull_request(session: AsyncSession, pr: PullRequest) -> PullRequestEffects:
    """React to a PR's new review / merge state (called after the PR cache is updated): satisfy
    gates that accept GitHub evidence, retry approved gates waiting for it, and — when a PR is
    merged while its delegated task is still upstream — move the task to done (the board follows
    reality) and record the stages it skipped."""
    effects = PullRequestEffects()
    if pr.task_id is None:
        return effects
    task = await session.get(Task, pr.task_id)
    if task is None or task.id is None:
        return effects
    requester_ids = {
        g.requested_by_user_id for g in (
            await session.execute(select(Gate).where(Gate.task_id == task.id))
        ).scalars().all() if g.requested_by_user_id is not None
    }
    requester_logins = await policy_service.github_logins(session, requester_ids)
    approvers = [login for login in (pr.approved_by or []) if login not in requester_logins]
    change_request = pr_signals.latest_change_request(pr.reviews or [])
    open_gates = (
        await session.execute(
            select(Gate).where(Gate.task_id == task.id, Gate.status == GateStatus.open.value)
        )
    ).scalars().all()
    for gate in open_gates:
        satisfied_by = set(gate.satisfied_by or [])
        if "pr_merge" in satisfied_by and pr.merged:
            _finish(gate, GateDecision.approve.value, via=DecidedVia.pr_merge.value,
                    user=None, label=pr.merged_by, note="The pull request was merged", data={})
        elif "pr_approval" in satisfied_by and approvers:
            user = await _user_for_login(session, approvers[0])
            _finish(gate, GateDecision.approve.value, via=DecidedVia.pr_review.value,
                    user=user, label=approvers[0],
                    note=f"Approved on GitHub by {', '.join(approvers)}", data={})
        elif "pr_approval" in satisfied_by and change_request is not None and (
            pr.review_decision == "changes_requested"
        ):
            login = str(change_request.get("login") or "")
            if login in requester_logins:
                continue
            _finish(gate, GateDecision.request_changes.value, via=DecidedVia.pr_review.value,
                    user=await _user_for_login(session, login), label=login,
                    note=str(change_request.get("body") or "Changes requested on GitHub"),
                    data={})
            record_event(session, kind=WorkEventKind.gate_decided, project_id=task.project_id,
                         task_id=task.id, actor_kind=ActorKind.system.value, gate_id=gate.id,
                         data={"decision": gate.decision, "via": gate.decided_via})
            await _route_changes(session, gate, task, author=f"{login} (GitHub)")
            effects.satisfied += 1
            continue
        else:
            continue
        record_event(session, kind=WorkEventKind.gate_decided, project_id=task.project_id,
                     task_id=task.id, actor_kind=ActorKind.system.value, gate_id=gate.id,
                     data={"decision": gate.decision, "via": gate.decided_via})
        effects.satisfied += 1
    # Approved gates waiting for evidence (sign-off given, PR not merged yet).
    waiting = (
        await session.execute(
            select(Gate).where(
                Gate.task_id == task.id, Gate.status == GateStatus.approved.value,
                col(Gate.routed_at).is_(None),
            )
        )
    ).scalars().all()
    for gate in waiting:
        if await route_approved(session, gate, author="canopy"):
            effects.routed += 1
    await session.refresh(task)
    if (
        pr.merged
        and task.delegation == Delegation.agent.value
        and task.status_owner == CANOPY_OWNER
        and category_of_task(task) not in (flow.DONE, flow.CANCELLED)
    ):
        pipeline = await _pipeline(session, task)
        done = pipeline.first_of(flow.DONE)
        current = pipeline.stage(task.status)
        if done is not None:
            skipped = [
                s.status_name for s in pipeline.stages
                if current is not None and current.position <= s.position < done.position
                and (s.is_agent_stage or s.is_decision_column)
            ]
            await work_service.supersede_claims(session, task, "merged_ahead")
            await close_open_gates(session, task, reason="merged_ahead", via=DecidedVia.pr_merge)
            if await _move(session, task, done.status_name, author="canopy (PR merged)",
                           actor_kind=ActorKind.system.value):
                record_event(session, kind=WorkEventKind.merged_ahead_of_stage,
                             project_id=task.project_id, task_id=task.id,
                             actor_kind=ActorKind.system.value,
                             data={"skipped": skipped, "pr": pr.number, "repo": pr.repo})
                effects.merged_ahead = bool(skipped)
    return effects


def claim_states_ending() -> tuple[str, ...]:
    return (ClaimState.completed.value, ClaimState.superseded.value)
