"""Turns the declarative demo catalog into a coherent set of rows, and resets it.

Everything routes through the ORM session so the data is identical across SQLite / Postgres /
MySQL. Projects are scheduled with the real CPM planner so the Gantt, critical path, baselines
and variance are genuine; status history / activity / risk snapshots are back-dated so the
time-series views (burndown, forecast, delivery metrics, risk timeline) have real trends.

Builders are generic — they read the per-project spec fields — so every project is fully
populated (architecture, ADRs, specs, risks, outcomes, docs, blockers, retros, activity).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from itertools import pairwise
from typing import TypeVar

from sqlalchemy import delete, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel, select

from app.core.crypto import encrypt_token
from app.core.security import hash_password
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
)
from app.models.base import (
    ADRCommentKind,
    ADRStatus,
    BlockerCategory,
    BlockerSeverity,
    CriterionStatus,
    DocKind,
    DocScope,
    DocSource,
    OutcomeScope,
    OutcomeStatus,
    ProjectHealth,
    Provider,
    RetrospectiveKind,
    Reversibility,
    RiskCategory,
    RiskGrade,
    RiskScope,
    RiskStatus,
    SpecStatus,
    TaskType,
    utcnow,
)
from app.models.doc import DocReference
from app.models.draft import DraftPlan, DraftTask
from app.models.integration import Connection, ExternalRef, JiraLink, PullRequest
from app.models.outcome import Outcome
from app.models.project import (
    Baseline,
    Blocker,
    Dependency,
    Holiday,
    Initiative,
    Milestone,
    Project,
    RiskMitigation,
    RiskSnapshot,
    Task,
    TaskStatusHistory,
)
from app.models.retro import Retrospective, RetrospectiveComment
from app.models.risk_register import RiskItem
from app.models.scenario import (
    Scenario,
    ScenarioDependency,
    ScenarioProject,
    ScenarioTask,
)
from app.models.spec import Spec, SpecCriterion
from app.models.team import Allocation, Engineer, EngineerAvailability, Role
from app.models.user import User
from app.services.planner import reschedule_project
from app.services.seed import catalog
from app.services.seed.catalog import (
    ALLOCATIONS,
    AVAILABILITY,
    CROSS_PROJECT_HANDOFFS,
    ENGINEERS,
    FLAGSHIP_KEY,
    INITIATIVES,
    PROJECTS,
    SCENARIOS,
    TEAM_ROLES,
    USERS,
    ProjectSpec,
)

M = TypeVar("M", bound=SQLModel)

_DONE = "Done"
_PERCENT = {"To Do": 0.0, "In Progress": 40.0, "In Review": 75.0, "Done": 100.0}


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
async def _add(session: AsyncSession, obj: M) -> M:
    session.add(obj)
    await session.flush()
    return obj


def _req(value: int | None) -> int:
    assert value is not None
    return value


def _today() -> date:
    return date.today()


def _weeks(base: date, n: int) -> date:
    return base + timedelta(weeks=n)


def _risk_level(score: int) -> str:
    if score >= 75:
        return "critical"
    if score >= 50:
        return "high"
    if score >= 30:
        return "moderate"
    return "low"


def _lifecycle(status: str, entered_days_ago: int) -> tuple[int, list[tuple[str | None, str, int]]]:
    """(created_days_ago, status transitions as (from, to, days_ago)) for a leaf's history."""
    if status == "In Progress":
        return entered_days_ago + 8, [("To Do", "In Progress", entered_days_ago)]
    if status == "In Review":
        return entered_days_ago + 12, [
            ("To Do", "In Progress", entered_days_ago + 6),
            ("In Progress", "In Review", entered_days_ago),
        ]
    if status == _DONE:
        return entered_days_ago + 16, [
            ("To Do", "In Progress", entered_days_ago + 12),
            ("In Progress", "In Review", entered_days_ago + 4),
            ("In Review", _DONE, entered_days_ago),
        ]
    return 5, []  # To Do: created recently, no history yet


