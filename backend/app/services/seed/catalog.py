"""Declarative demo dataset (lives in the repo; extend it as features grow).

Pure data + small frozen dataclasses — no DB, no imports from the loader — so it is trivial to
review and to reuse (e.g. e2e tests asserting on the seeded fixtures). The loader
(`app/services/seed/loader.py`) turns this into rows.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models.base import UserFunction, UserRole

# Shared password for every demo login (local/dev only; surfaced in the UI in demo mode).
DEMO_PASSWORD = "canopy-demo"


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
    deadline_weeks: int | None = None


@dataclass(frozen=True)
class PhaseSpec:
    name: str
    tasks: tuple[TaskSpec, ...]


@dataclass(frozen=True)
class MilestoneSpec:
    name: str
    target_weeks: int
    status: str = "planned"


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


# --------------------------------------------------------------------------- #
# People — one user per role, spanning every cross-functional persona.
# --------------------------------------------------------------------------- #
USERS: tuple[DemoUser, ...] = (
    DemoUser("admin@canopy.dev", "Dana Reed", UserRole.admin, UserFunction.management),
    DemoUser("architect@canopy.dev", "Aanya Sharma", UserRole.architect,
             UserFunction.architecture),
    DemoUser("em@canopy.dev", "Marcus Lee", UserRole.engineering_manager,
             UserFunction.management),
    DemoUser("staff@canopy.dev", "Ravi Iyer", UserRole.architect, UserFunction.engineering),
    DemoUser("sofia@canopy.dev", "Sofia Garcia", UserRole.engineer, UserFunction.engineering),
    DemoUser("tom@canopy.dev", "Tom Becker", UserRole.engineer, UserFunction.engineering),
    DemoUser("yuki@canopy.dev", "Yuki Tanaka", UserRole.engineer, UserFunction.engineering),
    DemoUser("pm@canopy.dev", "Priya Nair", UserRole.viewer, UserFunction.product),
    DemoUser("design@canopy.dev", "Lena Brooks", UserRole.viewer, UserFunction.design),
    DemoUser("exec@canopy.dev", "Olivia Chen", UserRole.viewer, UserFunction.leadership),
    DemoUser("member@canopy.dev", "Sam Carter", UserRole.member, UserFunction.engineering),
)

TEAM_ROLES: tuple[str, ...] = (
    "Architecture", "Management", "Backend", "Frontend", "Platform", "QA", "Data"
)

ENGINEERS: tuple[DemoEngineer, ...] = (
    DemoEngineer("Aanya Sharma", "Principal Architect", ("architecture", "backend", "security"),
                 "America/New_York", 32, "aanyasharma", "Architecture", "architect@canopy.dev"),
    DemoEngineer("Marcus Lee", "Engineering Manager", ("management", "backend"),
                 "America/Los_Angeles", 20, "marcuslee", "Management", "em@canopy.dev"),
    DemoEngineer("Ravi Iyer", "Staff Engineer", ("backend", "distributed-systems", "security"),
                 "Asia/Kolkata", 36, "raviiyer", "Architecture", "staff@canopy.dev"),
    DemoEngineer("Sofia Garcia", "Senior Backend Engineer", ("backend", "python", "infra"),
                 "Europe/Madrid", 40, "sofiagarcia", "Backend", "sofia@canopy.dev"),
    DemoEngineer("Tom Becker", "Frontend Engineer", ("frontend", "react", "typescript"),
                 "Europe/Berlin", 40, "tombecker", "Frontend", "tom@canopy.dev"),
    DemoEngineer("Yuki Tanaka", "Full-stack Engineer", ("backend", "frontend", "data"),
                 "Asia/Tokyo", 40, "yukitanaka", "Backend", "yuki@canopy.dev"),
    DemoEngineer("Noah Williams", "Site Reliability Engineer",
                 ("infra", "kubernetes", "observability"), "America/Chicago", 40, "noahwilliams",
                 "Platform", None),
    DemoEngineer("Mei Lin", "QA Engineer", ("qa", "automation", "e2e"), "Asia/Singapore", 30,
                 "meilin", "QA", None),
    DemoEngineer("Diego Santos", "Data Engineer", ("data", "etl", "python"),
                 "America/Sao_Paulo", 40, "diegosantos", "Data", None),
)

AVAILABILITY: tuple[DemoAvailability, ...] = (
    DemoAvailability("Sofia Garcia", 2, 4, 0.0, "Vacation"),
    DemoAvailability("Tom Becker", -1, 1, 0.5, "Ramping up on the codebase"),
    DemoAvailability("Yuki Tanaka", 1, 2, 0.5, "Conference"),
    DemoAvailability("Marcus Lee", -4, 12, 0.5, "Split between management and delivery"),
    DemoAvailability("Noah Williams", 3, 4, 0.7, "On-call rotation"),
)


# --------------------------------------------------------------------------- #
# Initiatives + projects (a scheduled WBS each).
# --------------------------------------------------------------------------- #
INITIATIVES: tuple[InitiativeSpec, ...] = (
    InitiativeSpec(
        "PLATFORM-2026", "Platform Modernization 2026",
        "Cut p99 latency 40% and halve incident MTTR by GA.", 24, "Aanya Sharma",
        ("platform", "reliability"), "on_track",
        "Gateway and auth tracking to plan; observability work is the current focus.",
    ),
    InitiativeSpec(
        "GROWTH-2026", "Growth & Activation",
        "Lift new-user activation from 38% to 55% within two quarters.", 16, "Marcus Lee",
        ("growth", "activation"), "at_risk",
        "Onboarding redesign is slipping on frontend capacity; billing is on track.",
    ),
)

PROJECTS: tuple[ProjectSpec, ...] = (
    ProjectSpec(
        "APIGW", "API Gateway", "A unified, observable edge gateway for all services.",
        "PLATFORM-2026", 8, 10, True, "on_track",
        "Routing shipped; auth integration is the critical path.",
        ("backend", "edge", "reliability"),
        (
            PhaseSpec("Discovery & Design", (
                TaskSpec("Gateway requirements", 3, "Done", 49, "Aanya Sharma", ("design",)),
                TaskSpec("Choose proxy tech (ADR)", 2, "Done", 45, "Ravi Iyer",
                         ("architecture",)),
                TaskSpec("API contract spec", 4, "Done", 38, "Sofia Garcia", ("design",),
                         (3, 4, 7)),
            )),
            PhaseSpec("Build", (
                TaskSpec("Routing & middleware", 6, "Done", 28, "Sofia Garcia", ("backend",),
                         (4, 6, 9)),
                TaskSpec("AuthN/AuthZ integration", 5, "In Progress", 35, "Ravi Iyer",
                         ("backend", "security"), (3, 5, 9)),
                TaskSpec("Rate limiting", 4, "In Progress", 9, "Yuki Tanaka", ("backend",)),
                TaskSpec("Observability hooks", 3, "To Do", 0, "Noah Williams",
                         ("observability",)),
            )),
            PhaseSpec("Harden & Launch", (
                TaskSpec("Load & soak testing", 5, "To Do", 0, "Mei Lin", ("qa",)),
                TaskSpec("Runbook & dashboards", 3, "To Do", 0, "Noah Williams", ("infra",)),
                TaskSpec("GA cutover", 0, "To Do", 0, None, (), None, True, 10),
            )),
        ),
        (
            MilestoneSpec("Design sign-off", 1, "hit"),
            MilestoneSpec("Feature complete", 6),
            MilestoneSpec("GA", 10),
        ),
    ),
    ProjectSpec(
        "AUTH", "Auth Service", "OIDC identity, sessions, MFA and recovery.",
        "PLATFORM-2026", 6, 8, True, "on_track",
        "OIDC integration underway; MFA and recovery queued.",
        ("backend", "security"),
        (
            PhaseSpec("Design", (
                TaskSpec("Token model ADR", 2, "Done", 30, "Ravi Iyer", ("architecture",)),
                TaskSpec("Session storage spike", 3, "Done", 21, "Sofia Garcia", ("backend",)),
            )),
            PhaseSpec("Build", (
                TaskSpec("OIDC provider integration", 5, "In Progress", 12, "Sofia Garcia",
                         ("backend", "security"), (4, 5, 8)),
                TaskSpec("MFA enrollment", 4, "To Do", 0, "Yuki Tanaka", ("backend",)),
                TaskSpec("Account recovery", 3, "To Do", 0, "Tom Becker", ("frontend",)),
            )),
        ),
        (MilestoneSpec("Auth beta", 6),),
    ),
    ProjectSpec(
        "ONB", "Onboarding Revamp", "A guided, progressive onboarding flow.",
        "GROWTH-2026", 5, 9, False, "at_risk",
        "Welcome flow is aging in review; frontend capacity is the constraint.",
        ("frontend", "growth"),
        (
            PhaseSpec("Research", (
                TaskSpec("Funnel analysis", 3, "Done", 28, "Yuki Tanaka", ("data",)),
                TaskSpec("Onboarding redesign", 4, "Done", 18, "Tom Becker", ("design",)),
            )),
            PhaseSpec("Build", (
                TaskSpec("New welcome flow", 6, "In Progress", 22, "Tom Becker", ("frontend",),
                         (4, 6, 10)),
                TaskSpec("Progressive profiling", 4, "To Do", 0, "Yuki Tanaka", ("frontend",)),
                TaskSpec("Email nudges", 3, "To Do", 0, "Diego Santos", ("data",)),
            )),
        ),
        (MilestoneSpec("Beta launch", 7),),
    ),
    ProjectSpec(
        "BILL", "Billing v2", "Usage metering and invoicing.",
        "GROWTH-2026", 3, 12, False, "on_track",
        "Design complete; metering pipeline is next.",
        ("backend", "billing"),
        (
            PhaseSpec("Design", (
                TaskSpec("Billing model ADR", 3, "Done", 12, "Ravi Iyer", ("architecture",)),
                TaskSpec("Pricing tiers spec", 2, "In Progress", 6, "Sofia Garcia", ("design",)),
            )),
            PhaseSpec("Build", (
                TaskSpec("Metering pipeline", 6, "To Do", 0, "Diego Santos", ("data",),
                         (5, 6, 10)),
                TaskSpec("Invoice generation", 5, "To Do", 0, "Sofia Garcia", ("backend",)),
            )),
        ),
        (MilestoneSpec("Billing GA", 12),),
    ),
    ProjectSpec(
        "TOOLS", "Internal Tools", "Admin console and operational tooling.",
        None, 4, 6, False, "on_track",
        "Admin console in progress; standalone (no initiative).",
        ("internal", "frontend"),
        (
            PhaseSpec("Build", (
                TaskSpec("Audit log viewer", 3, "Done", 14, "Yuki Tanaka", ("frontend",)),
                TaskSpec("Admin console", 5, "In Progress", 8, "Tom Becker", ("frontend",)),
                TaskSpec("Feature flag UI", 3, "To Do", 0, "Tom Becker", ("frontend",)),
            )),
        ),
        (MilestoneSpec("v1", 6),),
    ),
)

# The flagship project that receives the rich architecture / risk / spec / scenario content.
FLAGSHIP_KEY = "APIGW"

# A cross-project hand-off inside one initiative (Platform): gateway → auth.
CROSS_PROJECT_HANDOFF = (
    (FLAGSHIP_KEY, "Observability hooks"),
    ("AUTH", "OIDC provider integration"),
)


@dataclass(frozen=True)
class DemoAccount:
    email: str
    full_name: str
    role: str
    function: str


def demo_accounts() -> list[DemoAccount]:
    """The demo logins (for the login screen + admin panel + e2e). Password is shared."""
    return [
        DemoAccount(u.email, u.full_name, u.role.value, u.function.value) for u in USERS
    ]


# --------------------------------------------------------------------------- #
# Connector demo configs (served by the offline HTTP mock, see connectors/demo.py).
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class DemoConnection:
    provider: str
    name: str
    config: dict[str, object] = field(default_factory=dict)


def demo_connections(flagship_project_id: int) -> list[DemoConnection]:
    return [
        DemoConnection("jira", "Jira — demo.atlassian.net", {
            "demo": True,
            "base_url": "https://demo.atlassian.net",
            "project_id": flagship_project_id,
            "jira_project_key": "PLAT",
            "email": "demo@canopy.dev",
            "board_id": 1,
            "story_point_field": "customfield_10016",
            "epic_issue_type": "Epic",
            "story_issue_type": "Story",
        }),
        DemoConnection("github", "GitHub — canopy-co/platform", {
            "demo": True, "owner": "canopy-co", "repo": "platform",
        }),
        DemoConnection("gdrive", "Google Drive — Platform docs", {
            "demo": True, "folder_id": "demo-folder",
        }),
    ]
