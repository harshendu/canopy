"""Feature gates: the catalog of admin-toggleable features and the effective-state resolver.

Two levels: a **group** (`planning`) and the **features** inside it (`planning.scenarios`).
Every gate defaults to enabled; an admin stores a `FeatureFlag` row only to override. A feature
is effectively on iff its own flag is on **and** its group's flag is on, so one group toggle
cleanly shuts a whole surface. Core flows (projects, tasks, Gantt/CPM, team, auth) are
deliberately **not** in the catalog — they cannot be turned off.

Resolution (`resolve_effective`) is pure; the DB read is a single small-table load. Enforcement
is `require_feature` in `app/api/deps_features.py` (403 with a machine-readable detail), and the
frontend mirrors the same map from `GET /features` to hide gated navigation/tabs live (SSE
`features` event on every toggle).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.feature import FeatureFlag


@dataclass(frozen=True)
class FeatureDef:
    """One entry in the feature catalog (a group when `group` is None, else a feature)."""

    key: str
    label: str
    description: str
    group: str | None = None


# The catalog. Order is presentation order (groups first, then their features).
FEATURE_CATALOG: tuple[FeatureDef, ...] = (
    FeatureDef(
        "planning",
        "Planning & scheduling",
        "What-if projections, baselines, scenario simulation, and draft plans on top of the "
        "core Gantt/CPM scheduler (the scheduler itself is always on).",
    ),
    FeatureDef(
        "planning.whatif", "What-if projections",
        "Non-persisted schedule projections with hypothetical durations.", "planning",
    ),
    FeatureDef(
        "planning.baselines", "Baselines & schedule variance",
        "Snapshot the plan-of-record and overlay current-vs-baseline variance on the Gantt.",
        "planning",
    ),
    FeatureDef(
        "planning.scenarios", "Scenario simulation",
        "Initiative-level what-if workspaces: clone, edit, compare, and apply scenarios.",
        "planning",
    ),
    FeatureDef(
        "planning.draft_plans", "Draft plans → Jira",
        "Stage epic/story plans for review and push them to Jira as tickets (content only).",
        "planning",
    ),
    FeatureDef(
        "tracking",
        "Progress tracking",
        "Flow board, burndown, probabilistic forecast, alerts, blockers, delivery metrics, "
        "and the capacity heatmap.",
    ),
    FeatureDef(
        "tracking.board", "Flow board",
        "Status lanes with WIP and aging derived from the Jira-mirrored status history.",
        "tracking",
    ),
    FeatureDef(
        "tracking.burndown", "Burndown",
        "Remaining/completed per week from task status history.", "tracking",
    ),
    FeatureDef(
        "tracking.forecast", "Probabilistic forecast",
        "Monte-Carlo P50/P85 completion dates from historical weekly throughput.", "tracking",
    ),
    FeatureDef(
        "tracking.alerts", "Alerts digest",
        "Actionable alerts: deadline misses, overdue milestones, over-allocation, blockers.",
        "tracking",
    ),
    FeatureDef(
        "tracking.blockers", "Blockers",
        "Raise and resolve impediments on tasks; they surface in /me and alerts.", "tracking",
    ),
    FeatureDef(
        "tracking.delivery", "Delivery metrics (DORA + flow)",
        "Team-level deploy frequency, change-fail rate, throughput, cycle time, WIP.",
        "tracking",
    ),
    FeatureDef(
        "tracking.capacity", "Capacity heatmap",
        "Engineer-by-week allocation heatmap and over-allocation detection.", "tracking",
    ),
    FeatureDef(
        "architecture",
        "Architecture & decisions",
        "Component map, ADRs with lifecycle/reviews, decision queue, impact analysis, and "
        "architecture drift.",
    ),
    FeatureDef(
        "architecture.drift", "Architecture drift",
        "Drift scans of observed vs declared topology, fitness-function violations, "
        "reconciliation.", "architecture",
    ),
    FeatureDef(
        "portfolio",
        "Portfolio & outcomes",
        "The program layer above single projects: initiatives (rollups, cross-project critical "
        "path, digest) and outcome bets.",
    ),
    FeatureDef(
        "portfolio.initiatives", "Initiatives",
        "Group projects into initiatives with health rollups, digest, and cross-project "
        "dependencies.", "portfolio",
    ),
    FeatureDef(
        "portfolio.outcomes", "Outcomes",
        "Track a project/initiative as a measurable bet: hypothesis, metric, verdict.",
        "portfolio",
    ),
    FeatureDef(
        "governance",
        "Governance & practice",
        "Risk management, retrospectives, specs, and the document graph.",
    ),
    FeatureDef(
        "governance.risk", "Risk",
        "Composite risk score, timeline, mitigation log, and the RAID register.", "governance",
    ),
    FeatureDef(
        "governance.retros", "Retrospectives",
        "Project retros and incident postmortems with follow-up actions.", "governance",
    ),
    FeatureDef(
        "governance.specs", "Specs",
        "Spec-driven development: acceptance criteria, task links, readiness audit.",
        "governance",
    ),
    FeatureDef(
        "governance.docs", "Document graph",
        "Typed links to PRDs/designs living in Jira/Drive/Figma/repos, with coverage.",
        "governance",
    ),
    FeatureDef(
        "integrations",
        "Integrations",
        "The connectors surface: Jira/GitHub/Drive connections, OAuth, sync, Jira links, "
        "reads, and ingest.",
    ),
    FeatureDef(
        "integrations.webhooks", "Webhook intake",
        "Accept GitHub/Jira webhooks (signature-verified, processed in the background).",
        "integrations",
    ),
    FeatureDef(
        "reporting",
        "Reporting",
        "Point-in-time export snapshots of a project/initiative/portfolio.",
    ),
    FeatureDef(
        "reporting.exports", "Export snapshots (PDF/CSV)",
        "Download a snapshot or save it to a connected Google Drive.", "reporting",
    ),
    FeatureDef(
        "ai",
        "AI & agents",
        "Agent-facing capabilities beyond the read/write API the MCP tools already use.",
    ),
    FeatureDef(
        "ai.agent_tokens", "Bounded agent tokens",
        "Mint scoped tokens for Claude that are blocked from one-way-door actions.", "ai",
    ),
)

FEATURES_BY_KEY: dict[str, FeatureDef] = {f.key: f for f in FEATURE_CATALOG}


def is_known_feature(key: str) -> bool:
    return key in FEATURES_BY_KEY


def resolve_effective(stored: dict[str, bool]) -> dict[str, bool]:
    """The effective on/off state of every catalog key, from the stored overrides.

    A group is on unless overridden off. A feature is on iff it and its group are on. Unknown
    stored keys (e.g. a feature removed from the catalog) are ignored.
    """
    effective: dict[str, bool] = {}
    for feature in FEATURE_CATALOG:
        own = stored.get(feature.key, True)
        if feature.group is not None:
            own = own and stored.get(feature.group, True)
        effective[feature.key] = own
    return effective


async def load_stored_flags(session: AsyncSession) -> dict[str, bool]:
    rows = (await session.execute(select(FeatureFlag))).scalars().all()
    return {row.key: row.enabled for row in rows}


async def effective_features(session: AsyncSession) -> dict[str, bool]:
    """The effective feature map straight from the DB (one small-table read)."""
    return resolve_effective(await load_stored_flags(session))


async def feature_enabled(session: AsyncSession, key: str) -> bool:
    """Whether one feature is effectively on (unknown keys are on — fail open for core)."""
    if not is_known_feature(key):
        return True
    return (await effective_features(session)).get(key, True)
