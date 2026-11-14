"""Importing this package registers all connector implementations."""

from app.connectors import gdrive, generic, github, jira, linear  # noqa: F401
from app.connectors.base import (
    Connector,
    Credential,
    EffectiveCredential,
    SyncResult,
    get_connector,
)

__all__ = [
    "Connector",
    "Credential",
    "EffectiveCredential",
    "SyncResult",
    "get_connector",
]