# --------------------------------------------------------------------------- #
# Reset
# --------------------------------------------------------------------------- #
async def clear_all_data(session: AsyncSession, keep_user_ids: set[int]) -> None:
    """Wipe every domain table. Users are removed too (full reset) except `keep_user_ids`
    (the acting admin + the configured superuser) so the operator stays logged in."""
    for stmt in (
        update(Task).values(parent_id=None),
        update(DraftTask).values(parent_id=None),
        update(ArchitectureDecision).values(supersedes_id=None),
        update(ScenarioTask).values(parent_id=None),
    ):
        await session.execute(stmt)
    await session.flush()

    for table in reversed(SQLModel.metadata.sorted_tables):
        if table.name == User.__tablename__ and keep_user_ids:
            await session.execute(delete(table).where(table.c.id.notin_(keep_user_ids)))
        else:
            await session.execute(delete(table))
    await session.commit()


# --------------------------------------------------------------------------- #
# References threaded through the build
# --------------------------------------------------------------------------- #
@dataclass
class _Refs:
    users: dict[str, User] = field(default_factory=dict)
    engineers: dict[str, Engineer] = field(default_factory=dict)
    roles: dict[str, Role] = field(default_factory=dict)
    initiatives: dict[str, Initiative] = field(default_factory=dict)
    projects: dict[str, Project] = field(default_factory=dict)
    tasks: dict[str, dict[str, Task]] = field(default_factory=dict)  # project_key -> name -> Task
    leaf_order: dict[str, list[Task]] = field(default_factory=dict)  # project_key -> leaves

    def eng(self, name: str | None) -> int | None:
        if name is None:
            return None
        engineer = self.engineers.get(name)
        return engineer.id if engineer else None


# --------------------------------------------------------------------------- #
# People + initiatives
# --------------------------------------------------------------------------- #
async def _build_users(session: AsyncSession, refs: _Refs) -> None:
    existing = {u.email: u for u in (await session.execute(select(User))).scalars().all()}
    for spec in USERS:
        if spec.email in existing:
            refs.users[spec.email] = existing[spec.email]
            continue
        refs.users[spec.email] = await _add(session, User(
            email=spec.email, hashed_password=hash_password(catalog.DEMO_PASSWORD),
            full_name=spec.full_name, role=spec.role, function=spec.function,
        ))


async def _build_team(session: AsyncSession, refs: _Refs) -> None:
    for name in TEAM_ROLES:
        refs.roles[name] = await _add(session, Role(name=name))
    for spec in ENGINEERS:
        user = refs.users.get(spec.user_email) if spec.user_email else None
        refs.engineers[spec.name] = await _add(session, Engineer(
            name=spec.name, email=spec.user_email, title=spec.title,
            role_id=refs.roles[spec.role_name].id, user_id=user.id if user else None,
            skill_tags=list(spec.skill_tags), github_login=spec.github_login,
            timezone=spec.timezone, committed_hours_per_week=spec.committed_hours_per_week,
        ))
    today = _today()
    for av in AVAILABILITY:
        eng_id = refs.eng(av.engineer)
        if eng_id is None:
            continue
        await _add(session, EngineerAvailability(
            engineer_id=eng_id, start_date=_weeks(today, av.start_weeks),
            end_date=_weeks(today, av.end_weeks), capacity_factor=av.capacity_factor,
            note=av.note,
        ))


async def _build_initiatives(session: AsyncSession, refs: _Refs) -> None:
    today = _today()
    for spec in INITIATIVES:
        init = await _add(session, Initiative(
            key=spec.key, name=spec.name, outcome_statement=spec.outcome_statement,
            start_date=_weeks(today, -10), target_date=_weeks(today, spec.target_weeks_ahead),
            owner_engineer_id=refs.eng(spec.owner_engineer), tags=list(spec.tags),
            health=ProjectHealth(spec.health) if spec.health else None,
            status_note=spec.status_note, status_updated_at=utcnow(),
        ))
        refs.initiatives[spec.key] = init
    await _build_initiative_extras(session, refs)


