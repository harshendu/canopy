from fastapi import APIRouter

from app.webhooks import events, github, jira, trackers

webhook_router = APIRouter()
webhook_router.include_router(jira.router, prefix="/jira", tags=["webhooks"])
webhook_router.include_router(github.router, prefix="/github", tags=["webhooks"])
webhook_router.include_router(events.router, prefix="/events", tags=["webhooks"])
# Any other work tracker (Linear…): verified with its own scheme + `<PROVIDER>_WEBHOOK_SECRET`.
# Included last so the named routes above win.
webhook_router.include_router(trackers.router, tags=["webhooks"])
