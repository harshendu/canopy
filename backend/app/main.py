from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import select

from app.api.v1 import api_router
from app.core.config import settings
from app.core.db import async_session_factory
from app.core.security import hash_password
from app.models.base import UserRole
from app.models.user import User
from app.webhooks import webhook_router


async def _seed_superuser() -> None:
    if not (settings.FIRST_SUPERUSER_EMAIL and settings.FIRST_SUPERUSER_PASSWORD):
        return
    try:
        async with async_session_factory() as session:
            existing = await session.execute(
                select(User).where(User.email == settings.FIRST_SUPERUSER_EMAIL)
            )
            if existing.scalar_one_or_none() is None:
                session.add(
                    User(
                        email=settings.FIRST_SUPERUSER_EMAIL,
                        hashed_password=hash_password(settings.FIRST_SUPERUSER_PASSWORD),
                        full_name="Architect",
                        role=UserRole.admin,
                    )
                )
                await session.commit()
    except Exception:  # pragma: no cover - migrations may not have run yet
        pass


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await _seed_superuser()
    yield


app = FastAPI(title=settings.PROJECT_NAME, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_V1_PREFIX)
app.include_router(webhook_router, prefix="/webhooks")


@app.get("/api/v1/health", tags=["health"])
async def health() -> dict:
    return {"status": "ok", "service": settings.PROJECT_NAME}