async def _build_initiative_extras(session: AsyncSession, refs: _Refs) -> None:
    today = _today()
    for spec in INITIATIVES:
        init = refs.initiatives[spec.key]
        iid = _req(init.id)
        for o in spec.outcomes:
            await _add(session, Outcome(
                scope_level=OutcomeScope.initiative, scope_id=iid, statement=o.statement,
                metric=o.metric, unit=o.unit, baseline_value=o.baseline, target_value=o.target,
                current_value=o.current, status=OutcomeStatus(o.status),
                target_date=_weeks(today, o.target_weeks), owner_engineer_id=refs.eng(o.owner),
            ))
        for r in spec.risks:
            await _add(session, RiskItem(
                scope_level=RiskScope.initiative, scope_id=iid, title=r.title,
                category=RiskCategory(r.category), probability=RiskGrade(r.probability),
                impact=RiskGrade(r.impact), status=RiskStatus(r.status),
                owner_engineer_id=refs.eng(r.owner), mitigation=r.mitigation,
                contingency=r.contingency,
                target_resolution_date=_weeks(today, r.target_weeks) if r.target_weeks else None,
            ))
        for d in spec.docs:
            await _add(session, DocReference(
                scope_level=DocScope.initiative, scope_id=iid, kind=DocKind(d.kind),
                title=d.title, url=d.url, source=DocSource(d.source),
            ))


# --------------------------------------------------------------------------- #
# Projects — schedule + per-project rich content
# --------------------------------------------------------------------------- #
async def _build_projects(session: AsyncSession, refs: _Refs) -> None:
    for spec in PROJECTS:
        await _build_one_project(session, refs, spec)

    # Cross-project hand-offs within an initiative (drive the cross-project critical path).
    for (pk_pred, t_pred), (pk_succ, t_succ) in CROSS_PROJECT_HANDOFFS:
        pred = refs.tasks[pk_pred].get(t_pred)
        succ = refs.tasks[pk_succ].get(t_succ)
        if pred is not None and succ is not None:
            await _add(session, Dependency(
                predecessor_id=_req(pred.id), successor_id=_req(succ.id)))

    await _baseline_flagship(session, refs)


async def _build_one_project(session: AsyncSession, refs: _Refs, spec: ProjectSpec) -> None:
    today = _today()
    init = refs.initiatives.get(spec.initiative_key) if spec.initiative_key else None
    project = await _add(session, Project(
        key=spec.key, name=spec.name, description=spec.description,
        initiative_id=init.id if init else None,
        start_date=_weeks(today, -spec.start_weeks_ago),
        target_date=_weeks(today, spec.target_weeks_ahead), skip_weekends=spec.skip_weekends,
        tags=list(spec.tags), health=ProjectHealth(spec.health) if spec.health else None,
        status_note=spec.status_note, status_updated_at=utcnow(),
    ))
    pid = _req(project.id)
    refs.projects[spec.key] = project
    refs.tasks[spec.key] = {}
    leaves: list[Task] = []

    for phase in spec.phases:
        summary = await _add(session, Task(
            project_id=pid, name=phase.name, type=TaskType.summary, duration=0))
        for ts in phase.tasks:
            task = await _add(session, Task(
                project_id=pid, parent_id=summary.id, name=ts.name,
                type=TaskType.milestone if ts.milestone else TaskType.task, duration=ts.duration,
                tags=list(ts.tags), assignee_engineer_id=refs.eng(ts.assignee),
                estimate_optimistic=ts.estimate[0] if ts.estimate else None,
                estimate_likely=ts.estimate[1] if ts.estimate else None,
                estimate_pessimistic=ts.estimate[2] if ts.estimate else None,
                deadline=_weeks(today, ts.deadline_weeks) if ts.deadline_weeks else None,
            ))
            refs.tasks[spec.key][ts.name] = task
            leaves.append(task)

    for prev, nxt in pairwise(leaves):
        await _add(session, Dependency(
            predecessor_id=_req(prev.id), successor_id=_req(nxt.id)))
    refs.leaf_order[spec.key] = leaves

    for ms in spec.milestones:
        await _add(session, Milestone(
            project_id=pid, name=ms.name, target_date=_weeks(today, ms.target_weeks),
            status=ms.status))
    if spec.skip_weekends:
        await _add(session, Holiday(project_id=pid, day=_weeks(today, 3), name="Company holiday"))

    await reschedule_project(session, pid)
    await _apply_lifecycle(session, refs, spec)

    comps = await _build_project_arch(session, refs, spec, pid)
    adrs = await _build_project_adrs(session, refs, spec, pid, comps)
    await _build_project_drift(session, spec, pid, comps)
    await _build_project_specs(session, refs, spec, pid, adrs)
    await _build_project_risk(session, refs, spec, pid)
    await _build_project_outcomes(session, refs, spec, pid)
    await _build_project_docs(session, refs, spec, pid)
    await _build_project_blockers(session, refs, spec)
    await _build_project_retro(session, refs, spec, pid, comps)
    await _build_project_draft(session, spec, pid)
    await _build_project_activity(session, spec, pid, comps)


