import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse

from app.core.events import subscribe
from app.core.security import decode_access_token

router = APIRouter()


@router.get("/stream")
async def stream(token: str) -> StreamingResponse:
    """SSE for live UI refresh. Auth via `?token=` since EventSource can't set headers."""
    if not decode_access_token(token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    async def gen() -> AsyncIterator[str]:
        yield ": connected\n\n"
        async for event in subscribe():
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
