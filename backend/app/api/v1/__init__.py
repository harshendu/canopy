from fastapi import APIRouter

from app.api.v1 import (
    activity,
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
    gantt,
    initiatives,
    jira_links,
    me,
    milestones,
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
api_router.include_router(initiatives.router, prefix="/initiatives", tags=["initiatives"])
api_router.include_router(projects.router, prefix="/projects", tags=["projects"])
api_router.include_router(milestones.router, prefix="/milestones", tags=["milestones"])
api_router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
api_router.include_router(dependencies.router, prefix="/dependencies", tags=["dependencies"])
api_router.include_router(team.router, prefix="/team", tags=["team"])
api_router.include_router(architecture.router, prefix="/architecture", tags=["architecture"])
api_router.include_router(decisions.router, prefix="/decisions", tags=["decisions"])
api_router.include_router(connectors.router, prefix="/connectors", tags=["connectors"])
api_router.include_router(jira_links.router, tags=["jira-links"])
api_router.include_router(docs.router, tags=["docs"])
api_router.include_router(specs.router, tags=["specs"])
api_router.include_router(delivery.router, tags=["delivery"])
api_router.include_router(events.router, prefix="/events", tags=["events"])
api_router.include_router(gantt.router, tags=["gantt"])
api_router.include_router(drafts.router, tags=["drafts"])
api_router.include_router(exports.router, tags=["exports"])
api_router.include_router(risk.router, tags=["risk"])
api_router.include_router(risk_register.router, tags=["risk-register"])
api_router.include_router(drift.router, tags=["drift"])
api_router.include_router(retros.router, tags=["retros"])
api_router.include_router(activity.router, tags=["activity"])
api_router.include_router(blockers.router, tags=["blockers"])
api_router.include_router(scenarios.router, tags=["scenarios"])
