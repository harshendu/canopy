"""Pluggable connector interface + registry."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt_token, encrypt_token
from app.models.base import Provider, utcnow
from app.models.integration import Connection, UserConnection

_REFRESH_SKEW_SECONDS = 60


class EffectiveCredential:
    """A user's personal token (a `UserConnection`) layered over a shared integration's config
    (its parent `Connection`). Connectors run against this to act *as the user* without
    duplicating the target config: `provider`/`config` are read from the parent connection,
    while the token, refresh token, expiry, and watermark read and **write through to the
    `UserConnection` row** (so token rotation and the per-user incremental cursor persist there,
    not on the shared connection)."""

    def __init__(self, connection: Connection, user_connection: UserConnection) -> None:
        self._connection = connection
        self._user = user_connection

    @property
    def provider(self) -> Provider:
        return self._connection.provider

    @property
    def config(self) -> dict:
        return self._connection.config

    @property
    def encrypted_token(self) -> str | None:
        return self._user.encrypted_token

    @encrypted_token.setter
    def encrypted_token(self, value: str | None) -> None:
        self._user.encrypted_token = value

    @property
    def encrypted_refresh_token(self) -> str | None:
        return self._user.encrypted_refresh_token

    @encrypted_refresh_token.setter
    def encrypted_refresh_token(self, value: str | None) -> None:
        self._user.encrypted_refresh_token = value

    @property
    def token_expires_at(self) -> datetime | None:
        return self._user.token_expires_at

    @token_expires_at.setter
    def token_expires_at(self, value: datetime | None) -> None:
        self._user.token_expires_at = value

    @property
    def watermark(self) -> str | None:
        return self._user.watermark

    @watermark.setter
    def watermark(self, value: str | None) -> None:
        self._user.watermark = value


# What a connector can run against: a shared Connection, or a user's token over a shared config.
Credential = Connection | EffectiveCredential


@dataclass
class SyncResult:
    provider: str
    created: int = 0
    updated: int = 0
    skipped: int = 0
    watermark: str | None = None

    def merge(self, other: SyncResult) -> SyncResult:
        self.created += other.created
        self.updated += other.updated
        self.skipped += other.skipped
        self.watermark = other.watermark or self.watermark
        return self


class Connector(ABC):
    provider: Provider

    def __init__(self, connection: Credential, session: AsyncSession) -> None:
        self.connection = connection
        self.session = session
        self.config = connection.config or {}

    def access_token(self) -> str | None:
        if self.connection.encrypted_token:
            return decrypt_token(self.connection.encrypted_token)
        return None

    def _client(self) -> httpx.AsyncClient:
        raise NotImplementedError

    async def open_client(self) -> httpx.AsyncClient:
        """Refresh the OAuth token if needed, then build the connector's HTTP client.

        In demo mode a connection flagged ``config.demo`` is served by an in-process HTTP
        mock (no network), so the whole UI works offline."""
        from app.connectors.demo import demo_client, is_demo_connection

        if is_demo_connection(self):
            return demo_client(self)
        await self.ensure_fresh_token()
        return self._client()

    async def ensure_fresh_token(self) -> None:
        """Refresh an expired OAuth access token using the stored refresh token (with rotation)."""
        if not self.connection.encrypted_refresh_token:
            return
        expires_at = self.connection.token_expires_at
        if expires_at is not None:
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at > datetime.now(UTC) + timedelta(seconds=_REFRESH_SKEW_SECONDS):
                return

        from app.connectors.oauth import refresh_access_token

        refresh = decrypt_token(self.connection.encrypted_refresh_token)
        tokens = await refresh_access_token(self.provider, refresh)
        self.connection.encrypted_token = encrypt_token(tokens.access_token)
        if tokens.refresh_token:  # providers like Jira rotate the refresh token
            self.connection.encrypted_refresh_token = encrypt_token(tokens.refresh_token)
        if tokens.expires_in:
            self.connection.token_expires_at = utcnow() + timedelta(
                seconds=tokens.expires_in
            )
        await self.session.commit()

    @abstractmethod
    async def full_sync(self) -> SyncResult: ...

    @abstractmethod
    async def incremental_sync(self, since: str | None = None) -> SyncResult: ...

    async def handle_webhook(self, payload: dict[str, Any]) -> SyncResult:
        raise NotImplementedError(f"{self.provider} does not handle webhooks")


_REGISTRY: dict[Provider, type[Connector]] = {}


def register(provider: Provider) -> Callable[[type[Connector]], type[Connector]]:
    def deco(cls: type[Connector]) -> type[Connector]:
        cls.provider = provider
        _REGISTRY[provider] = cls
        return cls

    return deco


def get_connector(connection: Credential, session: AsyncSession) -> Connector:
    try:
        cls = _REGISTRY[connection.provider]
    except KeyError as exc:  # pragma: no cover - defensive
        raise ValueError(f"No connector registered for {connection.provider}") from exc
    return cls(connection, session)
