"""The work queue, database side — docs/AGENT_EXECUTION.md §6, §8, §9, §12.

**The only writer** of `WorkClaim.state` and of `Task.active_claim_id`
(`tests/test_work_invariants.py` pins it). A claim is made with a compare-and-swap that behaves
the same on PostgreSQL, MySQL/MariaDB and SQLite — no `SKIP LOCKED`, no `RETURNING`, no
savepoints: insert the claim, then `UPDATE task SET active_claim_id = :new WHERE id = :task AND
active_claim_id IS NULL`; one row changed means the claim is ours, zero means another session
won, and the inserted row is removed before trying the next candidate. Every claim-bound write
first renews the lease with `UPDATE workclaim … WHERE id = :id AND state = 'active'`; zero rows
is `409 claim_lost`, so a session whose lease was taken over changes nothing (fencing).

Status changes still go through `workflow.move_task` → `record_transition`, the single status
writer. Nothing here commits unless a function says so; the API layer commits.
"""

from __future__ import annotations

import fnmatch
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.core.config import settings
from app.core.events import publish
from app.models.agent_token import AgentTokenRecord
from app.models.architecture import (
    ADRComponentLink,
    ADRFitnessFunction,
    ArchitectureComponent,
    ArchitectureDecision,
    ComponentCodeBinding,
    TaskComponentLink,
)
from app.models.base import (
    CANOPY_OWNER,
    ActorKind,
    AgentIntake,
    ArtifactKind,
    ClaimOutcome,
    ClaimState,
    Delegation,
    GateDecision,
    GateKind,
    GateStatus,
    TaskType,
    WorkEventKind,
    utcnow,
)
from app.models.gate import Gate
from app.models.integration import Connection
from app.models.project import Blocker, Project, Task
from app.models.team import Engineer
from app.models.user import User
from app.models.work import TaskArtifact, WorkClaim, WorkEvent
from app.services import flow, policy_service, stage_policy, work_queue
from app.services.access import project_can_edit
from app.services.sprint_service import active_sprints, project_delivery
from app.services.stage_policy import ActorFact, Pipeline, StageDef
from app.services.work_queue import CallerFacts, ClaimFact, Readiness, TaskFacts
from app.services.workflow import (
    TrackingError,
    category_of_task,
    move_task,
    resolve_workflow,
    wip_counts,
    wip_scope_project_ids,
)

# --------------------------------------------------------------------------- #
# Errors + the caller
# --------------------------------------------------------------------------- #


class WorkError(Exception):
    """A refused work-queue operation, mapped to an HTTP status with a machine-readable code."""

    def __init__(self, code: str, message: str, status_code: int, **extra: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.extra = extra

    def detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, **self.extra}


@dataclass
class Caller:
    """Who is calling: the person, the agent token they issued (None for their own session),
    and their engineer record (the accountable owner when they pull unassigned work)."""

    user: User
    token: AgentTokenRecord | None = None
    is_agent: bool = False
    engineer_id: int | None = None

    @property
    def user_id(self) -> int:
        assert self.user.id is not None
        return self.user.id

    @property
    def token_id(self) -> int | None:
        return self.token.id if self.token is not None else None

    @property
    def actor_kind(self) -> str:
        return ActorKind.agent.value if self.is_agent else ActorKind.human.value

    @property
    def name(self) -> str:
        base = self.user.full_name or self.user.email
        if self.is_agent and self.token is not None:
            return f"{base} (agent: {self.token.label})"
        return f"{base} (agent)" if self.is_agent else base

    def actor_fact(self) -> ActorFact:
        return ActorFact(agent_token_id=self.token_id, user_id=self.user_id)


async def caller_for(
    session: AsyncSession, user: User, token: AgentTokenRecord | None, *, is_agent: bool
) -> Caller:
    engineer = (
        await session.execute(select(Engineer).where(Engineer.user_id == user.id))
    ).scalars().first()
    return Caller(
        user=user,
        token=token,
        is_agent=is_agent,
        engineer_id=engineer.id if engineer is not None else None,
    )


# --------------------------------------------------------------------------- #
# Events
# --------------------------------------------------------------------------- #


def record_event(
    session: AsyncSession,
    *,
    kind: WorkEventKind,
    project_id: int,
    task_id: int | None,
    caller: Caller | None = None,
    actor_kind: str | None = None,
    claim_id: int | None = None,
    gate_id: int | None = None,
    artifact_id: int | None = None,
    data: dict[str, Any] | None = None,
    at: datetime | None = None,
) -> WorkEvent:
    event = WorkEvent(
        task_id=task_id,
        project_id=project_id,
        at=at or utcnow(),
        kind=kind.value,
        actor_kind=actor_kind or (caller.actor_kind if caller else ActorKind.system.value),
        user_id=caller.user_id if caller else None,
        agent_token_id=caller.token_id if caller else None,
        work_claim_id=claim_id,
        gate_id=gate_id,
        artifact_id=artifact_id,
        data=data or {},
    )
    session.add(event)
    return event


async def notify(project_id: int, task_id: int | None = None, **extra: Any) -> None:
    """Live refresh for boards, task panels, the Agents view and the inbox (§K)."""
    await publish({"type": "work", "project_id": project_id, "task_id": task_id, **extra})


# --------------------------------------------------------------------------- #
# Facts
# --------------------------------------------------------------------------- #


def claim_fact(claim: WorkClaim) -> ClaimFact:
    assert claim.id is not None
    return ClaimFact(
        id=claim.id, task_id=claim.task_id, role=claim.role, stage=claim.stage,
        state=claim.state, outcome=claim.outcome, claimed_at=claim.claimed_at,
        lease_expires_at=claim.lease_expires_at, agent_token_id=claim.agent_token_id,
        user_id=claim.user_id, progress_note=claim.progress_note,
    )


async def attempt_resets(session: AsyncSession, task_ids: Sequence[int]) -> dict[int, datetime]:
    """Per task, the last time a person said "retry with guidance" on a parking escalation."""
    if not task_ids:
        return {}
    rows = (
        await session.execute(
            select(Gate).where(
                col(Gate.task_id).in_(task_ids),
                Gate.decision == GateDecision.retry.value,
            )
        )
    ).scalars().all()
    out: dict[int, datetime] = {}
    for gate in rows:
        if gate.decided_at is not None:
            out[gate.task_id] = max(out.get(gate.task_id, gate.decided_at), gate.decided_at)
    return out


def stage_attempts(
    claims: Sequence[ClaimFact], reset: datetime | None, pipeline: Pipeline
) -> dict[str, int]:
    """Unfinished attempts per stage since the later of the last reset and the last time that
    stage's work was finished."""
    out: dict[str, int] = {}
    for stage in pipeline.stages:
        if not stage.is_agent_stage:
            continue
        finished = [
            c.claimed_at for c in claims
            if c.stage.casefold() == stage.key and c.outcome in (
                ClaimOutcome.advanced.value, ClaimOutcome.returned.value
            )
        ]
        since_candidates = [d for d in (reset, max(finished, default=None)) if d is not None]
        since = max(since_candidates) if since_candidates else None
        out[stage.key] = work_queue.unfinished_attempts(claims, stage.key, since)
    return out


@dataclass
class ProjectWork:
    project: Project
    pipeline: Pipeline
    tasks: list[Task]
    facts: dict[int, TaskFacts]
    claims: dict[int, list[ClaimFact]]
    wip_full: set[str]


