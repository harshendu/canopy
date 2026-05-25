"""Declarative demo dataset (lives in the repo; extend it as features grow).

The narrative — **Helix**, an enterprise hybrid platform vendor. Helix sells a *data
intelligence* product with a deliberately split architecture:

  * a vendor-owned, multi-tenant **control plane** (orchestration, a model/policy registry,
    an admin console) that Helix runs as SaaS, and
  * a customer-deployed **data plane** — the "intelligence suite" that runs inside the
    customer's own cloud/VPC so their data never leaves their environment — plus the
    **field/solutions** org that does the (complex) customer deployments and the domain
    implementation Helix sells alongside the software.

Three initiatives mirror that org (Control Plane / Data Plane / Field Delivery), each with
fully-populated projects so every UI surface has real content. Pure data + frozen dataclasses
(no DB, no logic) so it's trivial to review and extend; the loader turns it into rows.
"""

from __future__ import annotations

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


# --------------------------------------------------------------------------- #
# DATA — people
# --------------------------------------------------------------------------- #
USERS: tuple[DemoUser, ...] = (
    DemoUser("admin@helix.dev", "Dana Okafor", UserRole.admin, UserFunction.management),
    DemoUser("cto@helix.dev", "Olivia Chen", UserRole.viewer, UserFunction.leadership),
    DemoUser("architect@helix.dev", "Aanya Sharma", UserRole.architect,
             UserFunction.architecture),
    DemoUser("staff@helix.dev", "Ravi Iyer", UserRole.architect, UserFunction.engineering),
    DemoUser("em@helix.dev", "Marcus Lee", UserRole.engineering_manager,
             UserFunction.management),
    DemoUser("sofia@helix.dev", "Sofia Garcia", UserRole.engineer, UserFunction.engineering),
    DemoUser("tom@helix.dev", "Tom Becker", UserRole.engineer, UserFunction.engineering),
    DemoUser("yuki@helix.dev", "Yuki Tanaka", UserRole.engineer, UserFunction.engineering),
    DemoUser("noah@helix.dev", "Noah Williams", UserRole.engineer, UserFunction.engineering),
    DemoUser("pm@helix.dev", "Priya Nair", UserRole.viewer, UserFunction.product),
    DemoUser("design@helix.dev", "Lena Brooks", UserRole.viewer, UserFunction.design),
    DemoUser("field@helix.dev", "Diego Santos", UserRole.member, UserFunction.engineering),
)

TEAM_ROLES: tuple[str, ...] = (
    "Architecture", "Management", "Control Plane", "Data Plane", "Security",
    "Platform / SRE", "Field Engineering", "Frontend", "QA", "Data",
)

ENGINEERS: tuple[DemoEngineer, ...] = (
    DemoEngineer("Aanya Sharma", "Chief Architect",
                 ("architecture", "security", "distributed-systems"), "America/New_York", 30,
                 "aanyasharma", "Architecture", "architect@helix.dev"),
    DemoEngineer("Ravi Iyer", "Staff Engineer, Control Plane",
                 ("backend", "go", "kubernetes"), "Asia/Kolkata", 36, "raviiyer",
                 "Control Plane", "staff@helix.dev"),
    DemoEngineer("Marcus Lee", "Engineering Manager, Data Plane",
                 ("management", "backend"), "America/Los_Angeles", 20, "marcuslee",
                 "Management", "em@helix.dev"),
    DemoEngineer("Sofia Garcia", "Senior Backend Engineer",
                 ("backend", "python", "postgres"), "Europe/Madrid", 40, "sofiagarcia",
                 "Control Plane", "sofia@helix.dev"),
    DemoEngineer("Tom Becker", "Data Plane Engineer",
                 ("backend", "rust", "streaming"), "Europe/Berlin", 40, "tombecker",
                 "Data Plane", "tom@helix.dev"),
    DemoEngineer("Yuki Tanaka", "Security Engineer",
                 ("security", "cryptography", "networking"), "Asia/Tokyo", 40, "yukitanaka",
                 "Security", "yuki@helix.dev"),
    DemoEngineer("Noah Williams", "Site Reliability Engineer",
                 ("infra", "kubernetes", "observability"), "America/Chicago", 40,
                 "noahwilliams", "Platform / SRE", "noah@helix.dev"),
    DemoEngineer("Diego Santos", "Solutions Architect (Field)",
                 ("solutions", "deployment", "customer"), "America/Sao_Paulo", 40,
                 "diegosantos", "Field Engineering", "field@helix.dev"),
    DemoEngineer("Hannah Schmidt", "Frontend Engineer",
                 ("frontend", "react", "typescript"), "Europe/Berlin", 40, "hannahschmidt",
                 "Frontend", None),
    DemoEngineer("Omar Haddad", "Deployment Engineer (Field)",
                 ("deployment", "terraform", "customer"), "Asia/Dubai", 40, "omarhaddad",
                 "Field Engineering", None),
    DemoEngineer("Grace Liu", "Data Engineer",
                 ("data", "etl", "python"), "America/New_York", 40, "graceliu", "Data", None),
    DemoEngineer("Ivan Petrov", "Platform Engineer",
                 ("infra", "networking", "go"), "Europe/Kyiv", 40, "ivanpetrov",
                 "Platform / SRE", None),
    DemoEngineer("Mei Lin", "QA / Release Engineer",
                 ("qa", "automation", "e2e"), "Asia/Singapore", 32, "meilin", "QA", None),
)

