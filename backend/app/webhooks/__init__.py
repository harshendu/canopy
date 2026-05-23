from fastapi import APIRouter

from app.webhooks import github, jira

webhook_router = APIRouter()
webhook_router.include_router(jira.router, prefix="/jira", tags=["webhooks"])
webhook_router.include_router(github.router, prefix="/github", tags=["webhooks"])