async def load_project_work(
    session: AsyncSession, project: Project, *, task_ids: Sequence[int] | None = None
) -> ProjectWork:
    """The delegated leaf tasks of a project with everything readiness reads."""
    assert project.id is not None
    pipeline = await policy_service.resolve_pipeline(session, project)
    stmt = select(Task).where(
        Task.project_id == project.id,
        Task.type != TaskType.summary,
        Task.delegation == Delegation.agent.value,
    )
    if task_ids is not None:
        stmt = stmt.where(col(Task.id).in_(list(task_ids)))
    tasks = list((await session.execute(stmt.order_by(col(Task.id)))).scalars().all())
    ids = [t.id for t in tasks if t.id is not None]
    claims_by_task: dict[int, list[ClaimFact]] = {}
    gates_open: dict[int, int] = {}
    blockers_open: dict[int, int] = {}
    if ids:
        for claim in (
            await session.execute(select(WorkClaim).where(col(WorkClaim.task_id).in_(ids)))
        ).scalars().all():
            claims_by_task.setdefault(claim.task_id, []).append(claim_fact(claim))
        for gate in (
            await session.execute(
                select(Gate).where(
                    col(Gate.task_id).in_(ids), Gate.status == GateStatus.open.value
                )
            )
        ).scalars().all():
            gates_open[gate.task_id] = gates_open.get(gate.task_id, 0) + 1
        for blocker in (
            await session.execute(
                select(Blocker).where(
                    col(Blocker.task_id).in_(ids), col(Blocker.resolved_at).is_(None)
                )
            )
        ).scalars().all():
            blockers_open[blocker.task_id] = blockers_open.get(blocker.task_id, 0) + 1
    resets = await attempt_resets(session, ids)
    sprint_ids: set[int] | None = None
    delivery = await project_delivery(session, project)
    if delivery.uses_sprints:
        sprint_ids = {s.id for s in await active_sprints(session, delivery.team_id)
                      if s.id is not None}
    facts: dict[int, TaskFacts] = {}
    for task in tasks:
        assert task.id is not None
        claims = claims_by_task.get(task.id, [])
        active = next((c for c in claims if c.id == task.active_claim_id), None)
        facts[task.id] = TaskFacts(
            task_id=task.id,
            project_id=task.project_id,
            status=task.status,
            category=category_of_task(task),
            is_summary=task.type == TaskType.summary,
            delegated=task.delegation == Delegation.agent.value,
            assignee_engineer_id=task.assignee_engineer_id,
            rank=flow.effective_rank(task.board_rank, task.id),
            active_claim=active,
            open_gates=gates_open.get(task.id, 0),
            open_blockers=blockers_open.get(task.id, 0),
            in_active_sprint=None if sprint_ids is None else task.sprint_id in sprint_ids,
            stage_attempts=stage_attempts(claims, resets.get(task.id), pipeline),
        )
    wip_full: set[str] = set()
    view = await resolve_workflow(session, project)
    if view.wip_enforcement == "block":
        counts = await wip_counts(session, await wip_scope_project_ids(session, project, view))
        for column in view.columns:
            if column.wip_limit is not None and counts.get(column.name.casefold(), 0) >= (
                column.wip_limit
            ):
                wip_full.add(column.name.casefold())
    return ProjectWork(project=project, pipeline=pipeline, tasks=tasks, facts=facts,
                       claims=claims_by_task, wip_full=wip_full)


async def caller_facts(session: AsyncSession, caller: Caller, project: Project) -> CallerFacts:
    token = caller.token
    return CallerFacts(
        may_plan=await project_can_edit(session, caller.user, project),
        engineer_id=caller.engineer_id,
        roles_allowed=list(token.roles or []) if token is not None else [],
        project_ids_allowed=list(token.project_ids or []) if token is not None else [],
    )


async def readiness_of(
    session: AsyncSession,
    work: ProjectWork,
    task: Task,
    role: str,
    caller: CallerFacts,
    actor: ActorFact | None,
    now: datetime,
) -> Readiness:
    assert task.id is not None
    facts = work.facts[task.id]
    stage, pull = work_queue.locate(facts, work.pipeline, role)
    entry_failures: list[str] = []
    claim_failures: list[str] = []
    if stage is not None:
        ctx = await policy_service.evaluation_context(
            session, task, work.pipeline, actor="agent", current=actor
        )
        if pull:
            entry_failures = [r.check for r in stage_policy.evaluate(stage, ctx).failures]
        claim_failures = [
            r.check for r in stage_policy.evaluate(stage, ctx, phase="claim").failures
        ]
    return work_queue.readiness(
        facts, work.pipeline, role, intake=work.project.agent_intake, caller=caller, now=now,
        entry_failures=entry_failures, claim_failures=claim_failures, wip_full=work.wip_full,
    )


# --------------------------------------------------------------------------- #
# The queue
# --------------------------------------------------------------------------- #


@dataclass
class QueueItem:
    task: Task
    project: Project
    stage: str
    pull: bool
    order: tuple[int, int, int]


@dataclass
class QueueResult:
    ready: list[QueueItem] = field(default_factory=list)
    reasons: dict[str, int] = field(default_factory=dict)
    roles: list[str] = field(default_factory=list)


async def projects_for_repo(session: AsyncSession, repo: str) -> set[int]:
    """Projects with a component whose code binding names `repo` (owner/name), directly or
    through its connection's configured repository."""
    out: set[int] = set()
    wanted = repo.strip().casefold()
    bindings = (await session.execute(select(ComponentCodeBinding))).scalars().all()
    connections = {
        c.id: c for c in (await session.execute(select(Connection))).scalars().all()
    }
    for binding in bindings:
        name = binding.repo
        if not name and binding.connection_id in connections:
            config = connections[binding.connection_id].config or {}
            if config.get("owner") and config.get("repo"):
                name = f"{config['owner']}/{config['repo']}"
        if name and name.casefold() == wanted:
            component = await session.get(ArchitectureComponent, binding.component_id)
            if component is not None:
                out.add(component.project_id)
    return out


async def scoped_projects(
    session: AsyncSession,
    caller: Caller,
    *,
    project_id: int | None = None,
    team_id: int | None = None,
    repo: str | None = None,
) -> list[Project]:
    stmt = select(Project).where(col(Project.archived).is_(False))
    if project_id is not None:
        stmt = stmt.where(Project.id == project_id)
    projects = list((await session.execute(stmt.order_by(col(Project.id)))).scalars().all())
    if team_id is not None:
        from app.services.org import project_team_id

        projects = [p for p in projects if await project_team_id(session, p) == team_id]
    if repo:
        ids = await projects_for_repo(session, repo)
        projects = [p for p in projects if p.id in ids]
    token = caller.token
    if token is not None and token.project_ids:
        allowed = set(token.project_ids)
        projects = [p for p in projects if p.id in allowed]
    return projects