async def _apply_lifecycle(session: AsyncSession, refs: _Refs, spec: ProjectSpec) -> None:
    base = utcnow()
    for phase in spec.phases:
        for ts in phase.tasks:
            if ts.milestone:
                continue
            task = refs.tasks[spec.key][ts.name]
            created_days, transitions = _lifecycle(ts.status, ts.entered_days_ago)
            task.created_at = base - timedelta(days=created_days)
            task.status = ts.status
            task.percent_complete = _PERCENT.get(ts.status, 0.0)
            author = ts.assignee or "Jira Sync"
            for from_status, to_status, days_ago in transitions:
                await _add(session, TaskStatusHistory(
                    task_id=task.id, from_status=from_status, to_status=to_status,
                    changed_at=base - timedelta(days=days_ago), author=author,
                ))


async def _build_project_arch(
    session: AsyncSession, refs: _Refs, spec: ProjectSpec, pid: int
) -> dict[str, ArchitectureComponent]:
    comps: dict[str, ArchitectureComponent] = {}
    for c in spec.components:
        comps[c.name] = await _add(session, ArchitectureComponent(
            project_id=pid, name=c.name, kind=c.kind, tier=c.tier, criticality=c.criticality,
            owner_engineer_id=refs.eng(c.owner),
            description=f"The {c.name} component.",
        ))
    for link in spec.component_links:
        if link.source in comps and link.target in comps:
            await _add(session, ComponentLink(
                source_id=_req(comps[link.source].id), target_id=_req(comps[link.target].id),
                kind=link.kind))
    for b in spec.bindings:
        if b.component in comps:
            await _add(session, ComponentCodeBinding(
                component_id=_req(comps[b.component].id), path_glob=b.path_glob,
                module_prefix=b.module_prefix))
    return comps