AVAILABILITY: tuple[DemoAvailability, ...] = (
    DemoAvailability("Sofia Garcia", 2, 4, 0.0, "Vacation"),
    DemoAvailability("Tom Becker", -1, 1, 0.5, "Ramping up on the data-plane codebase"),
    DemoAvailability("Yuki Tanaka", 1, 2, 0.5, "Security conference"),
    DemoAvailability("Marcus Lee", -4, 16, 0.5, "Split between management and delivery"),
    DemoAvailability("Noah Williams", 3, 4, 0.7, "On-call rotation"),
    DemoAvailability("Diego Santos", 0, 6, 0.5, "On-site customer deployment"),
    DemoAvailability("Omar Haddad", 2, 3, 0.0, "Parental leave"),
)

# Engineer-to-project allocations (Sofia spans two projects → a cross-project over-allocation).
ALLOCATIONS: tuple[tuple[str, str, float], ...] = (
    ("Ravi Iyer", "CPORCH", 60), ("Sofia Garcia", "CPORCH", 60),
    ("Sofia Garcia", "REGISTRY", 60), ("Grace Liu", "REGISTRY", 50),
    ("Hannah Schmidt", "CONSOLE", 70), ("Lena Brooks", "CONSOLE", 20),
    ("Tom Becker", "ENGINE", 70), ("Marcus Lee", "ENGINE", 30),
    ("Mei Lin", "ENGINE", 40), ("Grace Liu", "ENGINE", 30),
    ("Yuki Tanaka", "GATEWAY", 70), ("Aanya Sharma", "GATEWAY", 25),
    ("Ivan Petrov", "OPERATOR", 60), ("Noah Williams", "OPERATOR", 40),
    ("Diego Santos", "PLAYBOOKS", 60), ("Omar Haddad", "FIELDCON", 70),
    ("Diego Santos", "FIELDCON", 30), ("Hannah Schmidt", "FIELDCON", 30),
)


# --------------------------------------------------------------------------- #
# DATA — initiatives
# --------------------------------------------------------------------------- #
INITIATIVES: tuple[InitiativeSpec, ...] = (
    InitiativeSpec(
        "CONTROL-PLANE", "Control Plane Scale-Out",
        "Run the multi-tenant control plane at 99.95% and onboard a tenant in under a day.",
        20, "Aanya Sharma", ("control-plane", "multi-tenant", "saas"), "on_track",
        "Orchestrator and registry on track; the console is the long pole.",
        outcomes=(
            OutcomeSpec("Cut tenant onboarding time", "time to first tenant", "hours",
                        72.0, 24.0, 40.0, "on_track", "Aanya Sharma"),
            OutcomeSpec("Hold control-plane availability", "uptime", "%",
                        99.5, 99.95, 99.9, "on_track", "Noah Williams"),
        ),
        risks=(
            RiskSpec("Noisy-neighbour tenants degrade shared services", "technical",
                     "medium", "high", "mitigating", "Ravi Iyer",
                     "Per-tenant quotas + isolation in the orchestrator."),
        ),
        docs=(
            DocSpec("prd", "Control Plane PRD",
                    "https://drive.google.com/file/d/doc-prd-001/view", "drive"),
        ),
    ),
    InitiativeSpec(
        "DATA-PLANE", "Data Plane v2 — BYOC",
        "Ship a customer-deployed data plane with zero data egress and a one-hour install.",
        24, "Ravi Iyer", ("data-plane", "byoc", "security"), "at_risk",
        "Engine and gateway progressing; the gateway egress review is the critical risk.",
        outcomes=(
            OutcomeSpec("Eliminate customer data egress", "bytes egressed per tenant", "MB/day",
                        120.0, 0.0, 12.0, "on_track", "Yuki Tanaka"),
            OutcomeSpec("Cut data-plane install time", "install time", "min",
                        240.0, 60.0, 110.0, "at_risk", "Ivan Petrov"),
        ),
        risks=(
            RiskSpec("Customer environments vary too widely to support", "external",
                     "high", "high", "open", "Diego Santos",
                     "Constrain to three reference architectures.", target_weeks=-1),
        ),
        docs=(
            DocSpec("architecture", "BYOC reference architecture",
                    "https://drive.google.com/file/d/doc-arch-002/view", "drive"),
        ),
    ),
    InitiativeSpec(
        "FIELD-DELIVERY", "Field Delivery & Onboarding",
        "Make customer deployments repeatable: 90% first-time install success, value in a week.",
        16, "Marcus Lee", ("field", "delivery", "customer-success"), "on_track",
        "Playbooks landing; the customer-facing deployment console is in build.",
        outcomes=(
            OutcomeSpec("Raise first-time install success", "install success rate", "%",
                        55.0, 90.0, 72.0, "on_track", "Diego Santos"),
            OutcomeSpec("Cut time-to-first-value", "days to first value", "days",
                        21.0, 7.0, 12.0, "on_track", "Marcus Lee"),
        ),
    ),
)