async def find_work(
    session: AsyncSession,
    caller: Caller,
    role: str,
    *,
    project_id: int | None = None,
    team_id: int | None = None,
    repo: str | None = None,
    now: datetime | None = None,
) -> QueueResult:
    """The ready tasks for `role`, best first, and why the rest of the delegated work isn't."""
    now = now or utcnow()
    result = QueueResult()
    for project in await scoped_projects(
        session, caller, project_id=project_id, team_id=team_id, repo=repo
    ):
        if project.agent_intake == AgentIntake.off.value:
            continue
        work = await load_project_work(session, project)
        for r in work.pipeline.roles():
            if r not in result.roles:
                result.roles.append(r)
        if not work.tasks:
            continue
        facts = await caller_facts(session, caller, project)
        for task in work.tasks:
            verdict = await readiness_of(
                session, work, task, role, facts, caller.actor_fact(), now
            )
            if verdict.ready and verdict.stage is not None:
                assert task.id is not None
                result.ready.append(
                    QueueItem(task=task, project=project, stage=verdict.stage, pull=verdict.pull,
                              order=work_queue.order_key(work.facts[task.id], verdict))
                )
            elif verdict.reason and verdict.reason != work_queue.REASON_NOT_IN_STAGE:
                result.reasons[verdict.reason] = result.reasons.get(verdict.reason, 0) + 1
    result.ready.sort(key=lambda item: item.order)
    return result


# --------------------------------------------------------------------------- #
# Claiming
# --------------------------------------------------------------------------- #


# `Task.active_claim_id` between reserving a task and inserting its claim — within one
# transaction, so no other session ever reads it.
RESERVED = -1


@dataclass
class AgentInfo:
    label: str | None = None
    runner: str | None = None
    session_ref: str | None = None


async def active_claims_of(session: AsyncSession, caller: Caller) -> list[WorkClaim]:
    """The live claims this caller's token holds (a person's own session: theirs without a
    token)."""
    stmt = select(WorkClaim).where(
        WorkClaim.state == ClaimState.active.value, WorkClaim.user_id == caller.user_id
    )
    if caller.token_id is not None:
        stmt = stmt.where(WorkClaim.agent_token_id == caller.token_id)
    else:
        stmt = stmt.where(col(WorkClaim.agent_token_id).is_(None))
    return list((await session.execute(stmt.order_by(col(WorkClaim.id)))).scalars().all())


def claim_limit(caller: Caller) -> int:
    return caller.token.max_active_claims if caller.token is not None else 1


async def _expire_if_lapsed(
    session: AsyncSession, task: Task, now: datetime
) -> bool:
    """When the task's claim has a lapsed lease, expire it (compare-and-swap) and clear the
    pointer. Returns True when the task is now free."""
    if task.active_claim_id is None:
        return True
    old = await session.get(WorkClaim, task.active_claim_id)
    if old is not None and old.state == ClaimState.active.value and old.lease_expires_at > now:
        return False
    if old is not None and old.state == ClaimState.active.value:
        changed = await session.execute(
            update(WorkClaim)
            .where(
                col(WorkClaim.id) == old.id,
                col(WorkClaim.state) == ClaimState.active.value,
                col(WorkClaim.lease_expires_at) < now,
            )
            .values(state=ClaimState.expired.value, outcome=ClaimOutcome.expired.value,
                    finished_at=now, end_reason="expired")
            .execution_options(synchronize_session=False)
        )
        if changed.rowcount == 1:  # type: ignore[attr-defined]
            await session.refresh(old)
            record_event(session, kind=WorkEventKind.claim_ended, project_id=task.project_id,
                         task_id=task.id, actor_kind=ActorKind.system.value, claim_id=old.id,
                         data={"outcome": ClaimOutcome.expired.value, "reason": "expired"})
    await session.execute(
        update(Task)
        .where(col(Task.id) == task.id, col(Task.active_claim_id) == task.active_claim_id)
        .values(active_claim_id=None)
        .execution_options(synchronize_session=False)
    )
    await session.refresh(task)
    if task.active_claim_id is not None:
        return False
    if old is not None and old.outcome == ClaimOutcome.expired.value:
        project = await session.get(Project, task.project_id)
        if project is not None:
            pipeline = await policy_service.resolve_pipeline(session, project)
            stage = pipeline.stage(old.stage)
            if stage is not None and await park_if_exhausted(session, task, stage):
                return False
    return True


async def _try_claim(
    session: AsyncSession,
    caller: Caller,
    task: Task,
    project: Project,
    stage: StageDef,
    pull: bool,
    *,
    role: str,
    agent: AgentInfo,
    idempotency_key: str,
    now: datetime,
) -> WorkClaim | None:
    """One compare-and-swap attempt on one task. None when another session got there first
    (or a pull would break a WIP limit).

    The task is reserved *before* the claim row is inserted: an INSERT's foreign-key check takes
    a shared lock on the task row, so inserting first lets two racing claims deadlock on MySQL
    (each holds the shared lock the other's UPDATE waits for). Reserving first, the loser's
    UPDATE simply waits for the winner's commit, then matches no row."""
    assert task.id is not None
    if not await _expire_if_lapsed(session, task, now):
        return None
    won = await session.execute(
        update(Task)
        .where(col(Task.id) == task.id, col(Task.active_claim_id).is_(None))
        .values(active_claim_id=RESERVED)
        .execution_options(synchronize_session=False)
    )
    if won.rowcount != 1:  # type: ignore[attr-defined]
        await session.refresh(task)
        return None
    attempts = (
        await session.execute(select(WorkClaim.attempt).where(WorkClaim.task_id == task.id))
    ).scalars().all()
    claim = WorkClaim(
        task_id=task.id,
        role=role,
        stage=stage.status_name,
        attempt=work_queue.next_attempt(attempts),
        state=ClaimState.active.value,
        user_id=caller.user_id,
        agent_token_id=caller.token_id,
        agent_label=(agent.label or (caller.token.label if caller.token else None)),
        runner=agent.runner,
        session_ref=agent.session_ref,
        idempotency_key=idempotency_key,
        claimed_at=now,
        heartbeat_at=now,
        lease_minutes=stage.lease_minutes,
        lease_expires_at=work_queue.lease_expiry(now, stage.lease_minutes),
    )
    session.add(claim)
    await session.flush()
    await session.execute(
        update(Task)
        .where(col(Task.id) == task.id, col(Task.active_claim_id) == RESERVED)
        .values(active_claim_id=claim.id)
        .execution_options(synchronize_session=False)
    )
    await session.refresh(task)
    if pull:
        try:
            await move_task(
                session, task, to_status=stage.status_name, author=caller.name,
                actor_kind=caller.actor_kind, work_claim_id=claim.id,
            )
        except TrackingError:
            await session.execute(
                update(Task)
                .where(col(Task.id) == task.id, col(Task.active_claim_id) == claim.id)
                .values(active_claim_id=None)
                .execution_options(synchronize_session=False)
            )
            await session.delete(claim)
            await session.flush()
            await session.refresh(task)
            return None
    if task.assignee_engineer_id is None and caller.engineer_id is not None:
        task.assignee_engineer_id = caller.engineer_id
    record_event(session, kind=WorkEventKind.claimed, project_id=project.id or task.project_id,
                 task_id=task.id, caller=caller, claim_id=claim.id,
                 data={"role": role, "stage": stage.status_name, "attempt": claim.attempt,
                       "pulled": pull})
    return claim


