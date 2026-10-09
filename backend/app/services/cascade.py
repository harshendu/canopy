"""FK-safe cascading deletes for a Task or a Project.

Postgres and MySQL **enforce** foreign keys; SQLite (dev/CI) does not by default. A bare
``session.delete(obj)`` therefore raises an ``IntegrityError`` (→ HTTP 500) in production for any
non-empty entity, while silently *orphaning* the referencing rows on SQLite — so tests pass and
prod breaks. These helpers clear every FK-referencing row in child→parent order first (the same
strategy as the demo ``clear_all_data``), so the delete is safe on all three dialects.

The ordering is verified against a fully-populated project under SQLite FK enforcement
(``tests/test_cascade_delete.py`` sets ``PRAGMA foreign_keys=ON``), which reproduces the
Postgres/MySQL behaviour and fails loudly if a referencing table is missed.
"""

from __future__ import annotations

from sqlalchemy import delete, or_, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.models.activity import ActivityEvent
from app.models.architecture import (
    ADRComment,
    ADRComponentLink,
    ADRFitnessFunction,
    ADRStakeholder,
    ArchitectureComponent,
    ArchitectureDecision,
    ComponentCodeBinding,
    ComponentLink,
    DriftEvent,
    DriftScan,
    DriftSuppression,
)
from app.models.base import DocScope, LeadershipScope, ProposalScope, RiskScope
from app.models.doc import DocReference
from app.models.draft import DraftPlan, DraftTask
from app.models.integration import ExternalRef, JiraLink, PullRequest
from app.models.leadership import LeadershipNote
from app.models.outcome import Outcome
from app.models.project import (
    Baseline,
    Blocker,
    Dependency,
    Holiday,
    Milestone,
    Project,
    RiskMitigation,
    RiskSnapshot,
    Task,
    TaskStatusHistory,
)
from app.models.proposal import Proposal, ProposalItem
from app.models.retro import Retrospective, RetrospectiveComment
from app.models.risk_register import RiskItem
from app.models.scenario import (
    ScenarioAllocation,
    ScenarioDependency,
    ScenarioMilestone,
    ScenarioProject,
    ScenarioTask,
)
from app.models.spec import Spec, SpecCriterion
from app.models.team import Allocation


async def delete_task_cascade(session: AsyncSession, task_id: int) -> None:
    """Delete one task and every row that FK-references it, so the delete is safe under enforced
    foreign keys. Child tasks are **promoted** to the deleted task's parent (hierarchy preserved);
    the caller commits."""
    task = await session.get(Task, task_id)
    if task is None:
        return
    # Promote children to the deleted node's parent (never leave a dangling parent_id).
    await session.execute(
        update(Task).where(col(Task.parent_id) == task_id).values(parent_id=task.parent_id)
    )
    # Nullable references from rows that outlive the task → SET NULL (keep the referrer).
    await session.execute(
        update(PullRequest).where(col(PullRequest.task_id) == task_id).values(task_id=None)
    )
    await session.execute(
        update(ScenarioTask)
        .where(col(ScenarioTask.live_task_id) == task_id)
        .values(live_task_id=None)
    )
    await session.execute(
        update(Blocker)
        .where(col(Blocker.blocking_task_id) == task_id)
        .values(blocking_task_id=None)
    )
    await session.execute(
        update(Allocation).where(col(Allocation.task_id) == task_id).values(task_id=None)
    )
    # Rows that only exist because of this task → delete.
    await session.execute(
        delete(Dependency).where(
            or_(col(Dependency.predecessor_id) == task_id, col(Dependency.successor_id) == task_id)
        )
    )
    await session.execute(delete(Blocker).where(col(Blocker.task_id) == task_id))
    await session.execute(
        delete(TaskStatusHistory).where(col(TaskStatusHistory.task_id) == task_id)
    )
    await session.execute(
        delete(RiskItem).where(
            col(RiskItem.scope_level) == RiskScope.task, col(RiskItem.scope_id) == task_id
        )
    )
    await session.execute(
        delete(DocReference).where(
            col(DocReference.scope_level) == DocScope.task, col(DocReference.scope_id) == task_id
        )
    )
    await session.execute(
        delete(ExternalRef).where(
            col(ExternalRef.entity_type) == "task", col(ExternalRef.entity_id) == task_id
        )
    )
    await session.delete(task)