async def _build_project_adrs(
    session: AsyncSession, refs: _Refs, spec: ProjectSpec, pid: int,
    comps: dict[str, ArchitectureComponent],
) -> dict[str, ArchitectureDecision]:
    base = utcnow()
    today = _today()
    adrs: dict[str, ArchitectureDecision] = {}
    for i, a in enumerate(spec.adrs, start=1):
        adr = await _add(session, ArchitectureDecision(
            project_id=pid, number=i, title=a.title, status=ADRStatus(a.status),
            reversibility=Reversibility(a.reversibility) if a.reversibility else None,
            context=a.context, decision=a.decision, consequences=a.consequences,
            alternatives=list(a.alternatives), decision_owner_id=refs.eng(a.owner),
            proposed_by_id=refs.eng(a.proposer),
            decide_by=_weeks(today, a.decide_by_weeks) if a.decide_by_weeks is not None else None,
            created_at=base - timedelta(days=a.created_days_ago),
        ))
        adrs[a.title] = adr
        for comp_name in a.components:
            if comp_name in comps:
                await _add(session, ADRComponentLink(
                    adr_id=_req(adr.id), component_id=_req(comps[comp_name].id)))
        for sh in a.stakeholders:
            eng_id = refs.eng(sh)
            if eng_id is not None:
                await _add(session, ADRStakeholder(adr_id=_req(adr.id), engineer_id=eng_id))
        for c in a.comments:
            await _add(session, ADRComment(
                adr_id=_req(adr.id), engineer_id=refs.eng(c.author), author_name=c.author,
                body=c.body, kind=ADRCommentKind(c.kind)))
        if a.fitness and a.fitness.source in comps and a.fitness.target in comps:
            await _add(session, ADRFitnessFunction(
                adr_id=_req(adr.id), kind=a.fitness.kind,
                source_component_id=_req(comps[a.fitness.source].id),
                target_component_id=_req(comps[a.fitness.target].id),
                description=a.fitness.description))
    return adrs


async def _build_project_drift(
    session: AsyncSession, spec: ProjectSpec, pid: int, comps: dict[str, ArchitectureComponent]
) -> None:
    if not spec.drift:
        return
    for n, d in enumerate(spec.drift):
        ids = [_req(comps[c].id) for c in d.components if c in comps]
        await _add(session, DriftEvent(
            project_id=pid, kind=d.kind, rule_key=f"{spec.key.lower()}:{d.kind}:{n}",
            summary=d.summary, detail=d.detail, suspected_cause=d.suspected_cause,
            affected_component_ids=ids, status=d.status))
    await _add(session, DriftScan(project_id=pid, finding_count=len(spec.drift)))


async def _build_project_specs(
    session: AsyncSession, refs: _Refs, spec: ProjectSpec, pid: int,
    adrs: dict[str, ArchitectureDecision],
) -> None:
    for s in spec.specs:
        adr = adrs.get(s.adr_title) if s.adr_title else None
        spec_row = await _add(session, Spec(
            project_id=pid, title=s.title, problem=s.problem, context=s.context,
            out_of_scope=s.out_of_scope, status=SpecStatus(s.status),
            owner_engineer_id=refs.eng(s.owner), adr_id=adr.id if adr else None,
            source_url=s.source_url))
        for i, c in enumerate(s.criteria):
            await _add(session, SpecCriterion(
                spec_id=spec_row.id, text=c.text, status=CriterionStatus(c.status),
                verification=c.verification, sort_order=i))
        for tname in s.task_names:
            task = refs.tasks[spec.key].get(tname)
            if task is not None:
                task.spec_id = spec_row.id
        await session.flush()


async def _build_project_risk(
    session: AsyncSession, refs: _Refs, spec: ProjectSpec, pid: int
) -> None:
    today = _today()
    for r in spec.risks:
        await _add(session, RiskItem(
            scope_level=RiskScope.project, scope_id=pid, title=r.title,
            category=RiskCategory(r.category), probability=RiskGrade(r.probability),
            impact=RiskGrade(r.impact), status=RiskStatus(r.status),
            owner_engineer_id=refs.eng(r.owner), mitigation=r.mitigation,
            contingency=r.contingency,
            target_resolution_date=_weeks(today, r.target_weeks) if r.target_weeks else None,
        ))
    for m in spec.mitigations:
        await _add(session, RiskMitigation(
            project_id=pid, indicator_key=m.indicator_key, note=m.note,
            owner_engineer_id=refs.eng(m.owner), resolved=m.resolved,
            check_in=_weeks(today, m.check_in_weeks) if m.check_in_weeks is not None else None,
        ))
    # Weekly risk snapshots so the timeline trends (higher band for at-risk projects).
    base = utcnow()
    high = spec.health == "at_risk"
    scores = [70, 66, 62, 59, 56, 53] if high else [52, 49, 46, 44, 41, 38]
    for weeks_ago, score in enumerate(reversed(scores)):
        await _add(session, RiskSnapshot(
            project_id=pid, score=score, level=_risk_level(score),
            created_at=base - timedelta(weeks=weeks_ago)))


