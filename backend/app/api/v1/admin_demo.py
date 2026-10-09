"""Admin: demo / seeded-data controls (local & dev only).

Reset to empty and reload the full demo dataset from the UI. The destructive actions are
double-gated: the caller must be an admin **and** ``DEMO_MODE`` must be on, so they can never
run against a production database. The reset keeps the acting admin + the configured superuser
logged in (everything else, including other users, is wiped and re-seeded).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlmodel import select

from app.api.deps import AdminUser, DemoModeGuard, SessionDep
from app.core.config import settings
from app.models.user import User
from app.schemas.admin import DemoAccountRead, DemoDatasetRead, DemoPublic, DemoStatus
from app.services import seed

router = APIRouter()


def _accounts() -> list[DemoAccountRead]:
    return [
        DemoAccountRead(email=a.email, full_name=a.full_name, role=a.role, function=a.function)
        for a in seed.demo_accounts()
    ]


def _datasets() -> list[DemoDatasetRead]:
    return [
        DemoDatasetRead(key=d.key, name=d.name, description=d.description)
        for d in seed.DATASETS.values()
    ]


def _pick_dataset(key: str | None) -> seed.Dataset:
    try:
        return seed.get_dataset(key)
    except KeyError:
        raise HTTPException(
            status_code=400, detail=f"Unknown demo dataset {key!r}"
        ) from None


async def _keep_user_ids(session: SessionDep, admin: User) -> set[int]:
    """Users to preserve across a reset: the acting admin + the configured superuser."""
    ids: set[int] = set()
    if admin.id is not None:
        ids.add(admin.id)
    if settings.FIRST_SUPERUSER_EMAIL:
        row = (
            await session.execute(
                select(User).where(User.email == settings.FIRST_SUPERUSER_EMAIL)
            )
        ).scalar_one_or_none()
        if row is not None and row.id is not None:
            ids.add(row.id)
    return ids


async def _status(session: SessionDep) -> DemoStatus:
    counts = await seed.seed_summary(session)
    on = settings.DEMO_MODE
    return DemoStatus(
        demo_mode=on,
        seeded=counts.get("projects", 0) > 0,
        counts=counts,
        password=seed.DEMO_PASSWORD if on else None,
        accounts=_accounts() if on else [],
        dataset=settings.DEMO_DATASET if on else None,
        datasets=_datasets() if on else [],
    )


@router.get("/demo/public", response_model=DemoPublic)
async def demo_public() -> DemoPublic:
    """Unauthenticated: lets the login screen show the demo accounts when demo mode is on."""
    if not settings.DEMO_MODE:
        return DemoPublic(demo_mode=False)
    return DemoPublic(demo_mode=True, password=seed.DEMO_PASSWORD, accounts=_accounts())


@router.get("/demo/status", response_model=DemoStatus)
async def demo_status(session: SessionDep, _: AdminUser) -> DemoStatus:
    return await _status(session)


@router.post("/demo/reseed", response_model=DemoStatus)
async def demo_reseed(
    session: SessionDep,
    admin: AdminUser,
    __: DemoModeGuard,
    dataset: str | None = Query(default=None, description="Seed narrative key (see status)"),
) -> DemoStatus:
    """Wipe + rebuild. ``dataset`` picks the narrative; default is ``DEMO_DATASET``."""
    chosen = _pick_dataset(dataset)
    keep = await _keep_user_ids(session, admin)
    await seed.reseed(session, keep, chosen)
    return await _status(session)


@router.post("/demo/clear", response_model=DemoStatus)
async def demo_clear(session: SessionDep, admin: AdminUser, __: DemoModeGuard) -> DemoStatus:
    keep = await _keep_user_ids(session, admin)
    await seed.clear_all_data(session, keep)
    return await _status(session)
