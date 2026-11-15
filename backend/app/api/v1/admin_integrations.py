"""Admin: the per-provider integration policy (how reads/writes flow).

One row per provider in `IntegrationSetting`; a missing row reads back as the default
(direct/direct). The enforcement lives in `app/services/integration_policy.py` and the
read/write call sites that consult it.
"""

from fastapi import APIRouter
from sqlmodel import select

from app.api.deps import AdminUser, HumanOnly, SessionDep
from app.connectors.tracker import is_tracker, tracker_enabled
from app.models.base import Provider
from app.models.integration import Connection, IntegrationSetting
from app.schemas.integration import IntegrationSettingRead, IntegrationSettingUpdate

router = APIRouter()


@router.get("/integrations", response_model=list[IntegrationSettingRead])
async def list_integration_settings(
    session: SessionDep, _: AdminUser
) -> list[IntegrationSettingRead]:
    rows = (await session.execute(select(IntegrationSetting))).scalars().all()
    by_provider = {r.provider: r for r in rows}
    in_use = {
        c.provider for c in (await session.execute(select(Connection))).scalars().all()
    }
    # Synthesize the default (direct/direct) for any provider without a stored row. Trackers
    # are listed when this instance enables them (TRACKERS_ENABLED) or has a connection to one;
    # the Claude artifact sync (opt-in, §V11) once a connection to it exists.
    return [
        IntegrationSettingRead.model_validate(
            by_provider.get(provider) or IntegrationSetting(provider=provider)
        )
        for provider in Provider
        if provider in in_use
        or provider in by_provider
        or (provider != Provider.claude and (not is_tracker(provider) or tracker_enabled(provider)))
    ]


@router.patch("/integrations/{provider}", response_model=IntegrationSettingRead)
async def update_integration_setting(
    session: SessionDep, _: AdminUser, __: HumanOnly, provider: Provider,
    payload: IntegrationSettingUpdate,
) -> IntegrationSettingRead:
    row = (
        await session.execute(
            select(IntegrationSetting).where(IntegrationSetting.provider == provider)
        )
    ).scalar_one_or_none()
    if row is None:
        row = IntegrationSetting(provider=provider)
        session.add(row)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    await session.commit()
    await session.refresh(row)
    return IntegrationSettingRead.model_validate(row)