async def delete_project_cascade(session: AsyncSession, project_id: int) -> None:
    """Delete a project and its entire object graph in FK-safe order (tasks, schedule, decisions,
    architecture, governance, drafts, scenarios that referenced it, and the polymorphic
    risk/doc/outcome/proposal rows scoped to it). The caller commits."""
    pid = project_id
    # Scoping subqueries (evaluated by the DB inside each statement — no id materialization).
    task_ids = select(col(Task.id)).where(col(Task.project_id) == pid)
    comp_ids = select(col(ArchitectureComponent.id)).where(
        col(ArchitectureComponent.project_id) == pid
    )
    adr_ids = select(col(ArchitectureDecision.id)).where(
        col(ArchitectureDecision.project_id) == pid
    )
    spec_ids = select(col(Spec.id)).where(col(Spec.project_id) == pid)
    retro_ids = select(col(Retrospective.id)).where(col(Retrospective.project_id) == pid)
    plan_ids = select(col(DraftPlan.id)).where(col(DraftPlan.project_id) == pid)
    prop_ids = select(col(Proposal.id)).where(
        col(Proposal.scope_level) == ProposalScope.project, col(Proposal.scope_id) == pid
    )
    stask_ids = select(col(ScenarioTask.id)).where(col(ScenarioTask.project_id) == pid)
    mile_ids = select(col(Milestone.id)).where(col(Milestone.project_id) == pid)
    dep_ids = select(col(Dependency.id)).where(
        or_(
            col(Dependency.predecessor_id).in_(task_ids),
            col(Dependency.successor_id).in_(task_ids),
        )
    )
    alloc_ids = select(col(Allocation.id)).where(
        or_(col(Allocation.project_id) == pid, col(Allocation.task_id).in_(task_ids))
    )

    # 1) Break self-references and cross-project references that would block the deletes below.
    await session.execute(
        update(Task).where(col(Task.project_id) == pid).values(parent_id=None)
    )
    await session.execute(
        update(ScenarioTask).where(col(ScenarioTask.project_id) == pid).values(parent_id=None)
    )
    await session.execute(
        update(DraftTask).where(col(DraftTask.plan_id).in_(plan_ids)).values(parent_id=None)
    )
    await session.execute(
        update(ArchitectureDecision)
        .where(col(ArchitectureDecision.supersedes_id).in_(adr_ids))
        .values(supersedes_id=None)
    )
    # References from rows in *other* projects/scenarios → SET NULL (keep those referrers).
    await session.execute(
        update(PullRequest).where(col(PullRequest.task_id).in_(task_ids)).values(task_id=None)
    )
    await session.execute(
        update(Blocker)
        .where(col(Blocker.blocking_task_id).in_(task_ids))
        .values(blocking_task_id=None)
    )
    await session.execute(
        update(Spec).where(col(Spec.adr_id).in_(adr_ids)).values(adr_id=None)
    )
    # A task (possibly in another project) may implement one of this project's specs — clear the
    # link so specs can be deleted regardless of the task-vs-spec delete order.
    await session.execute(
        update(Task).where(col(Task.spec_id).in_(spec_ids)).values(spec_id=None)
    )
    await session.execute(
        update(ActivityEvent)
        .where(col(ActivityEvent.component_id).in_(comp_ids))
        .values(component_id=None)
    )
    await session.execute(
        update(ScenarioTask)
        .where(col(ScenarioTask.live_task_id).in_(task_ids))
        .values(live_task_id=None)
    )
    await session.execute(
        update(ScenarioDependency)
        .where(col(ScenarioDependency.live_dep_id).in_(dep_ids))
        .values(live_dep_id=None)
    )
    await session.execute(
        update(ScenarioMilestone)
        .where(col(ScenarioMilestone.live_milestone_id).in_(mile_ids))
        .values(live_milestone_id=None)
    )
    await session.execute(
        delete(LeadershipNote).where(
            col(LeadershipNote.scope_level) == LeadershipScope.project,
            col(LeadershipNote.scope_id) == pid,
        )
    )
    await session.execute(
        update(ScenarioAllocation)
        .where(col(ScenarioAllocation.live_allocation_id).in_(alloc_ids))
        .values(live_allocation_id=None)
    )

    # 2) Delete grandchildren → children → the project row, each before what it references.
    stmts = [
        # architecture sub-tables
        delete(ADRComment).where(col(ADRComment.adr_id).in_(adr_ids)),
        delete(ADRStakeholder).where(col(ADRStakeholder.adr_id).in_(adr_ids)),
        delete(ADRComponentLink).where(col(ADRComponentLink.adr_id).in_(adr_ids)),
        delete(ADRFitnessFunction).where(col(ADRFitnessFunction.adr_id).in_(adr_ids)),
        delete(ComponentLink).where(
            or_(
                col(ComponentLink.source_id).in_(comp_ids),
                col(ComponentLink.target_id).in_(comp_ids),
            )
        ),
        delete(ComponentCodeBinding).where(col(ComponentCodeBinding.component_id).in_(comp_ids)),
        # governance sub-tables
        delete(SpecCriterion).where(col(SpecCriterion.spec_id).in_(spec_ids)),
        delete(RetrospectiveComment).where(
            col(RetrospectiveComment.retrospective_id).in_(retro_ids)
        ),
        delete(ProposalItem).where(col(ProposalItem.proposal_id).in_(prop_ids)),
        delete(DraftTask).where(col(DraftTask.plan_id).in_(plan_ids)),
        # scenario rows that snapshot this (now-deleted) live project
        delete(ScenarioDependency).where(
            or_(
                col(ScenarioDependency.predecessor_id).in_(stask_ids),
                col(ScenarioDependency.successor_id).in_(stask_ids),
            )
        ),
        delete(ScenarioAllocation).where(col(ScenarioAllocation.project_id) == pid),
        delete(ScenarioMilestone).where(col(ScenarioMilestone.project_id) == pid),
        delete(ScenarioTask).where(col(ScenarioTask.project_id) == pid),
        delete(ScenarioProject).where(col(ScenarioProject.project_id) == pid),
        # task-derived rows
        delete(TaskStatusHistory).where(col(TaskStatusHistory.task_id).in_(task_ids)),
        delete(Dependency).where(
            or_(
                col(Dependency.predecessor_id).in_(task_ids),
                col(Dependency.successor_id).in_(task_ids),
            )
        ),
        delete(Blocker).where(col(Blocker.task_id).in_(task_ids)),
        delete(Allocation).where(
            or_(col(Allocation.project_id) == pid, col(Allocation.task_id).in_(task_ids))
        ),
        # polymorphic (scope_level/scope_id) rows for this project + its tasks
        delete(RiskItem).where(
            or_(
                (col(RiskItem.scope_level) == RiskScope.project)
                & (col(RiskItem.scope_id) == pid),
                (col(RiskItem.scope_level) == RiskScope.task)
                & col(RiskItem.scope_id).in_(task_ids),
            )
        ),
        delete(DocReference).where(
            or_(
                (col(DocReference.scope_level) == DocScope.project)
                & (col(DocReference.scope_id) == pid),
                (col(DocReference.scope_level) == DocScope.task)
                & col(DocReference.scope_id).in_(task_ids),
            )
        ),
        delete(Outcome).where(
            col(Outcome.scope_level) == "project", col(Outcome.scope_id) == pid
        ),
        delete(Proposal).where(col(Proposal.id).in_(prop_ids)),
        # project-direct children
        delete(RiskMitigation).where(col(RiskMitigation.project_id) == pid),
        delete(RiskSnapshot).where(col(RiskSnapshot.project_id) == pid),
        delete(Baseline).where(col(Baseline.project_id) == pid),
        delete(Milestone).where(col(Milestone.project_id) == pid),
        delete(Holiday).where(col(Holiday.project_id) == pid),
        delete(DriftEvent).where(col(DriftEvent.project_id) == pid),
        delete(DriftSuppression).where(col(DriftSuppression.project_id) == pid),
        delete(DriftScan).where(col(DriftScan.project_id) == pid),
        delete(ActivityEvent).where(col(ActivityEvent.project_id) == pid),
        delete(Spec).where(col(Spec.project_id) == pid),
        delete(Retrospective).where(col(Retrospective.project_id) == pid),
        delete(DraftPlan).where(col(DraftPlan.project_id) == pid),
        delete(Task).where(col(Task.project_id) == pid),
        delete(ArchitectureDecision).where(col(ArchitectureDecision.project_id) == pid),
        delete(ArchitectureComponent).where(col(ArchitectureComponent.project_id) == pid),
        # idempotency/hygiene mappings (polymorphic, not FK-enforced) — clear so a re-created
        # project/key doesn't collide with stale external refs.
        delete(ExternalRef).where(
            or_(
                (col(ExternalRef.entity_type) == "project") & (col(ExternalRef.entity_id) == pid),
                (col(ExternalRef.entity_type) == "task") & col(ExternalRef.entity_id).in_(task_ids),
                (col(ExternalRef.entity_type) == "adr")
                & col(ExternalRef.entity_id).in_(adr_ids),
                (col(ExternalRef.entity_type) == "component")
                & col(ExternalRef.entity_id).in_(comp_ids),
                (col(ExternalRef.entity_type) == "milestone")
                & col(ExternalRef.entity_id).in_(mile_ids),
            )
        ),
        delete(JiraLink).where(
            col(JiraLink.target_type) == "project", col(JiraLink.target_id) == pid
        ),
    ]
    for stmt in stmts:
        await session.execute(stmt)

    project = await session.get(Project, pid)
    if project is not None:
        await session.delete(project)