async def claim_work(
    session: AsyncSession,
    caller: Caller,
    role: str,
    *,
    task_id: int | None = None,
    project_id: int | None = None,
    team_id: int | None = None,
    repo: str | None = None,
    agent: AgentInfo | None = None,
    idempotency_key: str | None = None,
    now: datetime | None = None,
) -> WorkClaim | None:
    """Claim `task_id`, or the first ready task for `role`. Returns None when nothing is ready.
    A retried call (same idempotency key, or a token already at its claim limit asking for the
    same work) returns the claim it already holds. Raises WorkError."""
    now = now or utcnow()
    agent = agent or AgentInfo()
    role = role.strip().lower()
    if caller.token is not None and caller.token.roles and role not in caller.token.roles:
        raise WorkError("role_not_allowed", f"This token may not claim work as {role!r}", 403,
                        roles=list(caller.token.roles))
    if idempotency_key:
        existing = (
            await session.execute(
                select(WorkClaim).where(WorkClaim.idempotency_key == idempotency_key)
            )
        ).scalars().first()
        if existing is not None:
            if existing.user_id != caller.user_id:
                raise WorkError("idempotency_key_reused", "That key belongs to another claim",
                                409)
            return existing
    held = await active_claims_of(session, caller)
    if len(held) >= claim_limit(caller):
        mine = next((c for c in held if task_id is None or c.task_id == task_id), None)
        if mine is not None:
            return mine
        raise WorkError(
            "claim_limit",
            "This session already holds as many claims as its token allows — hand off, ask or "
            "release first",
            409,
            claim_ids=[c.id for c in held],
        )
    key = (idempotency_key or uuid.uuid4().hex)[:64]
    if task_id is not None:
        task = await session.get(Task, task_id)
        if task is None:
            raise WorkError("not_found", "Task not found", 404)
        project = await session.get(Project, task.project_id)
        if project is None:
            raise WorkError("not_found", "Project not found", 404)
        if task.delegation != Delegation.agent.value:
            raise WorkError("not_delegated", "Nobody has delegated this task to agents", 409)
        work = await load_project_work(session, project, task_ids=[task_id])
        verdict = await readiness_of(
            session, work, task, role, await caller_facts(session, caller, project),
            caller.actor_fact(), now,
        )
        if not verdict.ready:
            code = ("already_claimed" if verdict.reason == work_queue.REASON_CLAIMED
                    else "no_accountable_owner" if verdict.reason == work_queue.REASON_NO_OWNER
                    else "not_ready")
            raise WorkError(code, f"Task isn't ready for {role}: {verdict.reason}", 409,
                            reasons=[verdict.reason], detail_text=verdict.detail)
        stage = work.pipeline.stage(verdict.stage)
        assert stage is not None
        claim = await _try_claim(session, caller, task, project, stage, verdict.pull, role=role,
                                 agent=agent, idempotency_key=key, now=now)
        if claim is None:
            raise WorkError("already_claimed", "Another session claimed this task first", 409)
        return claim
    queue = await find_work(session, caller, role, project_id=project_id, team_id=team_id,
                            repo=repo, now=now)
    for item in queue.ready:
        pipeline = await policy_service.resolve_pipeline(session, item.project)
        stage = pipeline.stage(item.stage)
        if stage is None:
            continue
        claim = await _try_claim(session, caller, item.task, item.project, stage, item.pull,
                                 role=role, agent=agent, idempotency_key=key, now=now)
        if claim is not None:
            return claim
    return None


# --------------------------------------------------------------------------- #
# Fencing, heartbeats, ending claims
# --------------------------------------------------------------------------- #


async def get_claim(session: AsyncSession, claim_id: int) -> WorkClaim:
    claim = await session.get(WorkClaim, claim_id)
    if claim is None:
        raise WorkError("not_found", "Claim not found", 404)
    return claim


def ensure_holder(claim: WorkClaim, caller: Caller) -> None:
    """Only the session that made a claim (same person, same token) may act under it."""
    if claim.user_id != caller.user_id or claim.agent_token_id != caller.token_id:
        raise WorkError("not_claim_holder", "This claim belongs to another session", 403)


async def renew(session: AsyncSession, claim: WorkClaim, now: datetime | None = None) -> None:
    """Fence a claim-bound write: renew the lease if — and only if — the claim is still
    active. Zero rows changed is `409 claim_lost` and nothing else in the request happens."""
    now = now or utcnow()
    changed = await session.execute(
        update(WorkClaim)
        .where(col(WorkClaim.id) == claim.id, col(WorkClaim.state) == ClaimState.active.value)
        .values(
            heartbeat_at=now,
            lease_expires_at=work_queue.lease_expiry(now, claim.lease_minutes),
        )
        .execution_options(synchronize_session=False)
    )
    if changed.rowcount != 1:  # type: ignore[attr-defined]
        await session.refresh(claim)
        raise WorkError("claim_lost", "This claim is no longer active — stop work on this task",
                        409, state=claim.state, reason=claim.end_reason)
    await session.refresh(claim)


