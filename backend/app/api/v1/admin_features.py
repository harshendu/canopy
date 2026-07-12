"""Admin: feature gates — turn app surfaces on/off at group or feature level.

The catalog (keys, labels, grouping) lives in `app/services/features.py`; a `FeatureFlag` row
is stored only as an override (missing row = enabled). Enforcement is `require_feature` /
`FeatureGate` on the gated routers/endpoints; the UI reads `GET /features` and hides gated
surfaces live (every toggle publishes a `features` SSE event).
"""

from fastapi import APIRouter, HTTPException, status
from sqlmodel import select

from app.api.deps import AdminUser, SessionDep
from app.core.events import publish
from app.models.feature import FeatureFlag
from app.schemas.admin import FeatureGateRead, FeatureGateUpdate
from app.services.features import (
    FEATURE_CATALOG,
    is_known_feature,
    load_stored_flags,
    resolve_effective,
)

router = APIRouter()


def _gates(stored: dict[str, bool]) -> list[FeatureGateRead]:
    effective = resolve_effective(stored)
    return [
        FeatureGateRead(
            key=f.key,
            label=f.label,
            description=f.description,
            group=f.group,
            enabled=stored.get(f.key, True),
            effective=effective[f.key],
        )
        for f in FEATURE_CATALOG
    ]


@router.get("/features", response_model=list[FeatureGateRead])
async def list_feature_gates(session: SessionDep, _: AdminUser) -> list[FeatureGateRead]:
    return _gates(await load_stored_flags(session))


@router.patch("/features/{key}", response_model=list[FeatureGateRead])
async def update_feature_gate(
    session: SessionDep, _: AdminUser, key: str, payload: FeatureGateUpdate
) -> list[FeatureGateRead]:
    """Toggle one gate and return the full refreshed list (a group flip changes children's
    effective state, so the caller needs the whole picture)."""
    if not is_known_feature(key):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown feature")
    row = (
        await session.execute(select(FeatureFlag).where(FeatureFlag.key == key))
    ).scalar_one_or_none()
    if row is None:
        row = FeatureFlag(key=key)
        session.add(row)
    row.enabled = payload.enabled
    await session.commit()
    await publish({"type": "features", "key": key, "enabled": payload.enabled})
    return _gates(await load_stored_flags(session))
