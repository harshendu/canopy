"""Shared test setup for tracker connections (USER_FLOWS §J0).

A tracker connection feeds what its `TrackerBinding` rows say: a project binding mirrors one
canopy project from a scope in the tracker (for Jira, a project key), the way creating the
connection with `project_id` does through the API.
"""

from __future__ import annotations

from typing import Any

from app.core.crypto import encrypt_token
from app.models.base import Provider, TrackingMode
from app.models.integration import Connection, TrackerBinding
from app.models.project import Project


async def bind_project(
    session: Any,
    connection: Connection,
    project_id: int,
    scope: dict[str, Any] | None = None,
    **fields: Any,
) -> TrackerBinding:
    """A project binding from `connection` to `project_id`; the project becomes mirrored."""
    assert connection.id is not None
    binding = TrackerBinding(
        connection_id=connection.id,
        provider=connection.provider,
        target_type="project",
        target_id=project_id,
        scope=scope or {},
        **fields,
    )
    session.add(binding)
    project = await session.get(Project, project_id)
    if project is not None:
        project.tracking_mode = TrackingMode.mirrored.value
    await session.flush()
    return binding


async def jira_connection(
    session: Any,
    project_id: int | None = None,
    *,
    project_key: str = "PLAT",
    config: dict[str, Any] | None = None,
    scope: dict[str, Any] | None = None,
    commit: bool = False,
) -> Connection:
    """A token-authorized Jira connection, bound to `project_id` (scope: its project key)."""
    connection = Connection(
        provider=Provider.jira,
        name="jira",
        encrypted_token=encrypt_token("api-token"),
        config={
            "base_url": "https://example.atlassian.net",
            "email": "a@b.com",
            "jira_project_key": project_key,
            **(config or {}),
        },
    )
    session.add(connection)
    await session.flush()
    if project_id is not None:
        await bind_project(
            session, connection, project_id, scope or {"project_key": project_key}
        )
    if commit:
        await session.commit()
    return connection
