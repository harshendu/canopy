"""Stage policy, database side — docs/AGENT_EXECUTION.md §9, §12.

Resolves a project's **pipeline** (its board columns, each with its stage definition) and loads
the facts the pure `stage_policy.evaluate` reads for one task. The pipeline follows the
workflow's own resolution (project override → team → workspace template → built-in default,
§C9.1): stored policies at the scope the columns come from apply; with none, the built-in
default does (the first in-progress column is the implementer's stage).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.models.base import ArtifactKind, ClaimOutcome, GateKind, GateStatus, WorkEventKind
from app.models.gate import Gate
from app.models.integration import PullRequest
from app.models.project import Blocker, Dependency, Project, Task
from app.models.spec import Spec, SpecCriterion
from app.models.team import Engineer
from app.models.work import TaskArtifact, WorkClaim, WorkEvent
from app.services import flow, stage_policy
from app.services.stage_policy import (
    ActorFact,
    ArtifactFact,
    EvalContext,
    Pipeline,
    PullRequestFact,
)
from app.services.workflow import WorkflowView, category_of_task, resolve_workflow


async def stored_policies(
    session: AsyncSession, view: WorkflowView, project: Project
) -> dict[str, dict[str, Any]]:
    """The stored policy documents for the columns `view` describes, keyed by column name.
    (Stage policies are stored from Phase 2; until then every pipeline is the default.)"""
    loader = _POLICY_LOADER
    if loader is None:
        return {}
    loaded: dict[str, dict[str, Any]] = await loader(session, view, project)
    return loaded


# Phase 2 registers the stored-policy loader here (kept as a hook so this module has no import
# of the policy table before it exists).
_POLICY_LOADER: Any = None


def register_policy_loader(loader: Any) -> None:
    global _POLICY_LOADER
    _POLICY_LOADER = loader


async def resolve_pipeline(session: AsyncSession, project: Project) -> Pipeline:
    view = await resolve_workflow(session, project)
    policies = await stored_policies(session, view, project)
    return stage_policy.pipeline_from_policies(view.columns, policies)


def _started(task: Task) -> bool:
    return category_of_task(task) in (flow.IN_PROGRESS, flow.DONE)


async def dependencies_done(session: AsyncSession, task: Task) -> bool:
    """Finish-to-start predecessors are done; start-to-start ones have started."""
    deps = (
        await session.execute(select(Dependency).where(Dependency.successor_id == task.id))
    ).scalars().all()
    for dep in deps:
        pred = await session.get(Task, dep.predecessor_id)
        if pred is None:
            continue
        kind = str(dep.type.value if hasattr(dep.type, "value") else dep.type)
        if kind == "FS" and category_of_task(pred) not in (flow.DONE, flow.CANCELLED):
            return False
        if kind == "SS" and not _started(pred):
            return False
    return True


async def latest_pull_request(session: AsyncSession, task_id: int) -> PullRequest | None:
    rows = (
        await session.execute(
            select(PullRequest)
            .where(PullRequest.task_id == task_id)
            .order_by(col(PullRequest.updated_at).desc(), col(PullRequest.id).desc())
        )
    ).scalars().all()
    open_rows = [r for r in rows if r.state == "open" or r.merged]
    if open_rows:
        return open_rows[0]
    return rows[0] if rows else None


def pr_fact(pr: PullRequest | None) -> PullRequestFact | None:
    if pr is None:
        return None
    lines = None
    if pr.additions is not None or pr.deletions is not None:
        lines = int(pr.additions or 0) + int(pr.deletions or 0)
    return PullRequestFact(
        state=pr.state,
        merged=bool(pr.merged),
        head_sha=pr.head_sha,
        checks_state=pr.checks_state,
        approved_by=list(pr.approved_by or []),
        changed_lines=lines,
    )


async def round_started_at(session: AsyncSession, task_id: int) -> Any:
    """When the current round of work began: the last return for rework (None = the first)."""
    return (
        await session.execute(
            select(WorkEvent.at)
            .where(WorkEvent.task_id == task_id, WorkEvent.kind == WorkEventKind.returned.value)
            .order_by(col(WorkEvent.at).desc())
        )
    ).scalars().first()


async def stage_actors(
    session: AsyncSession, task_id: int, pipeline: Pipeline
) -> dict[str, ActorFact]:
    """Per role, the session that last finished that role's work on this task."""
    claims = (
        await session.execute(
            select(WorkClaim)
            .where(
                WorkClaim.task_id == task_id,
                WorkClaim.outcome == ClaimOutcome.advanced.value,
            )
            .order_by(col(WorkClaim.id))
        )
    ).scalars().all()
    out: dict[str, ActorFact] = {}
    for claim in claims:
        out[claim.role] = ActorFact(agent_token_id=claim.agent_token_id, user_id=claim.user_id)
    return out