async def _build_project_outcomes(
    session: AsyncSession, refs: _Refs, spec: ProjectSpec, pid: int
) -> None:
    today = _today()
    for o in spec.outcomes:
        await _add(session, Outcome(
            scope_level=OutcomeScope.project, scope_id=pid, statement=o.statement,
            metric=o.metric, unit=o.unit, baseline_value=o.baseline, target_value=o.target,
            current_value=o.current, status=OutcomeStatus(o.status),
            target_date=_weeks(today, o.target_weeks), owner_engineer_id=refs.eng(o.owner)))


async def _build_project_docs(
    session: AsyncSession, refs: _Refs, spec: ProjectSpec, pid: int
) -> None:
    for d in spec.docs:
        scope_level = DocScope.project
        scope_id = pid
        if d.task_name:
            task = refs.tasks[spec.key].get(d.task_name)
            if task is not None:
                scope_level, scope_id = DocScope.task, _req(task.id)
        await _add(session, DocReference(
            scope_level=scope_level, scope_id=scope_id, kind=DocKind(d.kind), title=d.title,
            url=d.url, source=DocSource(d.source)))


async def _build_project_blockers(
    session: AsyncSession, refs: _Refs, spec: ProjectSpec
) -> None:
    base = utcnow()
    today = _today()
    for b in spec.blockers:
        task = refs.tasks[spec.key].get(b.task_name)
        if task is None:
            continue
        await _add(session, Blocker(
            task_id=_req(task.id), reason=b.reason, category=BlockerCategory(b.category),
            severity=BlockerSeverity(b.severity), owner_engineer_id=refs.eng(b.owner),
            raised_by_engineer_id=refs.eng(b.raised_by),
            needed_by=_weeks(today, b.needed_weeks) if b.needed_weeks is not None else None,
            created_at=base - timedelta(days=b.created_days_ago),
            resolved_at=(base - timedelta(days=max(b.created_days_ago - 6, 1)))
            if b.resolved else None,
        ))


async def _build_project_retro(
    session: AsyncSession, refs: _Refs, spec: ProjectSpec, pid: int,
    comps: dict[str, ArchitectureComponent],
) -> None:
    if spec.retro is None:
        return
    r = spec.retro
    ids = [_req(comps[c].id) for c in r.components if c in comps]
    retro = await _add(session, Retrospective(
        project_id=pid, title=r.title, kind=RetrospectiveKind(r.kind), body=r.body,
        status="open", affected_component_ids=ids))
    for c in r.comments:
        await _add(session, RetrospectiveComment(
            retrospective_id=retro.id, engineer_id=refs.eng(c.author), author_name=c.author,
            body=c.body))


async def _build_project_draft(session: AsyncSession, spec: ProjectSpec, pid: int) -> None:
    if spec.draft is None:
        return
    d = spec.draft
    plan = await _add(session, DraftPlan(
        project_id=pid, title=d.title, description=d.description, status="draft",
        source="Planning doc / PRD"))
    epic = await _add(session, DraftTask(
        plan_id=plan.id, name=d.epic, type=TaskType.summary, estimate_days=0, sort_order=0))
    for i, t in enumerate(d.tasks, start=1):
        await _add(session, DraftTask(
            plan_id=plan.id, parent_id=epic.id, name=t.name, type=TaskType(t.type),
            estimate_days=t.estimate_days, story_points=t.story_points, sort_order=i))


