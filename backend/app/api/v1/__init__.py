from fastapi import APIRouter

from app.api.deps import FeatureGate
from app.api.v1 import (
    activity,
    admin_demo,
    admin_features,
    admin_integrations,
    architecture,
    auth,
    blockers,
    connectors,
    decisions,
    delivery,
    dependencies,
    docs,
    drafts,
    drift,
    events,
    exports,
    features,
    gantt,
    initiatives,
    jira_links,
    me,
    milestones,
    outcomes,
    projects,
    retros,
    risk,
    risk_register,
    scenarios,
    specs,
    tasks,
    team,
)

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(me.router, prefix="/me", tags=["me"])
api_router.include_router(features.router, prefix="/features", tags=["features"])
api_router.include_router(
    initiatives.router,
    prefix="/initiatives",
    tags=["initiatives"],
    dependencies=[FeatureGate("portfolio.initiatives")],
)
api_router.include_router(projects.router, prefix="/projects", tags=["projects"])
api_router.include_router(milestones.router, prefix="/milestones", tags=["milestones"])
api_router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
api_router.include_router(dependencies.router, prefix="/dependencies", tags=["dependencies"])
api_router.include_router(team.router, prefix="/team", tags=["team"])
api_router.include_router(
    architecture.router,
    prefix="/architecture",
    tags=["architecture"],
    dependencies=[FeatureGate("architecture")],
)
api_router.include_router(
    decisions.router,
    prefix="/decisions",
    tags=["decisions"],
    dependencies=[FeatureGate("architecture")],
)
api_router.include_router(
    connectors.router,
    prefix="/connectors",
    tags=["connectors"],
    dependencies=[FeatureGate("integrations")],
)
api_router.include_router(
    jira_links.router, tags=["jira-links"], dependencies=[FeatureGate("integrations")]
)
api_router.include_router(
    docs.router, tags=["docs"], dependencies=[FeatureGate("governance.docs")]
)
api_router.include_router(
    specs.router, tags=["specs"], dependencies=[FeatureGate("governance.specs")]
)
api_router.include_router(
    delivery.router, tags=["delivery"], dependencies=[FeatureGate("tracking.delivery")]
)
api_router.include_router(
    outcomes.router, tags=["outcomes"], dependencies=[FeatureGate("portfolio.outcomes")]
)
api_router.include_router(events.router, prefix="/events", tags=["events"])
api_router.include_router(gantt.router, tags=["gantt"])
api_router.include_router(
    drafts.router, tags=["drafts"], dependencies=[FeatureGate("planning.draft_plans")]
)
api_router.include_router(
    exports.router, tags=["exports"], dependencies=[FeatureGate("reporting.exports")]
)
api_router.include_router(
    risk.router, tags=["risk"], dependencies=[FeatureGate("governance.risk")]
)
api_router.include_router(
    risk_register.router,
    tags=["risk-register"],
    dependencies=[FeatureGate("governance.risk")],
)
api_router.include_router(
    drift.router, tags=["drift"], dependencies=[FeatureGate("architecture.drift")]
)
api_router.include_router(
    retros.router, tags=["retros"], dependencies=[FeatureGate("governance.retros")]
)
api_router.include_router(activity.router, tags=["activity"])
api_router.include_router(
    blockers.router, tags=["blockers"], dependencies=[FeatureGate("tracking.blockers")]
)
api_router.include_router(
    scenarios.router, tags=["scenarios"], dependencies=[FeatureGate("planning.scenarios")]
)
api_router.include_router(admin_integrations.router, prefix="/admin", tags=["admin"])
api_router.include_router(admin_features.router, prefix="/admin", tags=["admin"])
api_router.include_router(admin_demo.router, prefix="/admin", tags=["admin"])
