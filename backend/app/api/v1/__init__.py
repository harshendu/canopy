from fastapi import APIRouter

from app.api.v1 import (
    architecture,
    auth,
    connectors,
    dependencies,
    gantt,
    milestones,
    projects,
    tasks,
    team,
)

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(projects.router, prefix="/projects", tags=["projects"])
api_router.include_router(milestones.router, prefix="/milestones", tags=["milestones"])
api_router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
api_router.include_router(dependencies.router, prefix="/dependencies", tags=["dependencies"])
api_router.include_router(team.router, prefix="/team", tags=["team"])
api_router.include_router(architecture.router, prefix="/architecture", tags=["architecture"])
api_router.include_router(connectors.router, prefix="/connectors", tags=["connectors"])
api_router.include_router(gantt.router, tags=["gantt"])
