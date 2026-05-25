"""Turns the declarative demo catalog into a coherent set of rows, and resets it.

Everything routes through the ORM session so the data is identical across SQLite / Postgres /
MySQL. Projects are scheduled with the real CPM planner so the Gantt, critical path, baselines
and variance are genuine; status history / activity / risk snapshots are back-dated so the
time-series views (burndown, forecast, delivery metrics, risk timeline) have real trends.
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
    AVAILABILITY,
    CROSS_PROJECT_HANDOFF,
    ENGINEERS,
    FLAGSHIP_KEY,
    INITIATIVES,
    PROJECTS,
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


def _today() -> date:
    return date.today()


def _weeks(base: date, n: int) -> date:
    return base + timedelta(weeks=n)


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
    # Null self-referential FKs first: a single bulk DELETE of a self-referencing table would
    # otherwise violate the constraint on Postgres/MySQL (CLAUDE.md portability rule).
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
# Build — references threaded through a context object
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
    components: dict[str, ArchitectureComponent] = field(default_factory=dict)
    adrs: dict[int, ArchitectureDecision] = field(default_factory=dict)  # number -> ADR

    def eng(self, name: str | None) -> int | None:
        if name is None:
            return None
        return self.engineers[name].id


def _comp_id(refs: _Refs, name: str) -> int:
    cid = refs.components[name].id
    assert cid is not None
    return cid


async def _build_users(session: AsyncSession, refs: _Refs) -> None:
    existing = {
        u.email: u
        for u in (await session.execute(select(User))).scalars().all()
    }
    for spec in USERS:
        if spec.email in existing:
            refs.users[spec.email] = existing[spec.email]
            continue
        user = await _add(session, User(
            email=spec.email,
            hashed_password=hash_password(catalog.DEMO_PASSWORD),
            full_name=spec.full_name,
            role=spec.role,
            function=spec.function,
        ))
        refs.users[spec.email] = user


async def _build_team(session: AsyncSession, refs: _Refs) -> None:
    for name in TEAM_ROLES:
        refs.roles[name] = await _add(session, Role(name=name))
    for spec in ENGINEERS:
        user = refs.users.get(spec.user_email) if spec.user_email else None
        engineer = await _add(session, Engineer(
            name=spec.name,
            email=spec.user_email,
            title=spec.title,
            role_id=refs.roles[spec.role_name].id,
            user_id=user.id if user else None,
            skill_tags=list(spec.skill_tags),
            github_login=spec.github_login,
            timezone=spec.timezone,
            committed_hours_per_week=spec.committed_hours_per_week,
        ))
        refs.engineers[spec.name] = engineer

    today = _today()
    for av in AVAILABILITY:
        eng_id = refs.eng(av.engineer)
        if eng_id is None:
            continue
        await _add(session, EngineerAvailability(
            engineer_id=eng_id,
            start_date=_weeks(today, av.start_weeks),
            end_date=_weeks(today, av.end_weeks),
            capacity_factor=av.capacity_factor,
            note=av.note,
        ))


async def _build_initiatives(session: AsyncSession, refs: _Refs) -> None:
    today = _today()
    for spec in INITIATIVES:
        init = await _add(session, Initiative(
            key=spec.key,
            name=spec.name,
            outcome_statement=spec.outcome_statement,
            start_date=_weeks(today, -8),
            target_date=_weeks(today, spec.target_weeks_ahead),
            owner_engineer_id=refs.eng(spec.owner_engineer),
            tags=list(spec.tags),
            health=ProjectHealth(spec.health) if spec.health else None,
            status_note=spec.status_note,
            status_updated_at=utcnow(),
        ))
        refs.initiatives[spec.key] = init


async def _build_one_project(session: AsyncSession, refs: _Refs, spec: ProjectSpec) -> None:
    today = _today()
    init = refs.initiatives.get(spec.initiative_key) if spec.initiative_key else None
    project = await _add(session, Project(
        key=spec.key,
        name=spec.name,
        description=spec.description,
        initiative_id=init.id if init else None,
        start_date=_weeks(today, -spec.start_weeks_ago),
        target_date=_weeks(today, spec.target_weeks_ahead),
        skip_weekends=spec.skip_weekends,
        tags=list(spec.tags),
        health=ProjectHealth(spec.health) if spec.health else None,
        status_note=spec.status_note,
        status_updated_at=utcnow(),
    ))
    assert project.id is not None
    refs.projects[spec.key] = project
    refs.tasks[spec.key] = {}
    leaves: list[Task] = []

    for phase in spec.phases:
        summary = await _add(session, Task(
            project_id=project.id, name=phase.name, type=TaskType.summary, duration=0,
        ))
        for ts in phase.tasks:
            task = await _add(session, Task(
                project_id=project.id,
                parent_id=summary.id,
                name=ts.name,
                type=TaskType.milestone if ts.milestone else TaskType.task,
                duration=ts.duration,
                tags=list(ts.tags),
                assignee_engineer_id=refs.eng(ts.assignee),
                estimate_optimistic=ts.estimate[0] if ts.estimate else None,
                estimate_likely=ts.estimate[1] if ts.estimate else None,
                estimate_pessimistic=ts.estimate[2] if ts.estimate else None,
                deadline=_weeks(today, ts.deadline_weeks) if ts.deadline_weeks else None,
            ))
            refs.tasks[spec.key][ts.name] = task
            leaves.append(task)

    # Chain the leaves into a finish-to-start critical path.
    for prev, nxt in pairwise(leaves):
        assert prev.id is not None and nxt.id is not None
        await _add(session, Dependency(predecessor_id=prev.id, successor_id=nxt.id))
    refs.leaf_order[spec.key] = leaves

    # Project milestones (roadmap markers) + a couple of holidays for a 5-day calendar.
    for ms in spec.milestones:
        await _add(session, Milestone(
            project_id=project.id, name=ms.name,
            target_date=_weeks(today, ms.target_weeks), status=ms.status,
        ))
    if spec.skip_weekends:
        await _add(session, Holiday(
            project_id=project.id, day=_weeks(today, 3), name="Company holiday",
        ))

    await reschedule_project(session, project.id)
    await _apply_lifecycle(session, refs, spec)


async def _apply_lifecycle(session: AsyncSession, refs: _Refs, spec: ProjectSpec) -> None:
    """Back-date status history + set status/percent so the time-series views have trends."""
    base = utcnow()
    for phase in spec.phases:
        for ts in phase.tasks:
            task = refs.tasks[spec.key][ts.name]
            if ts.milestone:
                continue
            created_days, transitions = _lifecycle(ts.status, ts.entered_days_ago)
            task.created_at = base - timedelta(days=created_days)
            task.status = ts.status
            task.percent_complete = _PERCENT.get(ts.status, 0.0)
            author = ts.assignee or "Jira Sync"
            for from_status, to_status, days_ago in transitions:
                await _add(session, TaskStatusHistory(
                    task_id=task.id,
                    from_status=from_status,
                    to_status=to_status,
                    changed_at=base - timedelta(days=days_ago),
                    author=author,
                ))


async def _build_projects(session: AsyncSession, refs: _Refs) -> None:
    for spec in PROJECTS:
        await _build_one_project(session, refs, spec)

    # Cross-project hand-off within one initiative (gateway → auth).
    (pk_pred, t_pred), (pk_succ, t_succ) = CROSS_PROJECT_HANDOFF
    pred = refs.tasks[pk_pred][t_pred]
    succ = refs.tasks[pk_succ][t_succ]
    assert pred.id is not None and succ.id is not None
    await _add(session, Dependency(predecessor_id=pred.id, successor_id=succ.id))

    # Baseline + a small variance on the flagship so the Gantt overlay has something to show.
    await _baseline_flagship(session, refs)


async def _baseline_flagship(session: AsyncSession, refs: _Refs) -> None:
    project = refs.projects[FLAGSHIP_KEY]
    assert project.id is not None
    tasks = refs.leaf_order[FLAGSHIP_KEY]
    for t in tasks:
        t.baseline_start = t.start
        t.baseline_end = t.end
    await session.flush()
    await _add(session, Baseline(
        project_id=project.id,
        note="Plan-of-record committed at design sign-off.",
        task_count=len(tasks),
        project_end=max((t.end for t in tasks if t.end), default=None),
    ))
    # Bump one in-flight task so current schedule drifts from the baseline (visible variance).
    in_flight = refs.tasks[FLAGSHIP_KEY].get("AuthN/AuthZ integration")
    if in_flight is not None:
        in_flight.duration += 3
        await session.flush()
        await reschedule_project(session, project.id)


async def _build_allocations(session: AsyncSession, refs: _Refs) -> None:
    """Allocate engineers across projects, including one cross-project over-allocation."""
    plan: list[tuple[str, str, float]] = [
        ("Sofia Garcia", "APIGW", 60), ("Sofia Garcia", "AUTH", 60),  # over-allocated
        ("Ravi Iyer", "APIGW", 50), ("Yuki Tanaka", "APIGW", 40),
        ("Tom Becker", "ONB", 70), ("Tom Becker", "TOOLS", 40),
        ("Yuki Tanaka", "AUTH", 30), ("Diego Santos", "BILL", 80),
        ("Sofia Garcia", "BILL", 20), ("Noah Williams", "APIGW", 30),
        ("Mei Lin", "APIGW", 50), ("Aanya Sharma", "APIGW", 30),
    ]
    for eng_name, project_key, pct in plan:
        eng_id = refs.eng(eng_name)
        project = refs.projects.get(project_key)
        if eng_id is None or project is None:
            continue
        await _add(session, Allocation(
            engineer_id=eng_id, project_id=project.id, percent_allocation=pct,
            start_date=project.start_date, end_date=project.target_date,
        ))


# --------------------------------------------------------------------------- #
# Architecture (flagship) — components, links, ADRs, fitness, drift
# --------------------------------------------------------------------------- #
async def _build_architecture(session: AsyncSession, refs: _Refs) -> None:
    project = refs.projects[FLAGSHIP_KEY]
    assert project.id is not None
    pid = project.id

    comps = {
        "edge-gateway": ("service", "presentation", "high"),
        "auth-service": ("service", "business", "high"),
        "rate-limiter": ("module", "business", "med"),
        "config-store": ("datastore", "data", "med"),
        "telemetry": ("service", "infra", "med"),
        "web-app": ("ui", "presentation", "low"),
    }
    owners = {"edge-gateway": "Sofia Garcia", "auth-service": "Ravi Iyer",
              "telemetry": "Noah Williams"}
    for name, (kind, tier, crit) in comps.items():
        comp = await _add(session, ArchitectureComponent(
            project_id=pid, name=name, kind=kind, tier=tier, criticality=crit,
            owner_engineer_id=refs.eng(owners.get(name)),
            description=f"The {name} component of the gateway platform.",
        ))
        refs.components[name] = comp

    links = [
        ("web-app", "edge-gateway", "calls"),
        ("edge-gateway", "auth-service", "calls"),
        ("edge-gateway", "rate-limiter", "depends_on"),
        ("edge-gateway", "telemetry", "publishes_to"),
        ("auth-service", "config-store", "reads_from"),
        ("edge-gateway", "config-store", "depends_on"),  # the drift the fitness rule forbids
    ]
    for src, dst, kind in links:
        await _add(session, ComponentLink(
            source_id=_comp_id(refs, src),
            target_id=_comp_id(refs, dst),
            kind=kind,
        ))
    await _add(session, ComponentCodeBinding(
        component_id=_comp_id(refs, "edge-gateway"),
        path_glob="backend/app/api/**", module_prefix="app.api",
    ))
    await _add(session, ComponentCodeBinding(
        component_id=_comp_id(refs, "auth-service"),
        path_glob="backend/app/connectors/**", module_prefix="app.connectors",
    ))

    await _build_adrs(session, refs, pid)
    await _build_drift(session, refs, pid)


async def _build_adrs(session: AsyncSession, refs: _Refs, pid: int) -> None:
    today = _today()
    adr1 = await _add(session, ArchitectureDecision(
        project_id=pid, number=1, title="Adopt a single edge gateway",
        status=ADRStatus.accepted, reversibility=Reversibility.one_way,
        context="Each service exposing its own edge is inconsistent and hard to observe.",
        decision="Route all north-south traffic through one gateway.",
        consequences="A single, observable choke point; a new shared dependency to operate.",
        decision_owner_id=refs.eng("Aanya Sharma"), proposed_by_id=refs.eng("Ravi Iyer"),
    ))
    adr2 = await _add(session, ArchitectureDecision(
        project_id=pid, number=2, title="Use OpenTelemetry for tracing",
        status=ADRStatus.accepted, reversibility=Reversibility.two_way,
        context="We need vendor-neutral tracing across services.",
        decision="Standardize on OpenTelemetry + an OTLP collector.",
        decision_owner_id=refs.eng("Aanya Sharma"), proposed_by_id=refs.eng("Sofia Garcia"),
        alternatives=["Vendor agent", "Custom spans"],
    ))
    adr3 = await _add(session, ArchitectureDecision(
        project_id=pid, number=3, title="Token format: JWT vs opaque",
        status=ADRStatus.under_discussion, reversibility=Reversibility.one_way,
        context="The gateway must validate tokens cheaply at the edge.",
        decision="Proposed: short-lived JWTs with rotating keys.",
        decision_owner_id=refs.eng("Ravi Iyer"), proposed_by_id=refs.eng("Ravi Iyer"),
    ))
    await _add(session, ArchitectureDecision(
        project_id=pid, number=4, title="Multi-region rollout",
        status=ADRStatus.deferred, decide_by=_weeks(today, 4),
        context="Latency for non-US users is high.",
        decision_owner_id=refs.eng("Aanya Sharma"),
    ))
    await _add(session, ArchitectureDecision(
        project_id=pid, number=5, title="Introduce a service mesh",
        status=ADRStatus.proposed, proposed_by_id=refs.eng("Sofia Garcia"),
        context="mTLS and traffic policy are currently bespoke per service.",
    ))
    refs.adrs = {1: adr1, 2: adr2, 3: adr3}

    # Link ADRs to components.
    for adr, comp in ((adr1, "edge-gateway"), (adr2, "telemetry"), (adr3, "auth-service")):
        assert adr.id is not None
        await _add(session, ADRComponentLink(adr_id=adr.id, component_id=_comp_id(refs, comp)))

    # A machine-checkable fitness function on the accepted gateway ADR.
    assert adr1.id is not None
    await _add(session, ADRFitnessFunction(
        adr_id=adr1.id, kind="forbid",
        source_component_id=_comp_id(refs, "edge-gateway"),
        target_component_id=_comp_id(refs, "config-store"),
        description="The gateway must not read the datastore directly.",
    ))

    # A review thread on the in-discussion ADR (stakeholders + comments).
    assert adr3.id is not None
    for name in ("Sofia Garcia", "Aanya Sharma", "Ravi Iyer"):
        await _add(session, ADRStakeholder(adr_id=adr3.id, engineer_id=refs.eng(name)))
    comments = [
        ("Sofia Garcia", "JWTs let us validate at the edge without a round-trip.",
         ADRCommentKind.approve),
        ("Aanya Sharma", "Concerned about revocation — how do we handle logout?",
         ADRCommentKind.request_changes),
        ("Ravi Iyer", "We can pair short TTLs with a deny-list for revocation.",
         ADRCommentKind.comment),
    ]
    for name, body, kind in comments:
        await _add(session, ADRComment(
            adr_id=adr3.id, engineer_id=refs.eng(name), author_name=name, body=body, kind=kind,
        ))


async def _build_drift(session: AsyncSession, refs: _Refs, pid: int) -> None:
    gw = refs.components["edge-gateway"].id
    cs = refs.components["config-store"].id
    tel = refs.components["telemetry"].id
    await _add(session, DriftEvent(
        project_id=pid, kind="unexpected_dependency",
        rule_key="dep:edge-gateway->config-store",
        summary="edge-gateway reads config-store directly",
        detail="Observed import violates the accepted gateway layering ADR.",
        suspected_cause="PR #128 (Add OTLP exporter to gateway)",
        affected_component_ids=[c for c in (gw, cs) if c is not None],
        status="open",
    ))
    await _add(session, DriftEvent(
        project_id=pid, kind="unimplemented_adr", rule_key="adr:2:telemetry",
        summary="OpenTelemetry accepted but telemetry isn't wired in code yet",
        affected_component_ids=[c for c in (tel,) if c is not None],
        status="open",
    ))
    await _add(session, DriftScan(project_id=pid, finding_count=2))


# --------------------------------------------------------------------------- #
# Specs / risk / blockers / outcomes / docs / retro / draft / activity (flagship)
# --------------------------------------------------------------------------- #
async def _build_specs(session: AsyncSession, refs: _Refs) -> None:
    project = refs.projects[FLAGSHIP_KEY]
    assert project.id is not None
    spec = await _add(session, Spec(
        project_id=project.id, title="Edge gateway request routing",
        problem="Clients need one stable, observable entry point that routes to services.",
        context="Replaces per-service ingress with a unified gateway.",
        out_of_scope="GraphQL federation; that is a separate spec.",
        status=SpecStatus.in_progress, owner_engineer_id=refs.eng("Sofia Garcia"),
        adr_id=refs.adrs[1].id,
        source_url="https://demo.atlassian.net/wiki/spaces/PLAT/routing",
    ))
    criteria = [
        ("Requests route to the correct upstream by path and host.", "met",
         "Verified by the routing integration suite."),
        ("p99 added latency at the gateway is under 15ms.", "met", "Load test on staging."),
        ("Unmatched routes return a structured 404.", "open", None),
        ("Per-route rate limits are enforced.", "unmet", "Rate limiting still in progress."),
        ("Legacy direct ingress is removed.", "waived", "Deferred to the cutover phase."),
    ]
    for i, (text, st, verification) in enumerate(criteria):
        await _add(session, SpecCriterion(
            spec_id=spec.id, text=text, status=CriterionStatus(st),
            verification=verification, sort_order=i,
        ))
    # Link work to the spec.
    for name in ("Routing & middleware", "Rate limiting"):
        task = refs.tasks[FLAGSHIP_KEY].get(name)
        if task is not None:
            task.spec_id = spec.id
    await session.flush()


async def _build_risk(session: AsyncSession, refs: _Refs) -> None:
    project = refs.projects[FLAGSHIP_KEY]
    init = refs.initiatives["PLATFORM-2026"]
    assert project.id is not None and init.id is not None
    today = _today()

    await _add(session, RiskItem(
        scope_level=RiskScope.project, scope_id=project.id,
        title="Auth vendor lock-in", category=RiskCategory.technical,
        probability=RiskGrade.medium, impact=RiskGrade.high, status=RiskStatus.mitigating,
        owner_engineer_id=refs.eng("Ravi Iyer"),
        mitigation="Wrap the provider behind an internal interface.",
        contingency="Fall back to the self-hosted OIDC option.",
        target_resolution_date=_weeks(today, 4),
    ))
    await _add(session, RiskItem(
        scope_level=RiskScope.project, scope_id=project.id,
        title="Load-test environment unavailable", category=RiskCategory.resource,
        probability=RiskGrade.high, impact=RiskGrade.medium, status=RiskStatus.open,
        owner_engineer_id=refs.eng("Noah Williams"),
        mitigation="Stand up an ephemeral perf environment in CI.",
    ))
    await _add(session, RiskItem(
        scope_level=RiskScope.initiative, scope_id=init.id,
        title="Dependency on the data-platform team", category=RiskCategory.external,
        probability=RiskGrade.medium, impact=RiskGrade.medium, status=RiskStatus.open,
        owner_engineer_id=refs.eng("Marcus Lee"),
    ))

    await _add(session, RiskMitigation(
        project_id=project.id, indicator_key="deadline_violations",
        note="Re-sequencing auth work to protect the GA date.",
        owner_engineer_id=refs.eng("Aanya Sharma"), check_in=_weeks(today, 1), resolved=False,
    ))
    await _add(session, RiskMitigation(
        project_id=project.id, indicator_key="over_allocation",
        note="Brought in Mei for load testing to relieve Sofia.",
        owner_engineer_id=refs.eng("Marcus Lee"), resolved=True,
    ))

    base = utcnow()
    snapshots = [(5, 62, "high"), (4, 55, "moderate"), (3, 50, "moderate"),
                 (2, 48, "moderate"), (1, 44, "moderate"), (0, 40, "moderate")]
    for weeks_ago, score, level in snapshots:
        await _add(session, RiskSnapshot(
            project_id=project.id, score=score, level=level,
            created_at=base - timedelta(weeks=weeks_ago),
        ))


async def _build_blockers(session: AsyncSession, refs: _Refs) -> None:
    base = utcnow()
    today = _today()
    auth = refs.tasks[FLAGSHIP_KEY].get("AuthN/AuthZ integration")
    routing = refs.tasks[FLAGSHIP_KEY].get("Routing & middleware")

    if auth is not None:
        await _add(session, Blocker(
            task_id=auth.id, reason="Waiting on the security review of the token model.",
            raised_by_engineer_id=refs.eng("Ravi Iyer"), category=BlockerCategory.decision,
            severity=BlockerSeverity.high, owner_engineer_id=refs.eng("Aanya Sharma"),
            needed_by=_weeks(today, 1), created_at=base - timedelta(days=5),
        ))
    if routing is not None:
        await _add(session, Blocker(
            task_id=routing.id, reason="Blocked on staging access (now resolved).",
            raised_by_engineer_id=refs.eng("Sofia Garcia"), category=BlockerCategory.resource,
            severity=BlockerSeverity.medium, created_at=base - timedelta(days=20),
            resolved_at=base - timedelta(days=14),
        ))


async def _build_outcomes(session: AsyncSession, refs: _Refs) -> None:
    today = _today()
    platform = refs.initiatives["PLATFORM-2026"]
    growth = refs.initiatives["GROWTH-2026"]
    flagship = refs.projects[FLAGSHIP_KEY]
    assert platform.id is not None and growth.id is not None and flagship.id is not None
    rows = [
        (OutcomeScope.initiative, platform.id, "Cut p99 latency at the edge", "p99 latency",
         "ms", 800.0, 480.0, 640.0, OutcomeStatus.on_track, "Aanya Sharma"),
        (OutcomeScope.initiative, platform.id, "Halve incident MTTR", "MTTR", "min",
         120.0, 60.0, 95.0, OutcomeStatus.at_risk, "Marcus Lee"),
        (OutcomeScope.project, flagship.id, "Reduce gateway error rate", "5xx rate", "%",
         1.2, 0.3, 0.5, OutcomeStatus.on_track, "Sofia Garcia"),
        (OutcomeScope.initiative, growth.id, "Lift new-user activation", "activation", "%",
         38.0, 55.0, 41.0, OutcomeStatus.at_risk, "Marcus Lee"),
    ]
    for scope, sid, statement, metric, unit, base_v, target, current, st, owner in rows:
        await _add(session, Outcome(
            scope_level=scope, scope_id=sid, statement=statement, metric=metric, unit=unit,
            baseline_value=base_v, target_value=target, current_value=current, status=st,
            target_date=_weeks(today, 12), owner_engineer_id=refs.eng(owner),
        ))


async def _build_docs(session: AsyncSession, refs: _Refs) -> None:
    flagship = refs.projects[FLAGSHIP_KEY]
    platform = refs.initiatives["PLATFORM-2026"]
    assert flagship.id is not None and platform.id is not None
    contract = refs.tasks[FLAGSHIP_KEY].get("API contract spec")
    await _add(session, DocReference(
        scope_level=DocScope.project, scope_id=flagship.id, kind=DocKind.tech_design,
        title="Gateway technical design", url="https://demo.atlassian.net/wiki/PLAT/tech-design",
        source=DocSource.manual, owner_engineer_id=refs.eng("Sofia Garcia"),
    ))
    await _add(session, DocReference(
        scope_level=DocScope.initiative, scope_id=platform.id, kind=DocKind.prd,
        title="Platform 2026 PRD", url="https://drive.google.com/file/d/doc-prd-001/view",
        source=DocSource.drive,
    ))
    if contract is not None:
        await _add(session, DocReference(
            scope_level=DocScope.task, scope_id=contract.id, kind=DocKind.design,
            title="API contract (OpenAPI)", url="https://demo.atlassian.net/wiki/PLAT/openapi",
            source=DocSource.jira_epic, external_field="customfield_10042",
        ))


async def _build_retro(session: AsyncSession, refs: _Refs) -> None:
    flagship = refs.projects[FLAGSHIP_KEY]
    assert flagship.id is not None
    gw = refs.components["edge-gateway"].id
    retro = await _add(session, Retrospective(
        project_id=flagship.id, title="API Gateway — phase 1 retrospective",
        body=(
            "## What went well\n- Routing shipped ahead of schedule.\n\n"
            "## What to improve\n- Earlier security review on auth.\n\n"
            "## Actions\n- Book the perf environment before hardening."
        ),
        status="open", affected_component_ids=[c for c in (gw,) if c is not None],
    ))
    for name, body in (
        ("Sofia Garcia", "The contract-first approach paid off."),
        ("Aanya Sharma", "Let's start the security review one sprint earlier next time."),
    ):
        await _add(session, RetrospectiveComment(
            retrospective_id=retro.id, engineer_id=refs.eng(name), author_name=name, body=body,
        ))


async def _build_draft(session: AsyncSession, refs: _Refs) -> None:
    flagship = refs.projects[FLAGSHIP_KEY]
    assert flagship.id is not None
    plan = await _add(session, DraftPlan(
        project_id=flagship.id, title="Q3 hardening plan",
        description="Proposed hardening work to review before creating Jira tickets.",
        status="draft", source="Planning doc / PRD",
    ))
    epic = await _add(session, DraftTask(
        plan_id=plan.id, name="Hardening", type=TaskType.summary, estimate_days=0, sort_order=0,
    ))
    leaves = [
        ("Chaos testing", 5, 8.0),
        ("Failover drills", 3, 5.0),
        ("Security hardening", 4, 5.0),
    ]
    for i, (name, days, points) in enumerate(leaves):
        await _add(session, DraftTask(
            plan_id=plan.id, parent_id=epic.id, name=name, type=TaskType.task,
            estimate_days=days, story_points=points, sort_order=i + 1,
        ))


async def _build_activity(session: AsyncSession, refs: _Refs) -> None:
    flagship = refs.projects[FLAGSHIP_KEY]
    assert flagship.id is not None
    tel = refs.components["telemetry"].id
    base = utcnow()
    for w in range(8):
        await _add(session, ActivityEvent(
            project_id=flagship.id, kind="deploy", summary=f"Deployed gateway build #{120 + w}",
            source="ci", component_id=tel, reference=f"deploy-{120 + w}",
            created_at=base - timedelta(weeks=w, hours=2),
        ))
    await _add(session, ActivityEvent(
        project_id=flagship.id, kind="build_failure", summary="CI failed on flaky auth test",
        source="ci", created_at=base - timedelta(days=9),
    ))
    await _add(session, ActivityEvent(
        project_id=flagship.id, kind="incident_open", summary="Elevated 5xx after deploy #124",
        source="ci", component_id=tel, created_at=base - timedelta(days=12, hours=3),
    ))
    await _add(session, ActivityEvent(
        project_id=flagship.id, kind="incident_close", summary="5xx resolved (rollback)",
        source="ci", component_id=tel, created_at=base - timedelta(days=12),
    ))


# --------------------------------------------------------------------------- #
# Connections (demo HTTP mock) + caches + a scenario
# --------------------------------------------------------------------------- #
async def _build_connections(session: AsyncSession, refs: _Refs) -> None:
    flagship = refs.projects[FLAGSHIP_KEY]
    assert flagship.id is not None
    conns: dict[str, Connection] = {}
    for dc in catalog.demo_connections(flagship.id):
        conn = await _add(session, Connection(
            provider=Provider(dc.provider), name=dc.name, config=dict(dc.config),
            encrypted_token=encrypt_token("demo-token"),
        ))
        conns[dc.provider] = conn

    # GitHub PR cache (matches the mock fixtures).
    prs = [
        (128, "Add OTLP exporter to gateway", "open", "sofiagarcia"),
        (126, "Golden-signal dashboards", "open", "tombecker"),
        (120, "Structured request logging", "closed", "sofiagarcia"),
    ]
    for number, title, state, author in prs:
        await _add(session, PullRequest(
            repo="canopy-co/platform", number=number, title=title, state=state,
            url=f"https://github.com/canopy-co/platform/pull/{number}", author=author,
        ))

    # A Jira link from the demo epic into the flagship project.
    jira_id = conns["jira"].id
    assert jira_id is not None
    await _add(session, JiraLink(
        connection_id=jira_id, jira_issue_id="910000", jira_key="PLAT-100",
        jira_issue_type="Epic", target_type="project", target_id=flagship.id,
    ))
    # A couple of ExternalRefs so flagship tasks look synced from Jira.
    for ext_id, key, name in (("910101", "PLAT-101", "API contract spec"),
                              ("910102", "PLAT-102", "Routing & middleware")):
        task = refs.tasks[FLAGSHIP_KEY].get(name)
        if task is not None and task.id is not None:
            await _add(session, ExternalRef(
                provider=Provider.jira, external_id=ext_id, external_key=key,
                entity_type="task", entity_id=task.id,
            ))


async def _build_scenario(session: AsyncSession, refs: _Refs) -> None:
    """A minimal what-if scenario over the Platform initiative (snapshot of flagship work)."""
    init = refs.initiatives["PLATFORM-2026"]
    assert init.id is not None
    scenario = await _add(session, Scenario(
        initiative_id=init.id, title="Pull GA forward by adding an engineer",
        description="What if we add a backend engineer to the gateway in Q3?",
        status="draft",
    ))
    for key in ("APIGW", "AUTH"):
        project = refs.projects[key]
        assert project.id is not None
        await _add(session, ScenarioProject(
            scenario_id=scenario.id, project_id=project.id,
            start_date=project.start_date, target_date=project.target_date,
            skip_weekends=project.skip_weekends,
        ))
    # Clone the flagship's leaf tasks (flattened) + their FS chain.
    clone_by_live: dict[int, ScenarioTask] = {}
    leaves = [t for t in refs.leaf_order[FLAGSHIP_KEY] if t.type != TaskType.milestone]
    project = refs.projects[FLAGSHIP_KEY]
    assert project.id is not None
    for live in leaves:
        assert live.id is not None
        st = await _add(session, ScenarioTask(
            scenario_id=scenario.id, project_id=project.id, live_task_id=live.id,
            name=live.name, type=TaskType.task, duration=live.duration,
            percent_complete=live.percent_complete,
            assignee_engineer_id=live.assignee_engineer_id,
        ))
        clone_by_live[live.id] = st
    for prev, nxt in pairwise(leaves):
        assert prev.id is not None and nxt.id is not None
        pred_id = clone_by_live[prev.id].id
        succ_id = clone_by_live[nxt.id].id
        assert pred_id is not None and succ_id is not None
        await _add(session, ScenarioDependency(
            scenario_id=scenario.id, predecessor_id=pred_id, successor_id=succ_id,
        ))
    # An added (scenario-only) task — the extra engineer's parallel workstream.
    await _add(session, ScenarioTask(
        scenario_id=scenario.id, project_id=project.id, name="Parallelize rate limiting",
        type=TaskType.task, duration=3, assignee_engineer_id=refs.eng("Yuki Tanaka"),
    ))


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
    await _build_architecture(session, refs)
    await _build_specs(session, refs)
    await _build_risk(session, refs)
    await _build_blockers(session, refs)
    await _build_outcomes(session, refs)
    await _build_docs(session, refs)
    await _build_retro(session, refs)
    await _build_draft(session, refs)
    await _build_activity(session, refs)
    await _build_connections(session, refs)
    await _build_scenario(session, refs)
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
