"""Per-provider integration policy resolver.

An admin chooses, per provider, *how* reads and writes flow (the `IntegrationSetting` row).
The **absence** of a row means the default — direct reads + direct writes (canopy uses its own
credentials) — so behavior is unchanged until an admin opts in. Everything that decides whether
to read a provider directly, or whether a direct write is permitted, routes through here so the
policy lives in one place.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.models.base import Provider, ReadStrategy, WriteStrategy
from app.models.integration import Connection, IntegrationSetting


async def get_setting(session: AsyncSession, provider: Provider) -> IntegrationSetting:
    """The stored policy for a provider, or an in-memory default (never persisted on read)."""
    row = (
        await session.execute(
            select(IntegrationSetting).where(IntegrationSetting.provider == provider)
        )
    ).scalar_one_or_none()
    return row or IntegrationSetting(provider=provider)


async def usable_direct_connections(
    session: AsyncSession, provider: Provider
) -> list[Connection]:
    """Active connections that hold usable credentials (a stored token) for `provider`.

    This is the concrete meaning of "canopy holds usable credentials" — an active connection
    whose token has been stored. Used by the direct read path (the reconciliation poll).
    """
    rows = await session.execute(
        select(Connection).where(
            Connection.provider == provider, col(Connection.active).is_(True)
        )
    )
    return [c for c in rows.scalars().all() if c.authorized]


def reads_direct(setting: IntegrationSetting) -> bool:
    """Whether canopy should read this provider directly (poll / accept its webhooks).

    `mcp`/`file` read strategies mean canopy does not call the provider API — data arrives via
    Claude over MCP or a file drop — so the poll and webhook intake stand down.
    """
    return setting.read_strategy == ReadStrategy.direct


@dataclass(frozen=True)
class WriteCheck:
    """The outcome of checking whether a *direct* write to a provider is permitted by policy."""

    allowed: bool
    reason: str


async def resolve_write(session: AsyncSession, provider: Provider) -> WriteCheck:
    """Whether canopy may write to `provider` directly, per the admin's write strategy.

    `direct` is allowed (the caller still resolves/validates the specific connection); `mcp`
    routes the write through Claude (the direct path refuses); `disabled` blocks writes.
    """
    setting = await get_setting(session, provider)
    if setting.write_strategy == WriteStrategy.disabled:
        return WriteCheck(False, f"{provider.value} writes are disabled by integration policy")
    if setting.write_strategy == WriteStrategy.mcp:
        return WriteCheck(
            False,
            f"{provider.value} writes are routed via MCP/Claude by integration policy; "
            "the direct write path is disabled",
        )
    return WriteCheck(True, "direct")
