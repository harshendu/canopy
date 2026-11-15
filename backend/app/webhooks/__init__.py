from fastapi import APIRouter

from app.webhooks import events, github, trackers

webhook_router = APIRouter()
webhook_router.include_router(github.router, prefix="/github", tags=["webhooks"])
webhook_router.include_router(events.router, prefix="/events", tags=["webhooks"])
# Every work tracker (Jira, Linear, generic…) at /webhooks/{provider}: verified with its own
# scheme + `<PROVIDER>_WEBHOOK_SECRET`. Included last so the named routes above win.
webhook_router.include_router(trackers.router, tags=["webhooks"])