async def _build_project_activity(
    session: AsyncSession, spec: ProjectSpec, pid: int, comps: dict[str, ArchitectureComponent]
) -> None:
    base = utcnow()
    component_id = next((_req(c.id) for c in comps.values()), None)
    for w in range(spec.deploy_weeks):
        await _add(session, ActivityEvent(
            project_id=pid, kind="deploy", summary=f"Deployed {spec.key.lower()} build #{120 + w}",
            source="ci", component_id=component_id, reference=f"deploy-{spec.key}-{120 + w}",
            created_at=base - timedelta(weeks=w, hours=2)))
    for inc in spec.incidents:
        comp_id = (
            _req(comps[inc.component].id) if inc.component and inc.component in comps else None
        )
        await _add(session, ActivityEvent(
            project_id=pid, kind="incident_open", summary=inc.summary, source="ci",
            component_id=comp_id, created_at=base - timedelta(days=inc.opened_days_ago)))
        await _add(session, ActivityEvent(
            project_id=pid, kind="incident_close", summary=f"Resolved: {inc.summary}",
            source="ci", component_id=comp_id,
            created_at=base - timedelta(days=inc.opened_days_ago, hours=-inc.recovered_hours)))
    if spec.incidents:
        await _add(session, ActivityEvent(
            project_id=pid, kind="build_failure", summary="CI failed on a flaky integration test",
            source="ci", created_at=base - timedelta(days=8)))


async def _baseline_flagship(session: AsyncSession, refs: _Refs) -> None:
    project = refs.projects[FLAGSHIP_KEY]
    pid = _req(project.id)
    tasks = refs.leaf_order[FLAGSHIP_KEY]
    for t in tasks:
        t.baseline_start = t.start
        t.baseline_end = t.end
    await session.flush()
    await _add(session, Baseline(
        project_id=pid, note="Plan-of-record committed at architecture sign-off.",
        task_count=len(tasks), project_end=max((t.end for t in tasks if t.end), default=None)))
    in_flight = refs.tasks[FLAGSHIP_KEY].get("In-VPC model execution")
    if in_flight is not None:
        in_flight.duration += 4
        await session.flush()
        await reschedule_project(session, pid)


async def _build_allocations(session: AsyncSession, refs: _Refs) -> None:
    for eng_name, project_key, pct in ALLOCATIONS:
        eng_id = refs.eng(eng_name)
        project = refs.projects.get(project_key)
        if eng_id is None or project is None:
            continue
        await _add(session, Allocation(
            engineer_id=eng_id, project_id=project.id, percent_allocation=pct,
            start_date=project.start_date, end_date=project.target_date))


# --------------------------------------------------------------------------- #
# Connectors (demo HTTP mock) + caches + scenarios
# --------------------------------------------------------------------------- #
async def _build_connections(session: AsyncSession, refs: _Refs) -> None:
    flagship = refs.projects[FLAGSHIP_KEY]
    fid = _req(flagship.id)
    conns: dict[str, Connection] = {}
    for dc in catalog.demo_connections(fid):
        conns[dc.provider] = await _add(session, Connection(
            provider=Provider(dc.provider), name=dc.name, config=dict(dc.config),
            encrypted_token=encrypt_token("demo-token")))

    prs = [
        (318, "Wire secure gateway into engine", "open", "tombecker"),
        (316, "Egress allow-list enforcement", "open", "yukitanaka"),
        (309, "Streaming pipeline core", "closed", "tombecker"),
    ]
    for number, title, state, author in prs:
        await _add(session, PullRequest(
            repo="helix-io/data-plane", number=number, title=title, state=state,
            url=f"https://github.com/helix-io/data-plane/pull/{number}", author=author))

    await _add(session, JiraLink(
        connection_id=_req(conns["jira"].id), jira_issue_id="910000", jira_key="HELIX-100",
        jira_issue_type="Epic", target_type="project", target_id=fid))
    for ext_id, key, name in (("910101", "HELIX-101", "Processing contract spec"),
                              ("910102", "HELIX-102", "Streaming pipeline core")):
        task = refs.tasks[FLAGSHIP_KEY].get(name)
        if task is not None and task.id is not None:
            await _add(session, ExternalRef(
                provider=Provider.jira, external_id=ext_id, external_key=key,
                entity_type="task", entity_id=task.id))


