"""Schema for the declarative demo datasets (lives in the repo; extend it as features grow).

A dataset is plain data: frozen dataclasses (no DB, no logic) describing people, an org, and
initiatives → projects → a scheduled WBS plus every surface the UI shows (architecture, ADRs,
specs, risks, outcomes, docs, blockers, retros, scenarios, connectors). The generic loader
(``loader.py``) turns a :class:`Dataset` into rows. The shipped narrative is a fictional online
retailer — see ``ecommerce.py`` / ``ecommerce_projects.py``; ``DATASETS`` in the package init
registers it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from app.models.base import UserFunction, UserRole

# Shared password for every demo login (local/dev only; surfaced in the UI in demo mode).
DEMO_PASSWORD = "canopy-demo"


# --------------------------------------------------------------------------- #
# People
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class DemoUser:
    email: str
    full_name: str
    role: UserRole
    function: UserFunction


@dataclass(frozen=True)
class DemoEngineer:
    name: str
    title: str
    skill_tags: tuple[str, ...]
    timezone: str
    committed_hours_per_week: float
    github_login: str
    role_name: str
    user_email: str | None = None  # links the team member to a login (for /me + attribution)


@dataclass(frozen=True)
class DemoAvailability:
    engineer: str
    start_weeks: int  # weeks from today (may be negative)
    end_weeks: int
    capacity_factor: float
    note: str


# --------------------------------------------------------------------------- #
# Work breakdown
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class TaskSpec:
    name: str
    duration: int = 3
    status: str = "To Do"  # To Do | In Progress | In Review | Done
    entered_days_ago: int = 0  # when it entered its current status (drives history + aging)
    assignee: str | None = None  # engineer name
    tags: tuple[str, ...] = ()
    estimate: tuple[int, int, int] | None = None  # PERT optimistic/likely/pessimistic
    milestone: bool = False
    deadline_weeks: int | None = None  # a hard deadline (weeks from today; < end = a miss)


@dataclass(frozen=True)
class PhaseSpec:
    name: str
    tasks: tuple[TaskSpec, ...]


@dataclass(frozen=True)
class MilestoneSpec:
    name: str
    target_weeks: int  # weeks from today (negative = already due → overdue alert)
    status: str = "planned"  # planned | at_risk | hit | missed


# --------------------------------------------------------------------------- #
# Architecture + decisions
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ComponentSpec:
    name: str
    kind: str  # service | module | datastore | external | ui
    tier: str  # presentation | business | data | infra
    criticality: str  # low | med | high
    owner: str | None = None


@dataclass(frozen=True)
class LinkSpec:
    source: str
    target: str
    kind: str = "depends_on"  # depends_on | calls | publishes_to | reads_from


@dataclass(frozen=True)
class BindingSpec:
    component: str
    path_glob: str
    module_prefix: str | None = None


@dataclass(frozen=True)
class FitnessSpec:
    kind: str  # forbid | require
    source: str
    target: str
    description: str


@dataclass(frozen=True)
class ADRCommentSpec:
    author: str
    body: str
    kind: str = "comment"  # comment | approve | request_changes | reject


@dataclass(frozen=True)
class ADRSpec:
    title: str
    status: str  # proposed | under_discussion | accepted | rejected | superseded | deferred
    reversibility: str | None = None  # one_way | two_way
    owner: str | None = None
    proposer: str | None = None
    context: str | None = None
    decision: str | None = None
    consequences: str | None = None
    alternatives: tuple[str, ...] = ()
    components: tuple[str, ...] = ()
    stakeholders: tuple[str, ...] = ()
    comments: tuple[ADRCommentSpec, ...] = ()
    fitness: FitnessSpec | None = None
    created_days_ago: int = 2
    decide_by_weeks: int | None = None  # for `deferred` (negative = overdue in the queue)


@dataclass(frozen=True)
class DriftSpec:
    kind: str  # unexpected_dependency | dead_dependency | unimplemented_adr | implicit_decision
    summary: str
    components: tuple[str, ...] = ()
    detail: str | None = None
    suspected_cause: str | None = None
    status: str = "open"  # open | accepted | rejected | false_positive


# --------------------------------------------------------------------------- #
# Specs / risk / outcomes / docs / blockers / retro / draft / activity
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class CriterionSpec:
    text: str
    status: str = "open"  # open | met | unmet | waived
    verification: str | None = None


@dataclass(frozen=True)
class SpecSpec:
    title: str
    problem: str
    status: str  # draft | approved | in_progress | verified | archived
    owner: str | None = None
    context: str | None = None
    out_of_scope: str | None = None
    adr_title: str | None = None  # link to an ADR in the same project
    source_url: str | None = None
    criteria: tuple[CriterionSpec, ...] = ()
    task_names: tuple[str, ...] = ()  # tasks that implement the spec


@dataclass(frozen=True)
class RiskSpec:
    title: str
    category: str  # schedule | scope | technical | resource | external | quality | security
    probability: str  # low | medium | high
    impact: str
    status: str  # open | mitigating | accepted | resolved | occurred
    owner: str | None = None
    mitigation: str | None = None
    contingency: str | None = None
    target_weeks: int | None = None  # negative = overdue resolution (fires an alert)


@dataclass(frozen=True)
class MitigationSpec:
    indicator_key: str
    note: str
    owner: str | None = None
    resolved: bool = False
    check_in_weeks: int | None = None


@dataclass(frozen=True)
class OutcomeSpec:
    statement: str
    metric: str
    unit: str
    baseline: float
    target: float
    current: float
    status: str  # pending | on_track | at_risk | validated | invalidated
    owner: str | None = None
    target_weeks: int = 12


@dataclass(frozen=True)
class DocSpec:
    kind: str  # prd | design | tech_design | architecture | release | qa | runbook | other
    title: str
    url: str
    source: str = "manual"  # jira_epic | manual | repo | drive
    task_name: str | None = None  # if set, attach at task scope (else project/initiative)


@dataclass(frozen=True)
class BlockerSpec:
    task_name: str
    reason: str
    category: str  # dependency | resource | decision | external | technical
    severity: str  # low | medium | high | critical
    owner: str | None = None
    raised_by: str | None = None
    resolved: bool = False
    created_days_ago: int = 6
    needed_weeks: int | None = None


@dataclass(frozen=True)
class RetroCommentSpec:
    author: str
    body: str


@dataclass(frozen=True)
class RetroSpec:
    title: str
    kind: str = "project_retro"  # project_retro | incident_postmortem
    body: str = ""
    components: tuple[str, ...] = ()
    comments: tuple[RetroCommentSpec, ...] = ()


@dataclass(frozen=True)
class DraftTaskSpec:
    name: str
    type: str = "task"  # task | summary | milestone
    estimate_days: int = 1
    story_points: float | None = None


@dataclass(frozen=True)
class DraftSpec:
    title: str
    description: str
    epic: str
    tasks: tuple[DraftTaskSpec, ...] = ()


@dataclass(frozen=True)
class IncidentSpec:
    summary: str
    opened_days_ago: int
    recovered_hours: int = 6
    component: str | None = None


# --------------------------------------------------------------------------- #
# Projects + initiatives + scenarios
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ProjectSpec:
    key: str
    name: str
    description: str
    initiative_key: str | None
    start_weeks_ago: int
    target_weeks_ahead: int
    skip_weekends: bool
    health: str | None
    status_note: str
    tags: tuple[str, ...]
    phases: tuple[PhaseSpec, ...]
    milestones: tuple[MilestoneSpec, ...] = ()
    components: tuple[ComponentSpec, ...] = ()
    component_links: tuple[LinkSpec, ...] = ()
    bindings: tuple[BindingSpec, ...] = ()
    adrs: tuple[ADRSpec, ...] = ()
    drift: tuple[DriftSpec, ...] = ()
    specs: tuple[SpecSpec, ...] = ()
    risks: tuple[RiskSpec, ...] = ()
    mitigations: tuple[MitigationSpec, ...] = ()
    outcomes: tuple[OutcomeSpec, ...] = ()
    docs: tuple[DocSpec, ...] = ()
    blockers: tuple[BlockerSpec, ...] = ()
    retro: RetroSpec | None = None
    draft: DraftSpec | None = None
    incidents: tuple[IncidentSpec, ...] = ()
    deploy_weeks: int = 8  # weekly deploy events (DORA + activity feed)
    pod: str | None = None  # the pod that runs the project (USER_FLOWS §R6)
    owner: str | None = None  # the project's single owner (engineer name)


@dataclass(frozen=True)
class InitiativeSpec:
    key: str
    name: str
    outcome_statement: str
    target_weeks_ahead: int
    owner_engineer: str
    tags: tuple[str, ...]
    health: str | None
    status_note: str
    outcomes: tuple[OutcomeSpec, ...] = ()
    risks: tuple[RiskSpec, ...] = ()
    docs: tuple[DocSpec, ...] = ()
    # The initiative's owners: (engineer name, seat: technical | product | design | manager).
    # Several per initiative; one person may own several. Empty (and no team) → plain role
    # rules (USER_FLOWS §R6).
    leads: tuple[tuple[str, str], ...] = ()
    team_key: str | None = None  # the team (product/platform group) it belongs to


@dataclass(frozen=True)
class TeamSpec:
    """A team that owns a product or platform: its pods and its director/manager seats."""

    key: str
    name: str
    description: str
    pods: tuple[str, ...]
    directors: tuple[str, ...] = ()  # engineer names
    managers: tuple[str, ...] = ()


@dataclass(frozen=True)
class LeadershipNoteSpec:
    """A note from the executive layer on an initiative/project view (USER_FLOWS §BR)."""

    scope_key: str  # initiative key or project key (per `scope_level`)
    scope_level: str  # initiative | project
    author_email: str
    kind: str  # watch | priority | feedback
    body: str
    priority: int | None = None
    target_kind: str | None = None  # decision | risk | outcome | milestone
    target_title: str | None = None  # the target's title/name inside that scope
    status: str = "open"  # open | acknowledged | resolved
    response: str | None = None
    responder_email: str | None = None
    created_days_ago: int = 3


@dataclass(frozen=True)
class ScenarioAddedTask:
    """A brand-new task the what-if introduces (no live counterpart)."""

    name: str
    duration: int = 4
    assignee: str | None = None
    after_task: str | None = None  # live task name (in project_key) it depends on (FS)


@dataclass(frozen=True)
class ScenarioAllocSpec:
    """A scenario-only engineer allocation (e.g. pulling someone onto the work)."""

    engineer: str
    project_key: str
    percent_allocation: float = 100.0
    start_weeks: int = 0  # weeks from today
    end_weeks: int = 12


@dataclass(frozen=True)
class ScenarioAvailSpec:
    """A scenario-only availability override (PTO / ramp-up / conference)."""

    engineer: str
    start_weeks: int
    end_weeks: int
    capacity_factor: float = 0.0  # 0..1
    note: str | None = None


@dataclass(frozen=True)
class ScenarioMilestonePull:
    """Pull a cloned milestone's target date in (negative) or out (positive)."""

    name: str  # the milestone name within project_key
    weeks_delta: int