async def github_logins(session: AsyncSession, user_ids: set[int]) -> frozenset[str]:
    if not user_ids:
        return frozenset()
    rows = (
        await session.execute(
            select(Engineer.github_login).where(col(Engineer.user_id).in_(user_ids))
        )
    ).scalars().all()
    return frozenset(r for r in rows if r)


async def evaluation_context(
    session: AsyncSession,
    task: Task,
    pipeline: Pipeline,
    *,
    actor: str,
    current: ActorFact | None = None,
    extra_rules: tuple[list[str], dict[str, str]] | None = None,
) -> EvalContext:
    """Everything `stage_policy.evaluate` reads about `task` right now."""
    assert task.id is not None
    blockers = (
        await session.execute(
            select(Blocker.id).where(
                Blocker.task_id == task.id, col(Blocker.resolved_at).is_(None)
            )
        )
    ).scalars().all()
    spec_status: str | None = None
    criteria: list[str] = []
    if task.spec_id is not None:
        spec = await session.get(Spec, task.spec_id)
        if spec is not None:
            spec_status = str(spec.status.value if hasattr(spec.status, "value") else spec.status)
            criteria = [
                str(c.status.value if hasattr(c.status, "value") else c.status)
                for c in (
                    await session.execute(
                        select(SpecCriterion).where(SpecCriterion.spec_id == spec.id)
                    )
                ).scalars().all()
            ]
    artifacts = (
        await session.execute(select(TaskArtifact).where(TaskArtifact.task_id == task.id))
    ).scalars().all()
    started = await round_started_at(session, task.id)
    gates = (
        await session.execute(select(Gate).where(Gate.task_id == task.id))
    ).scalars().all()
    approved_plan: int | None = None
    plan_needed = False
    latest_plan = max(
        (a for a in artifacts if a.kind == ArtifactKind.plan.value),
        key=lambda a: a.revision,
        default=None,
    )
    approved_kinds: set[str] = set()
    for gate in gates:
        approved = gate.status == GateStatus.approved.value
        in_round = started is None or (gate.decided_at is not None and gate.decided_at >= started)
        if approved and in_round:
            approved_kinds.add(gate.kind)
        if gate.kind == GateKind.plan_approval.value and gate.subject_artifact_id is not None:
            subject = next((a for a in artifacts if a.id == gate.subject_artifact_id), None)
            if subject is not None and latest_plan is not None and subject.id == latest_plan.id:
                plan_needed = True
                if approved:
                    approved_plan = subject.revision
    if latest_plan is not None and (latest_plan.data or {}).get("approval_required"):
        plan_needed = True
    actors = await stage_actors(session, task.id, pipeline)
    requester_ids = {a.user_id for a in actors.values() if a.user_id is not None}
    rules_required, attested = extra_rules if extra_rules is not None else ([], {})
    return EvalContext(
        actor=actor,
        dependencies_done=await dependencies_done(session, task),
        open_blockers=len(blockers),
        spec_status=spec_status,
        criteria=criteria,
        artifacts=[
            ArtifactFact(
                kind=a.kind, revision=a.revision, created_at=a.created_at, verdict=a.verdict,
                head_sha=a.head_sha, data=a.data or {},
            )
            for a in artifacts
        ],
        round_started_at=started,
        approved_plan_revision=approved_plan,
        plan_approval_required=plan_needed,
        approved_gate_kinds=frozenset(approved_kinds),
        pull_request=pr_fact(await latest_pull_request(session, task.id)),
        requester_logins=await github_logins(session, requester_ids),
        rules_required=rules_required,
        attested=attested,
        current=current,
        stage_actors=actors,
    )
