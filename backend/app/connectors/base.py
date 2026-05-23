"""Pluggable connector interface + registry."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt_token
from app.models.base import Provider
from app.models.integration import Connection


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

    def __init__(self, connection: Connection, session: AsyncSession) -> None:
        self.connection = connection
        self.session = session
        self.config = connection.config or {}

    def access_token(self) -> str | None:
        if self.connection.encrypted_token:
            return decrypt_token(self.connection.encrypted_token)
        return None

    @abstractmethod
    async def full_sync(self) -> SyncResult: ...

    @abstractmethod
    async def incremental_sync(self, since: str | None = None) -> SyncResult: ...

    async def handle_webhook(self, payload: dict) -> SyncResult:
        raise NotImplementedError(f"{self.provider} does not handle webhooks")


_REGISTRY: dict[Provider, type[Connector]] = {}


def register(provider: Provider) -> Callable[[type[Connector]], type[Connector]]:
    def deco(cls: type[Connector]) -> type[Connector]:
        cls.provider = provider
        _REGISTRY[provider] = cls
        return cls

    return deco


def get_connector(connection: Connection, session: AsyncSession) -> Connector:
    try:
        cls = _REGISTRY[connection.provider]
    except KeyError as exc:  # pragma: no cover - defensive
        raise ValueError(f"No connector registered for {connection.provider}") from exc
    return cls(connection, session)
