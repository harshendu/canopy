"""Importing this package registers all connector implementations."""

from app.connectors import gdrive, github, jira  # noqa: F401
from app.connectors.base import Connector, SyncResult, get_connector

__all__ = ["Connector", "SyncResult", "get_connector"]
