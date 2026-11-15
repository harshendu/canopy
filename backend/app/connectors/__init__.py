"""Importing this package registers all connector implementations."""

from app.connectors import (  # noqa: F401
    claude_artifacts,
    gdrive,
    generic,
    github,
    jira,
    linear,
)
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