async def end_claim(
    session: AsyncSession,
    claim: WorkClaim,
    *,
    state: ClaimState,
    outcome: ClaimOutcome,
    reason: str | None = None,
    caller: Caller | None = None,
    usage: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> None:
    """Close a claim and release its task (the pointer is cleared only if it still names it)."""
    now = now or utcnow()
    claim.state = state.value
    claim.outcome = outcome.value
    claim.finished_at = now
    claim.end_reason = reason
    if usage:
        claim.usage = usage
    await session.execute(
        update(Task)
        .where(col(Task.id) == claim.task_id, col(Task.active_claim_id) == claim.id)
        .values(active_claim_id=None)
        .execution_options(synchronize_session=False)
    )
    task = await session.get(Task, claim.task_id)
    if task is not None:
        await session.refresh(task)
        record_event(session, kind=WorkEventKind.claim_ended, project_id=task.project_id,
                     task_id=task.id, caller=caller,
                     actor_kind=None if caller else ActorKind.system.value, claim_id=claim.id,
                     data={"outcome": outcome.value, "reason": reason})


async def supersede_claims(
    session: AsyncSession, task: Task, reason: str, caller: Caller | None = None
) -> int:
    """End every active claim on a task (a person took over, the task left the queue)."""
    claims = (
        await session.execute(
            select(WorkClaim).where(
                WorkClaim.task_id == task.id, WorkClaim.state == ClaimState.active.value
            )
        )
    ).scalars().all()
    for claim in claims:
        await end_claim(session, claim, state=ClaimState.superseded,
                        outcome=ClaimOutcome.superseded, reason=reason, caller=caller)
    return len(claims)


@dataclass
class Directive:
    directive: str  # continue | stop
    reason: str | None = None
    lease_expires_at: datetime | None = None
    heartbeat_interval_s: int = 300


async def heartbeat(
    session: AsyncSession,
    claim: WorkClaim,
    caller: Caller,
    *,
    note: str | None = None,
    steps: list[dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> Directive:
    """Renew the lease (and leave a progress note). A claim that is no longer active gets a
    `stop` directive with the reason rather than an error, so a runner can stop cleanly."""
    ensure_holder(claim, caller)
    now = now or utcnow()
    interval = work_queue.heartbeat_interval_s(claim.lease_minutes)
    task = await session.get(Task, claim.task_id)
    project = await session.get(Project, task.project_id) if task is not None else None
    if claim.state != ClaimState.active.value:
        return Directive("stop", claim.end_reason or claim.state, None, interval)
    if task is None or task.delegation != Delegation.agent.value:
        return Directive("stop", "undelegated", claim.lease_expires_at, interval)
    if project is not None and project.agent_intake == AgentIntake.off.value:
        return Directive("stop", "intake_off", claim.lease_expires_at, interval)
    if category_of_task(task) == flow.CANCELLED:
        return Directive("stop", "cancelled", claim.lease_expires_at, interval)
    try:
        await renew(session, claim, now)
    except WorkError:
        await session.refresh(claim)
        return Directive("stop", claim.end_reason or claim.state, None, interval)
    if note:
        claim.progress_note = note[:2000]
    if steps is not None:
        plan = await latest_artifact(session, claim.task_id, ArtifactKind.plan)
        if plan is not None:
            plan.data = {**(plan.data or {}), "steps": _clean_steps(steps)}
    return Directive("continue", None, claim.lease_expires_at, interval)


def _clean_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    allowed = {"pending", "in_progress", "completed", "canceled"}
    out: list[dict[str, Any]] = []
    for step in steps[:50]:
        content = str(step.get("content") or "").strip()[:300]
        if not content:
            continue
        status = str(step.get("status") or "pending")
        out.append({"content": content, "status": status if status in allowed else "pending"})
    return out


# --------------------------------------------------------------------------- #
# Artifacts
# --------------------------------------------------------------------------- #


async def latest_artifact(
    session: AsyncSession, task_id: int, kind: ArtifactKind
) -> TaskArtifact | None:
    return (
        await session.execute(
            select(TaskArtifact)
            .where(TaskArtifact.task_id == task_id, TaskArtifact.kind == kind.value)
            .order_by(col(TaskArtifact.revision).desc())
        )
    ).scalars().first()


async def add_artifact(
    session: AsyncSession,
    task: Task,
    kind: ArtifactKind,
    *,
    body: str,
    data: dict[str, Any] | None = None,
    title: str | None = None,
    caller: Caller | None = None,
    claim: WorkClaim | None = None,
    verdict: str | None = None,
    head_sha: str | None = None,
) -> TaskArtifact:
    assert task.id is not None
    previous = await latest_artifact(session, task.id, kind)
    artifact = TaskArtifact(
        task_id=task.id,
        kind=kind.value,
        revision=(previous.revision + 1) if previous is not None else 1,
        title=(title or "").strip()[:200] or None,
        body=body[:20000],
        data=data or {},
        verdict=verdict,
        head_sha=head_sha,
        author_kind=caller.actor_kind if caller else ActorKind.system.value,
        author_user_id=caller.user_id if caller else None,
        work_claim_id=claim.id if claim else None,
    )
    session.add(artifact)
    await session.flush()
    record_event(session, kind=WorkEventKind.artifact_added, project_id=task.project_id,
                 task_id=task.id, caller=caller, claim_id=claim.id if claim else None,
                 artifact_id=artifact.id,
                 data={"kind": kind.value, "revision": artifact.revision})
    return artifact


@dataclass
class GoverningDecision:
    adr_id: int
    number: int
    title: str
    status: str
    reversibility: str | None
    decision: str | None
    why: str
    fitness: list[dict[str, Any]]


async def components_for_paths(
    session: AsyncSession, project_id: int, paths: Sequence[str]
) -> list[int]:
    """Components whose code bindings match any of `paths` (glob match on `path_glob`)."""
    if not paths:
        return []
    comp_ids = (
        await session.execute(
            select(ArchitectureComponent.id).where(
                ArchitectureComponent.project_id == project_id
            )
        )
    ).scalars().all()
    if not comp_ids:
        return []
    bindings = (
        await session.execute(
            select(ComponentCodeBinding).where(
                col(ComponentCodeBinding.component_id).in_(list(comp_ids))
            )
        )
    ).scalars().all()
    out: list[int] = []
    for binding in bindings:
        pattern = binding.path_glob.strip()
        prefix = pattern.split("*", 1)[0]
        for path in paths:
            clean = path.strip().lstrip("./")
            if fnmatch.fnmatch(clean, pattern) or (prefix and clean.startswith(prefix)):
                if binding.component_id not in out:
                    out.append(binding.component_id)
                break
    return out


async def task_component_ids(session: AsyncSession, task_id: int) -> list[int]:
    return list(
        (
            await session.execute(
                select(TaskComponentLink.component_id).where(
                    TaskComponentLink.task_id == task_id
                )
            )
        ).scalars().all()
    )


async def decisions_for(
    session: AsyncSession, task: Task, component_ids: Sequence[int]
) -> tuple[list[GoverningDecision], list[GoverningDecision]]:
    """(binding, unsettled): accepted decisions that govern this work, and proposed /
    under-discussion ones on the same components. Superseded decisions give way to their
    successor."""
    from app.models.spec import Spec

    reasons: dict[int, str] = {}
    if task.implements_adr_id is not None:
        reasons[task.implements_adr_id] = "the task implements it"
    if task.spec_id is not None:
        spec = await session.get(Spec, task.spec_id)
        if spec is not None and spec.adr_id is not None:
            reasons.setdefault(spec.adr_id, "the task's spec names it")
    if component_ids:
        links = (
            await session.execute(
                select(ADRComponentLink).where(
                    col(ADRComponentLink.component_id).in_(list(component_ids))
                )
            )
        ).scalars().all()
        names = {
            c.id: c.name
            for c in (
                await session.execute(
                    select(ArchitectureComponent).where(
                        col(ArchitectureComponent.id).in_(list(component_ids))
                    )
                )
            ).scalars().all()
        }
        for link in links:
            reasons.setdefault(link.adr_id, f"governs component {names.get(link.component_id)}")
    binding: list[GoverningDecision] = []
    unsettled: list[GoverningDecision] = []
    seen: set[int] = set()
    for adr_id, why in reasons.items():
        adr = await session.get(ArchitectureDecision, adr_id)
        hops = 0
        while adr is not None and _status(adr) == "superseded" and hops < 10:
            successor = (
                await session.execute(
                    select(ArchitectureDecision).where(
                        ArchitectureDecision.supersedes_id == adr.id
                    )
                )
            ).scalars().first()
            if successor is None:
                break
            adr, hops = successor, hops + 1
        if adr is None or adr.id is None or adr.id in seen:
            continue
        seen.add(adr.id)
        status = _status(adr)
        fitness = [
            {"kind": f.kind, "source_component_id": f.source_component_id,
             "target_component_id": f.target_component_id, "description": f.description}
            for f in (
                await session.execute(
                    select(ADRFitnessFunction).where(ADRFitnessFunction.adr_id == adr.id)
                )
            ).scalars().all()
        ]
        item = GoverningDecision(
            adr_id=adr.id, number=adr.number, title=adr.title, status=status,
            reversibility=(adr.reversibility.value if adr.reversibility is not None else None),
            decision=(adr.decision or "")[:600] or None, why=why, fitness=fitness,
        )
        if status == "accepted":
            binding.append(item)
        elif status in ("proposed", "under_discussion"):
            unsettled.append(item)
    return binding, unsettled


def _status(adr: ArchitectureDecision) -> str:
    return str(adr.status.value if hasattr(adr.status, "value") else adr.status)


# --------------------------------------------------------------------------- #
# Plans, hand-offs, asking, releasing
# --------------------------------------------------------------------------- #


@dataclass
class PlanResult:
    artifact: TaskArtifact
    binding: list[GoverningDecision]
    unsettled: list[GoverningDecision]
    approval_required: bool = False
    reasons: list[str] = field(default_factory=list)
    gate: Gate | None = None


async def submit_plan(
    session: AsyncSession,
    claim: WorkClaim,
    caller: Caller,
    *,
    body: str,
    data: dict[str, Any],
    title: str | None = None,
) -> PlanResult:
    """Record a plan revision; answer with the decisions that govern the paths it touches and
    whether a person must approve it (the plan checkpoint, §9.3). A required approval opens a
    gate and ends the claim (`gated`)."""
    ensure_holder(claim, caller)
    await renew(session, claim)
    task = await session.get(Task, claim.task_id)
    assert task is not None and task.id is not None
    paths = [str(p) for p in data.get("affected_paths") or []][:200]
    from_paths = await components_for_paths(session, task.project_id, paths)
    declared = [int(c) for c in data.get("affected_component_ids") or []]
    component_ids = sorted({*await task_component_ids(session, task.id), *from_paths, *declared})
    binding, unsettled = await decisions_for(session, task, component_ids)
    data = {**data, "affected_paths": paths, "resolved_component_ids": component_ids}
    artifact = await add_artifact(session, task, ArtifactKind.plan, body=body, data=data,
                                  title=title, caller=caller, claim=claim)
    result = PlanResult(artifact=artifact, binding=binding, unsettled=unsettled)
    project = await session.get(Project, task.project_id)
    assert project is not None
    pipeline = await policy_service.resolve_pipeline(session, project)
    stage = pipeline.stage(claim.stage)
    checkpoint = stage.checkpoints.get("plan") if stage is not None else None
    if checkpoint is not None and stage is not None:
        from app.services import gates

        reasons = await gates.checkpoint_reasons(
            session, task, checkpoint.approval_when, artifact=artifact, component_ids=component_ids,
            binding=binding, unsettled=unsettled,
        )
        if reasons:
            artifact.data = {**artifact.data, "approval_required": True}
            result.approval_required = True
            result.reasons = reasons
            result.gate = await gates.open_gate(
                session, task, kind=GateKind.plan_approval, origin="checkpoint",
                stage=stage.status_name, title=f"Approve the plan for {task.key or task.name}",
                prompt=body[:4000], reasons=reasons, claim=claim, caller=caller,
                subject=artifact, decision=checkpoint.decision,
            )
            await end_claim(session, claim, state=ClaimState.completed,
                            outcome=ClaimOutcome.gated, reason="plan_approval", caller=caller)
    return result


@dataclass
class SubmitResult:
    claim: WorkClaim
    task: Task
    evaluation: dict[str, Any]
    moved_to: str | None = None
    gate: Gate | None = None
    warnings: list[str] = field(default_factory=list)


async def submit_work(
    session: AsyncSession,
    claim: WorkClaim,
    caller: Caller,
    *,
    kind: ArtifactKind,
    body: str,
    data: dict[str, Any],
    verdict: str | None = None,
    to_status: str | None = None,
    usage: dict[str, Any] | None = None,
) -> SubmitResult:
    """Hand off: save the artifact, evaluate the target column's entry checks, then advance,
    return for rework or open a gate — or refuse (`checks_failed`, the claim stays active and
    nothing is saved). The one function the dry run (`advance_check`) mirrors."""
    task = await session.get(Task, claim.task_id)
    assert task is not None and task.id is not None
    if claim.state != ClaimState.active.value and claim.outcome in (
        ClaimOutcome.advanced.value, ClaimOutcome.returned.value,
    ):
        return SubmitResult(claim=claim, task=task, evaluation={"replayed": True})
    ensure_holder(claim, caller)
    await renew(session, claim)
    project = await session.get(Project, task.project_id)
    assert project is not None
    pipeline = await policy_service.resolve_pipeline(session, project)
    stage = pipeline.stage(claim.stage) or pipeline.stage(task.status)
    if stage is None:
        raise WorkError("stage_missing", "The task's column no longer exists", 409)
    # The claim's role decides what it may hand off (§18.2): a reviewer session submits a
    # review, never code; an implementer a hand-off, never its own verdict.
    if kind.value != stage.hands_off:
        verb = "submit_work" if stage.hands_off == "handoff" else "submit_review"
        raise WorkError(
            "wrong_artifact",
            f"{stage.status_name} is worked as {claim.role}: it hands off a "
            f"{stage.hands_off.replace('_', ' ')} ({verb})",
            409, expected=stage.hands_off,
        )
    plan_checkpoint = stage.checkpoints.get("plan")
    # Any plan on the task counts: a rework round revises it if it needs to, rather than
    # re-planning (and re-asking for approval) every round.
    if (
        kind == ArtifactKind.handoff and plan_checkpoint is not None and plan_checkpoint.required
        and await latest_artifact(session, task.id, ArtifactKind.plan) is None
    ):
        raise WorkError("plan_missing",
                        f"{stage.status_name} requires a plan before the hand-off — "
                        "submit_plan first", 409)
    from app.services import gates

    pr = await policy_service.latest_pull_request(session, task.id)
    head = data.get("head_sha") or (pr.head_sha if pr is not None else None)
    artifact = await add_artifact(session, task, kind, body=body, data=data, caller=caller,
                                  claim=claim, verdict=verdict, head_sha=head)
    returning = kind in (ArtifactKind.review, ArtifactKind.qa_report) and verdict == "fail"
    evaluation: dict[str, Any]
    if returning:
        target = pipeline.rework_target(stage)
        if target is None:
            raise WorkError("no_rework_target", "There is no earlier column to send this back to",
                            409)
        evaluation = {"target": target.status_name, "allowed": True, "failures": [],
                      "warnings": [], "results": []}
    else:
        if to_status is not None:
            target_or_none = pipeline.stage(to_status)
            if target_or_none is None:
                raise WorkError("unknown_status", f"{to_status!r} is not a column", 422)
            target = target_or_none
        else:
            next_stage = pipeline.next_after(stage)
            if next_stage is None:
                raise WorkError("no_next_stage", "There is no column after this one", 409)
            target = next_stage
        rules = await gates.attestation_facts(session, task, stage, data)
        ctx = await policy_service.evaluation_context(
            session, task, pipeline, actor="agent", current=caller.actor_fact(),
            extra_rules=rules,
        )
        result = stage_policy.evaluate(target, ctx)
        evaluation = result.to_dict()
        if not result.allowed:
            raise WorkError("checks_failed", "The hand-off doesn't meet the next column's checks",
                            409, evaluation=evaluation)
        checkpoint = stage.checkpoints.get("handoff")
        if checkpoint is not None:
            reasons = await gates.checkpoint_reasons(
                session, task, checkpoint.approval_when, artifact=artifact,
            )
            if reasons:
                gate = await gates.open_gate(
                    session, task, kind=GateKind.handoff_approval, origin="checkpoint",
                    stage=stage.status_name,
                    title=f"Approve the hand-off of {task.key or task.name}",
                    prompt=body[:4000], reasons=reasons, claim=claim, caller=caller,
                    subject=artifact, decision=checkpoint.decision, evidence=evaluation,
                    on_approve=target.status_name,
                )
                record_event(session, kind=WorkEventKind.checks_evaluated,
                             project_id=task.project_id, task_id=task.id, caller=caller,
                             claim_id=claim.id, data=evaluation)
                await end_claim(session, claim, state=ClaimState.completed,
                                outcome=ClaimOutcome.gated, reason="handoff_approval",
                                caller=caller, usage=usage)
                return SubmitResult(claim=claim, task=task, evaluation=evaluation, gate=gate)
    record_event(session, kind=WorkEventKind.checks_evaluated, project_id=task.project_id,
                 task_id=task.id, caller=caller, claim_id=claim.id, data=evaluation)
    rework_exhausted = False
    if returning:
        rework = await gates.rework_rounds(session, task, target.status_name)
        rework_exhausted = rework + 1 > target.max_rework
    try:
        await move_task(session, task, to_status=target.status_name, author=caller.name,
                        actor_kind=caller.actor_kind, work_claim_id=claim.id)
    except TrackingError as exc:
        raise WorkError(exc.code, exc.message, exc.status_code, **exc.extra) from exc
    record_event(
        session,
        kind=WorkEventKind.returned if returning else WorkEventKind.advanced,
        project_id=task.project_id, task_id=task.id, caller=caller, claim_id=claim.id,
        artifact_id=artifact.id,
        data={"from": stage.status_name, "to": target.status_name, "stage": target.status_name,
              "verdict": verdict},
    )
    await end_claim(session, claim, state=ClaimState.completed,
                    outcome=ClaimOutcome.returned if returning else ClaimOutcome.advanced,
                    reason="handed_off", caller=caller, usage=usage)
    out = SubmitResult(claim=claim, task=task, evaluation=evaluation,
                       moved_to=target.status_name,
                       warnings=[w["check"] for w in evaluation.get("warnings", [])])
    if rework_exhausted:
        out.gate = await gates.open_gate(
            session, task, kind=GateKind.escalation, origin="system", stage=target.status_name,
            title=f"The review loop on {task.key or task.name} is not converging",
            prompt=(
                f"{task.key or task.name} has been sent back to {target.status_name} more than "
                f"{target.max_rework} times. Give guidance and retry, take it over, or cancel it."
            ),
            reasons=[f"Returned for rework more than {target.max_rework} times"],
        )
    elif target.is_decision_column:
        out.gate = await gates.open_column_gate(session, task, target, caller=caller,
                                                claim=claim, evidence=evaluation)
    return out


async def ask_human(
    session: AsyncSession,
    claim: WorkClaim,
    caller: Caller,
    *,
    kind: GateKind,
    title: str,
    prompt: str,
    options: list[dict[str, str]] | None = None,
    allow_text: bool = True,
) -> Gate:
    """The agent needs an answer (`question`) or says it should not proceed (`escalation`).
    The claim ends (`gated`); the task is held until a person responds."""
    ensure_holder(claim, caller)
    await renew(session, claim)
    task = await session.get(Task, claim.task_id)
    assert task is not None
    from app.services import gates

    gate = await gates.open_gate(
        session, task, kind=kind, origin="agent", stage=claim.stage, title=title, prompt=prompt,
        options=options or [], allow_text=allow_text, claim=claim, caller=caller,
    )
    await end_claim(session, claim, state=ClaimState.completed, outcome=ClaimOutcome.gated,
                    reason=kind.value, caller=caller)
    return gate


async def release_work(
    session: AsyncSession,
    claim: WorkClaim,
    caller: Caller,
    *,
    reason: str,
    note: str | None = None,
    needs_human: bool = False,
    as_planner: bool = False,
) -> Gate | None:
    """Give the task back (a note for the next session), or — with `needs_human` — say a person
    is needed: the attempt is `failed` and an escalation gate opens. A planner may release
    another session's claim (`as_planner`)."""
    if not as_planner:
        ensure_holder(claim, caller)
    if claim.state != ClaimState.active.value:
        raise WorkError("claim_lost", "This claim is no longer active", 409, state=claim.state)
    task = await session.get(Task, claim.task_id)
    assert task is not None
    if note:
        claim.progress_note = note[:2000]
    state, outcome = (
        (ClaimState.failed, ClaimOutcome.failed) if needs_human
        else (ClaimState.released, ClaimOutcome.released)
    )
    await end_claim(session, claim, state=state, outcome=outcome,
                    reason="released_by_planner" if as_planner else reason[:120], caller=caller)
    from app.services import gates

    if needs_human:
        return await gates.open_gate(
            session, task, kind=GateKind.escalation, origin="agent", stage=claim.stage,
            title=f"A person is needed on {task.key or task.name}",
            prompt=(note or reason)[:4000], claim=claim, caller=caller,
        )
    project = await session.get(Project, task.project_id)
    if project is not None:
        pipeline = await policy_service.resolve_pipeline(session, project)
        stage = pipeline.stage(claim.stage)
        if stage is not None:
            await park_if_exhausted(session, task, stage)
    return None


async def park_if_exhausted(session: AsyncSession, task: Task, stage: StageDef) -> Gate | None:
    """After an unfinished attempt: when the stage's attempts are used up, open an escalation
    gate ("N sessions did not finish this") with each attempt's last progress note."""
    assert task.id is not None
    open_gate_exists = (
        await session.execute(
            select(Gate.id).where(Gate.task_id == task.id, Gate.status == GateStatus.open.value)
        )
    ).scalars().first()
    if open_gate_exists is not None:
        return None
    project = await session.get(Project, task.project_id)
    assert project is not None
    work = await load_project_work(session, project, task_ids=[task.id])
    facts = work.facts.get(task.id)
    if facts is None or facts.stage_attempts.get(stage.key, 0) < stage.max_attempts:
        return None
    attempts = [c for c in work.claims.get(task.id, []) if c.stage.casefold() == stage.key
                and c.outcome in work_queue.UNFINISHED_OUTCOMES]
    lines = [
        f"- Attempt {c.id} ({c.outcome}): {c.progress_note or 'no progress note'}"
        for c in sorted(attempts, key=lambda c: c.claimed_at)[-stage.max_attempts:]
    ]
    from app.services import gates

    return await gates.open_gate(
        session, task, kind=GateKind.escalation, origin="system", stage=stage.status_name,
        title=f"{stage.max_attempts} sessions did not finish {task.key or task.name}",
        prompt="The last attempts:\n" + "\n".join(lines)
        + "\n\nGive guidance and retry, take it over, or cancel it.",
        reasons=[f"{stage.max_attempts} attempts in {stage.status_name} ended unfinished"],
    )


async def reap_expired(session: AsyncSession, now: datetime | None = None) -> int:
    """Expire every lapsed claim (the cron job, every few minutes). Commits."""
    now = now or utcnow()
    lapsed = (
        await session.execute(
            select(WorkClaim).where(
                WorkClaim.state == ClaimState.active.value,
                col(WorkClaim.lease_expires_at) < now,
            )
        )
    ).scalars().all()
    count = 0
    projects: set[int] = set()
    for claim in lapsed:
        task = await session.get(Task, claim.task_id)
        if task is None:
            continue
        if task.active_claim_id != claim.id:
            # An orphan (its task already moved on): just close it.
            await end_claim(session, claim, state=ClaimState.expired,
                            outcome=ClaimOutcome.expired, reason="expired", now=now)
            count += 1
            continue
        if await _expire_if_lapsed(session, task, now) or task.active_claim_id is None:
            count += 1
            projects.add(task.project_id)
    await session.commit()
    for project_id in projects:
        await notify(project_id)
    return count


# --------------------------------------------------------------------------- #
# Delegation, intake, take-over, components
# --------------------------------------------------------------------------- #


def keep_for_people_tags() -> set[str]:
    return {t.strip().lower() for t in settings.WORK_KEEP_FOR_PEOPLE_TAGS.split(",") if t.strip()}


async def readiness_hints(session: AsyncSession, task: Task) -> list[str]:
    """Why a task may be a poor candidate for an agent (§6.1) — advice, not a block."""
    assert task.id is not None
    hints: list[str] = []
    if not (task.description or "").strip():
        hints.append("It has no description — say what done looks like.")
    if task.spec_id is None:
        hints.append("It implements no spec, so it has no acceptance criteria.")
    else:
        from app.models.spec import SpecCriterion

        count = (
            await session.execute(
                select(SpecCriterion.id).where(SpecCriterion.spec_id == task.spec_id)
            )
        ).scalars().all()
        if not count:
            hints.append("Its spec has no acceptance criteria.")
    if task.duration > settings.WORK_SMALL_BATCH_DAYS:
        hints.append(
            f"It is sized at {task.duration} days — above the {settings.WORK_SMALL_BATCH_DAYS}-day "
            "small-batch threshold; consider splitting it."
        )
    if not await task_component_ids(session, task.id):
        hints.append("It names no architecture component, so the brief can't find the "
                     "decisions that govern it.")
    flagged = sorted({t.lower() for t in (task.tags or [])} & keep_for_people_tags())
    if flagged:
        hints.append(f"It is tagged {', '.join(flagged)} — work a person usually keeps.")
    return hints


async def set_delegation(
    session: AsyncSession, task: Task, caller: Caller, delegation: str | None
) -> list[str]:
    """Delegate a task to agents (or take it back). Taking it back ends active claims and
    closes its open gates. Returns readiness hints when delegating."""
    assert task.id is not None
    if task.type == TaskType.summary:
        raise WorkError("not_a_leaf", "Phases (summary tasks) can't be delegated", 422)
    if delegation is not None and task.status_owner != CANOPY_OWNER:
        raise WorkError(
            "status_externally_owned",
            "This task's status belongs to its tracker; delegating mirrored work arrives with "
            "mirrored-project support",
            409,
            provider=task.status_owner,
        )
    if delegation is not None and delegation != Delegation.agent.value:
        raise WorkError("bad_delegation", "delegation must be 'agent' or null", 422)
    previous = task.delegation
    task.delegation = delegation
    task.delegated_by_user_id = caller.user_id if delegation else None
    task.delegated_at = utcnow() if delegation else None
    hints: list[str] = []
    if delegation:
        hints = await readiness_hints(session, task)
    else:
        await supersede_claims(session, task, "undelegated", caller)
        from app.services import gates

        await gates.close_open_gates(session, task, reason="undelegated", caller=caller)
    if previous != delegation:
        record_event(session, kind=WorkEventKind.delegated, project_id=task.project_id,
                     task_id=task.id, caller=caller, data={"delegation": delegation})
    return hints


async def set_intake(
    session: AsyncSession, project: Project, caller: Caller, state: str
) -> int:
    """Switch a project's intake. `off` is the kill switch: active claims are superseded and
    told to stop at their next heartbeat. Returns how many claims were stopped."""
    assert project.id is not None
    try:
        value = AgentIntake(state).value
    except ValueError as exc:
        raise WorkError("bad_intake", "intake must be off | on | paused", 422) from exc
    stopped = 0
    if value == AgentIntake.off.value:
        tasks = (
            await session.execute(
                select(Task).where(
                    Task.project_id == project.id, col(Task.active_claim_id).is_not(None)
                )
            )
        ).scalars().all()
        for task in tasks:
            stopped += await supersede_claims(session, task, "intake_off", caller)
    if project.agent_intake != value:
        record_event(session, kind=WorkEventKind.intake_changed, project_id=project.id,
                     task_id=None, caller=caller,
                     data={"from": project.agent_intake, "to": value, "stopped": stopped})
    project.agent_intake = value
    return stopped


async def take_over(session: AsyncSession, task: Task, caller: Caller) -> None:
    """A person takes the task back from the queue: undelegated, claims superseded, open gates
    closed. The task stays where it is."""
    assert task.id is not None
    await supersede_claims(session, task, "taken_over", caller)
    from app.services import gates

    await gates.close_open_gates(session, task, reason="taken_over", caller=caller)
    if task.delegation is not None:
        task.delegation = None
        task.delegated_by_user_id = None
        task.delegated_at = None
        record_event(session, kind=WorkEventKind.delegated, project_id=task.project_id,
                     task_id=task.id, caller=caller,
                     data={"delegation": None, "taken_over": True})


async def check_person_move(
    session: AsyncSession,
    task: Task,
    caller: Caller,
    to_status: str,
    *,
    override_reason: str | None = None,
    may_override: bool = False,
) -> list[str]:
    """A person is about to move a delegated card (§9.2, D4): evaluate the target column's
    entry checks. People are warned, not stopped — the warnings join the move response — except
    by a check marked `everyone` + `block`, which refuses the move (`checks_failed`) unless a
    planner passes it with an `override_reason`, recorded as an `override` event. Projects with
    intake off, and tasks nobody delegated, are untouched."""
    if task.delegation != Delegation.agent.value:
        return []
    project = await session.get(Project, task.project_id)
    if project is None or project.agent_intake == AgentIntake.off.value:
        return []
    pipeline = await policy_service.resolve_pipeline(session, project)
    target = pipeline.stage(to_status)
    if target is None or (task.status or "").casefold() == target.key:
        return []
    ctx = await policy_service.evaluation_context(
        session, task, pipeline, actor="human", current=caller.actor_fact()
    )
    result = stage_policy.evaluate(target, ctx)
    warnings = [f"{w.label}: {w.message}" for w in result.warnings]
    if result.failures:
        reason = (override_reason or "").strip()
        if not (may_override and reason):
            raise WorkError(
                "checks_failed",
                f"{target.status_name} requires checks this card doesn't meet"
                + (" — a planner may override with a reason" if may_override else ""),
                409, evaluation=result.to_dict(), overridable=may_override,
            )
        record_event(session, kind=WorkEventKind.override, project_id=task.project_id,
                     task_id=task.id, caller=caller,
                     data={"to": target.status_name, "reason": reason[:500],
                           "failures": [f.check for f in result.failures]})
        warnings += [f"Overridden — {f.label}: {f.message}" for f in result.failures]
    return warnings


async def on_person_move(session: AsyncSession, task: Task, caller: Caller) -> None:
    """A person changed a delegated card's status: the board follows reality, so the running
    claim ends (its session is told to stop at its next call) and gates that held the task in
    its old column close."""
    await supersede_claims(session, task, "moved_by_person", caller)
    from app.services import gates

    await gates.close_open_gates(session, task, reason="moved_by_person", caller=caller,
                                 unless_stage=task.status)


async def set_components(
    session: AsyncSession, task: Task, component_ids: Sequence[int], caller: Caller
) -> list[int]:
    assert task.id is not None
    wanted = sorted({int(c) for c in component_ids})
    if wanted:
        found = set(
            (
                await session.execute(
                    select(ArchitectureComponent.id).where(
                        col(ArchitectureComponent.id).in_(wanted),
                        ArchitectureComponent.project_id == task.project_id,
                    )
                )
            ).scalars().all()
        )
        missing = [c for c in wanted if c not in found]
        if missing:
            raise WorkError("unknown_component",
                            f"Not components of this task's project: {missing}", 422)
    existing = (
        await session.execute(select(TaskComponentLink).where(TaskComponentLink.task_id == task.id))
    ).scalars().all()
    for link in existing:
        if link.component_id not in wanted:
            await session.delete(link)
    have = {link.component_id for link in existing}
    for cid in wanted:
        if cid not in have:
            session.add(TaskComponentLink(task_id=task.id, component_id=cid))
    record_event(session, kind=WorkEventKind.components_changed, project_id=task.project_id,
                 task_id=task.id, caller=caller, data={"component_ids": wanted})
    return wanted


def lease_window(claim: WorkClaim) -> timedelta:
    return timedelta(minutes=claim.lease_minutes)
