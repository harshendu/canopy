from fastapi import APIRouter, HTTPException, Request, status

from app.core.config import settings
from app.webhooks.security import verify_hmac_sha256

router = APIRouter()


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def github_webhook(request: Request) -> dict:
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")
    if not verify_hmac_sha256(settings.GITHUB_WEBHOOK_SECRET, body, signature):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bad signature")
    event = request.headers.get("X-GitHub-Event", "unknown")
    # GitHub content is read on-demand; we just acknowledge the event for the slice.
    return {"received": event}
