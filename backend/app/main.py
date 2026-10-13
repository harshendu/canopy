import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.api.v1 import api_router
from app.core.config import settings
from app.core.db import async_session_factory, get_session
from app.core.logging import configure_logging
from app.core.security import hash_password
from app.core.startup_checks import (
    InsecureConfigError,
    ensure_safe_first_superuser_password,
    ensure_secure_secret_key,
)
from app.models.base import UserRole
from app.models.user import User
from app.webhooks import webhook_router

configure_logging()
logger = logging.getLogger(__name__)


async def _seed_superuser() -> None:
    if not (settings.FIRST_SUPERUSER_EMAIL and settings.FIRST_SUPERUSER_PASSWORD):
        return
    try:
        async with async_session_factory() as session:
            existing = await session.execute(
                select(User).where(User.email == settings.FIRST_SUPERUSER_EMAIL)
            )
            if existing.scalar_one_or_none() is None:
                ensure_safe_first_superuser_password()
                session.add(
                    User(
                        email=settings.FIRST_SUPERUSER_EMAIL,
                        hashed_password=hash_password(settings.FIRST_SUPERUSER_PASSWORD),
                        full_name="Architect",
                        role=UserRole.admin,
                    )
                )
                await session.commit()
                logger.info("Seeded first superuser email=%s", settings.FIRST_SUPERUSER_EMAIL)
    except InsecureConfigError:
        raise
    except Exception:  # pragma: no cover - DB may be unreachable/unmigrated at startup
        logger.warning(
            "Skipped first-superuser seeding: the database could not be accessed. "
            "If you cannot log in, ensure migrations have run (`alembic upgrade head`).",
            exc_info=True,
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    ensure_secure_secret_key()
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
    return {"status": "ok", "service": settings.PROJECT_NAME, "demo_mode": settings.DEMO_MODE}


@app.get("/api/v1/health/ready", tags=["health"])
async def ready(session: Annotated[AsyncSession, Depends(get_session)]) -> dict:
    """Readiness probe: verifies the database is reachable."""
    await session.execute(text("SELECT 1"))
    return {"status": "ready"}