@dataclass(frozen=True)
class ScenarioSpec:
    initiative_key: str
    title: str
    description: str
    project_key: str  # the project whose tasks anchor the edits
    status: str = "draft"  # draft | ready (applied/archived would desync from live — never seeded)
    added_tasks: tuple[ScenarioAddedTask, ...] = ()
    removed_tasks: tuple[str, ...] = ()  # live task names (in project_key) to tombstone
    duration_overrides: tuple[tuple[str, int], ...] = ()  # (live task name, new duration)
    allocations: tuple[ScenarioAllocSpec, ...] = ()
    availability: tuple[ScenarioAvailSpec, ...] = ()
    milestone_pulls: tuple[ScenarioMilestonePull, ...] = ()
    target_weeks_delta: int = 0  # shift the project_key scenario target date


@dataclass(frozen=True)
class DemoAccount:
    email: str
    full_name: str
    role: str
    function: str


@dataclass(frozen=True)
class DemoConnection:
    provider: str
    name: str
    config: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class PullRequestSpec:
    """A cached GitHub PR on the flagship project, tied to the task it implements."""

    number: int
    title: str
    state: str  # open | closed
    author: str  # github login
    task_name: str


@dataclass(frozen=True)
class Dataset:
    """One complete, self-contained demo narrative (people → initiatives → projects → extras).

    The loader is generic over this holder, so alternate datasets are pure data modules that
    build one of these (see ``ecommerce.py``); ``DATASETS`` in ``__init__`` registers them.
    """

    key: str
    name: str
    description: str
    users: tuple[DemoUser, ...]
    team_roles: tuple[str, ...]
    engineers: tuple[DemoEngineer, ...]
    availability: tuple[DemoAvailability, ...]
    allocations: tuple[tuple[str, str, float], ...]
    initiatives: tuple[InitiativeSpec, ...]
    projects: tuple[ProjectSpec, ...]
    cross_project_handoffs: tuple[tuple[tuple[str, str], tuple[str, str]], ...]
    scenarios: tuple[ScenarioSpec, ...]
    flagship_key: str
    baseline_inflight_task: str  # flagship task that slips after the baseline (variance)
    github_repo: str  # "owner/repo" of the flagship's PR cache
    jira_project_key: str
    jira_epic: tuple[str, str]  # (issue id, key) linked to the flagship project
    jira_task_keys: tuple[tuple[str, str, str], ...]  # (issue id, key, flagship task name)
    pull_requests: tuple[PullRequestSpec, ...]
    connections: Callable[[int], list[DemoConnection]]  # flagship project id → connections
    leadership_notes: tuple[LeadershipNoteSpec, ...] = ()
    teams: tuple[TeamSpec, ...] = ()

    def accounts(self) -> list[DemoAccount]:
        return [DemoAccount(u.email, u.full_name, u.role.value, u.function.value)
                for u in self.users]