# --------------------------------------------------------------------------- #
# DATA — projects (defined in app/services/seed/projects.py to keep files readable)
# --------------------------------------------------------------------------- #
from app.services.seed.projects import PROJECTS  # noqa: E402, F401  (re-exported)

FLAGSHIP_KEY = "ENGINE"

# Cross-project hand-offs inside one initiative (drive the cross-project critical path).
CROSS_PROJECT_HANDOFFS: tuple[tuple[tuple[str, str], tuple[str, str]], ...] = (
    (("GATEWAY", "Control-plane handshake protocol"), ("ENGINE", "Wire secure gateway in")),
    (("ENGINE", "Package engine artifact"), ("OPERATOR", "Bundle engine + gateway")),
    (("REGISTRY", "Policy bundle publish API"), ("CPORCH", "Consume policy bundles")),
)

# Each scenario is a faithful clone of its initiative's live plan (every project's tasks, deps,
# milestones, allocations, availability) with a coherent set of edits layered on — so the Compare,
# Capacity, Gantt and Milestones tabs all show a real delta against live. Statuses stay draft/ready
# (an "applied" scenario would have to match live, which the seed doesn't mutate).
SCENARIOS: tuple[ScenarioSpec, ...] = (
    ScenarioSpec(
        "DATA-PLANE", "Add a security engineer to pull GA forward",
        "The secure-gateway integration is the at-risk critical path. What if Ivan joins Yuki on "
        "the enclave work so the gateway lands sooner and BYOC GA pulls in three weeks?",
        "ENGINE", status="ready",
        added_tasks=(
            ScenarioAddedTask("Parallelize enclave hardening", 4, "Ivan Petrov",
                              after_task="In-VPC model execution"),
        ),
        duration_overrides=(("Wire secure gateway in", 3),),
        allocations=(ScenarioAllocSpec("Ivan Petrov", "ENGINE", 80, 0, 12),),
        milestone_pulls=(ScenarioMilestonePull("BYOC GA", -3),),
        target_weeks_delta=-3,
    ),
    ScenarioSpec(
        "CONTROL-PLANE", "Defer multi-region to cut Q3 scope",
        "What if multi-region autoscaling is deferred out of Q3 and that capacity goes to the "
        "tenant onboarding console instead?",
        "CPORCH", status="draft",
        removed_tasks=("Multi-region autoscaling",),
        added_tasks=(
            ScenarioAddedTask("Harden single-region autoscaling", 3, "Ravi Iyer",
                              after_task="Fleet health reconciler"),
        ),
        allocations=(ScenarioAllocSpec("Sofia Garcia", "CONSOLE", 40, 0, 10),),
        milestone_pulls=(ScenarioMilestonePull("GA", -2),),
        target_weeks_delta=-2,
    ),
    ScenarioSpec(
        "FIELD-DELIVERY", "Plan around the Q3 PTO crunch",
        "What if two field engineers are out over the summer? Model the availability dip and the "
        "buffer the guided-install work needs to absorb it.",
        "FIELDCON", status="draft",
        duration_overrides=(("Guided install wizard", 8),),
        availability=(
            ScenarioAvailSpec("Omar Haddad", 4, 6, 0.0, "Summer PTO"),
            ScenarioAvailSpec("Hannah Schmidt", 6, 8, 0.3, "Parental leave ramp-down"),
        ),
        milestone_pulls=(ScenarioMilestonePull("Guided install MVP", 2),),
        target_weeks_delta=2,
    ),
)


def demo_accounts() -> list[DemoAccount]:
    """The demo logins (for the login screen + admin panel + e2e). Password is shared."""
    return [DemoAccount(u.email, u.full_name, u.role.value, u.function.value) for u in USERS]


def demo_connections(flagship_project_id: int) -> list[DemoConnection]:
    return [
        DemoConnection("jira", "Jira — helix.atlassian.net", {
            "demo": True,
            "base_url": "https://helix.atlassian.net",
            "project_id": flagship_project_id,
            "jira_project_key": "HELIX",
            "email": "demo@helix.dev",
            "board_id": 1,
            "story_point_field": "customfield_10016",
            "epic_issue_type": "Epic",
            "story_issue_type": "Story",
        }),
        DemoConnection("github", "GitHub — helix-io/data-plane", {
            "demo": True, "owner": "helix-io", "repo": "data-plane",
        }),
        DemoConnection("gdrive", "Google Drive — Helix docs", {
            "demo": True, "folder_id": "demo-folder",
        }),
    ]
