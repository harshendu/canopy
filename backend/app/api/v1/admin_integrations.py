"""Admin: the per-provider integration policy (how reads/writes flow).

One row per provider in `IntegrationSetting`; a missing row reads back as the default
(direct/direct). The enforcement lives in `app/services/integration_policy.py` and the
read/write call sites that consult it.
"""

from fastapi import APIRouter
from sqlmodel import select

from app.api.deps import AdminUser, HumanOnly, SessionDep
from app.models.base import Provider
from app.models.integration import IntegrationSetting
from app.schemas.integration import IntegrationSettingRead, IntegrationSettingUpdate

router = APIRouter()


@router.get("/integrations", response_model=list[IntegrationSettingRead])
async def list_integration_settings(
    session: SessionDep, _: AdminUser
) -> list[IntegrationSettingRead]:
    rows = (await session.execute(select(IntegrationSetting))).scalars().all()
    by_provider = {r.provider: r for r in rows}
    # Synthesize the default (direct/direct) for any provider without a stored row.
    return [
        IntegrationSettingRead.model_validate(
            by_provider.get(provider) or IntegrationSetting(provider=provider)
        )
        for provider in Provider
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