async def _build_scenarios(session: AsyncSession, refs: _Refs) -> None:
    for sc in SCENARIOS:
        init = refs.initiatives.get(sc.initiative_key)
        if init is None:
            continue
        scenario = await _add(session, Scenario(
            initiative_id=_req(init.id), title=sc.title, description=sc.description,
            status="draft"))
        for project in refs.projects.values():
            if project.initiative_id == init.id:
                await _add(session, ScenarioProject(
                    scenario_id=scenario.id, project_id=_req(project.id),
                    start_date=project.start_date, target_date=project.target_date,
                    skip_weekends=project.skip_weekends))
        project = refs.projects[sc.project_key]
        leaves = [t for t in refs.leaf_order[sc.project_key] if t.type != TaskType.milestone]
        clone_by_live: dict[int, ScenarioTask] = {}
        for live in leaves:
            st = await _add(session, ScenarioTask(
                scenario_id=scenario.id, project_id=_req(project.id), live_task_id=live.id,
                name=live.name, type=TaskType.task, duration=live.duration,
                percent_complete=live.percent_complete,
                assignee_engineer_id=live.assignee_engineer_id))
            clone_by_live[_req(live.id)] = st
        for prev, nxt in pairwise(leaves):
            await _add(session, ScenarioDependency(
                scenario_id=scenario.id, predecessor_id=_req(clone_by_live[_req(prev.id)].id),
                successor_id=_req(clone_by_live[_req(nxt.id)].id)))
        await _add(session, ScenarioTask(
            scenario_id=scenario.id, project_id=_req(project.id), name=sc.added_task,
            type=TaskType.task, duration=4,
            assignee_engineer_id=refs.eng(sc.added_task_assignee)))


# --------------------------------------------------------------------------- #
# Orchestration + summary
# --------------------------------------------------------------------------- #
async def load_seed_data(session: AsyncSession, keep_user_ids: set[int]) -> dict[str, int]:
    """Build the full demo dataset on an (assumed) empty domain. Returns the summary counts."""
    refs = _Refs()
    await _build_users(session, refs)
    await _build_team(session, refs)
    await _build_initiatives(session, refs)
    await _build_projects(session, refs)
    await _build_allocations(session, refs)
    await _build_connections(session, refs)
    await _build_scenarios(session, refs)
    await session.commit()
    return await seed_summary(session)


async def reseed(session: AsyncSession, keep_user_ids: set[int]) -> dict[str, int]:
    """Wipe everything (keeping the operator) and rebuild the demo dataset from scratch."""
    await clear_all_data(session, keep_user_ids)
    return await load_seed_data(session, keep_user_ids)


async def _count(session: AsyncSession, model: type[SQLModel]) -> int:
    result = await session.execute(select(func.count()).select_from(model))
    return int(result.scalar() or 0)


async def seed_summary(session: AsyncSession) -> dict[str, int]:
    """Per-entity row counts — drives the admin panel + tells whether data is loaded."""
    models: dict[str, type[SQLModel]] = {
        "users": User, "engineers": Engineer, "initiatives": Initiative, "projects": Project,
        "tasks": Task, "milestones": Milestone, "dependencies": Dependency,
        "allocations": Allocation, "decisions": ArchitectureDecision,
        "components": ArchitectureComponent, "risks": RiskItem, "specs": Spec,
        "outcomes": Outcome, "blockers": Blocker, "retrospectives": Retrospective,
        "draft_plans": DraftPlan, "connections": Connection, "scenarios": Scenario,
        "activity_events": ActivityEvent, "status_history": TaskStatusHistory,
        "documents": DocReference,
    }
    return {name: await _count(session, model) for name, model in models.items()}
