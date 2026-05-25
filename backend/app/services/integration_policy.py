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

from app.connectors.base import Credential, EffectiveCredential
from app.models.base import Provider, ReadStrategy, WriteStrategy
from app.models.integration import Connection, IntegrationSetting, UserConnection


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


# --- per-user (SSO) credential selection (Phase 2) ---
async def usable_user_connection(
    session: AsyncSession, connection_id: int, user_id: int
) -> UserConnection | None:
    """The caller's active, authorized personal credential attached to a connection, if any."""
    row = (
        await session.execute(
            select(UserConnection).where(
                UserConnection.connection_id == connection_id,
                UserConnection.user_id == user_id,
                col(UserConnection.active).is_(True),
            )
        )
    ).scalar_one_or_none()
    return row if (row is not None and row.authorized) else None


async def resolve_read_credential(
    session: AsyncSession, connection: Connection, user_id: int | None
) -> Credential | None:
    """The credential to read `connection` with, honoring policy + user-first precedence.

    Background reads (`user_id=None`, e.g. the poll) use the shared service token. A user's read
    prefers **their own** credential when `allow_user_connect` is on (each per-user credential
    carries its own watermark, so a narrow-access pull can't disturb the service cursor or remove
    what the service token populated), falling back to the shared token. Returns None when reads
    aren't direct, or no usable credential exists.
    """
    setting = await get_setting(session, connection.provider)
    if not reads_direct(setting):
        return None
    if user_id is not None and setting.allow_user_connect and connection.id is not None:
        user_conn = await usable_user_connection(session, connection.id, user_id)
        if user_conn is not None:
            return EffectiveCredential(connection, user_conn)
    return connection if connection.authorized else None


async def resolve_write_credential(
    session: AsyncSession, connection: Connection, user_id: int | None
) -> tuple[Credential | None, str]:
    """The credential to write `connection` with (user-first for attribution, else the shared
    token). Returns `(credential, reason)`; `credential` is None when the write is blocked, and
    `reason` explains why (policy, or no usable credential)."""
    check = await resolve_write(session, connection.provider)
    if not check.allowed:
        return None, check.reason
    setting = await get_setting(session, connection.provider)
    if user_id is not None and setting.allow_user_connect and connection.id is not None:
        user_conn = await usable_user_connection(session, connection.id, user_id)
        if user_conn is not None:
            return EffectiveCredential(connection, user_conn), "user"
    if connection.authorized:
        return connection, "shared"
    return None, f"no usable {connection.provider.value} credentials available for a direct write"
