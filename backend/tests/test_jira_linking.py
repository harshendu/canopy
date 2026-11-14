"""Linking a Jira item and its subtree into canopy (USER_FLOWS §J9): epics → summary tasks
(stories under them) in a project, or epics → projects of an initiative. The Jira connector
normalizes the raw issues; the sync engine maps them; a link is a subtree `TrackerBinding`."""

from typing import Any

import pytest
from sqlmodel import func, select

from app.connectors.jira import JiraConnector
from app.models.base import Provider, TaskType
from app.models.integration import ExternalRef, TrackerBinding
from app.models.project import Initiative, Project, Task
from app.services import tracker_links, tracker_sync
from tests.helpers import jira_connection


async def _map(
    session, connector: JiraConnector, issues: list[dict[str, Any]], target_type: str,
    target_id: int,
) -> tracker_sync.LinkMapResult:
    return await tracker_sync.map_subtree(
        session,
        provider=Provider.jira,
        connection_id=connector.connection_id,
        items=[connector.normalize(i) for i in issues],
        target_type=target_type,
        target_id=target_id,
    )


def _issue(
    ext_id: str,
    key: str,
    issuetype: str,
    updated: str = "2026-05-01T10:00:00.000+0000",
    parent_id: str | None = None,
) -> dict:
    fields: dict = {
        "summary": f"Issue {key}",
        "status": {"name": "To Do"},
        "issuetype": {"name": issuetype},
        "updated": updated,
    }
    if parent_id:
        fields["parent"] = {"id": parent_id}
    return {"id": ext_id, "key": key, "fields": fields}


async def _ref_entity(session, ext_id: str, entity_type: str) -> int:
    ref = (
        await session.execute(
            select(ExternalRef).where(
                ExternalRef.external_id == ext_id, ExternalRef.entity_type == entity_type
            )
        )
    ).scalar_one()
    return ref.entity_id


# --- mapping a subtree into a project (epic → summary task, stories → leaf tasks) ---
@pytest.mark.asyncio
async def test_map_subtree_into_project_wires_parents(db_session):
    project = Project(key="PLAT", name="Platform")
    db_session.add(project)
    await db_session.flush()
    connector = JiraConnector(await jira_connection(db_session), db_session)

    issues = [
        _issue("100", "PLAT-1", "Epic"),
        _issue("101", "PLAT-2", "Story", parent_id="100"),
        _issue("102", "PLAT-3", "Story", parent_id="100"),
    ]
    result = await _map(db_session, connector, issues, "project", project.id)

    assert result.tasks_created == 3
    epic = await db_session.get(Task, await _ref_entity(db_session, "100", "task"))
    story = await db_session.get(Task, await _ref_entity(db_session, "101", "task"))
    assert epic.type == TaskType.summary
    assert epic.project_id == project.id
    assert story.type == TaskType.task
    assert story.parent_id == epic.id


@pytest.mark.asyncio
async def test_map_subtree_into_project_is_idempotent(db_session):
    project = Project(key="PLAT", name="Platform")
    db_session.add(project)
    await db_session.flush()
    connector = JiraConnector(await jira_connection(db_session), db_session)
    issues = [_issue("100", "PLAT-1", "Epic"), _issue("101", "PLAT-2", "Story", parent_id="100")]

    await _map(db_session, connector, issues, "project", project.id)
    again = await _map(db_session, connector, issues, "project", project.id)

    assert again.skipped == 2  # same `updated` → not stale
    assert again.tasks_created == 0
    task_count = (await db_session.execute(select(func.count()).select_from(Task))).scalar()
    assert task_count == 2


# --- mapping a subtree into an initiative (epics → projects, stories → tasks) ---
@pytest.mark.asyncio
async def test_map_subtree_into_initiative_creates_projects(db_session):
    initiative = Initiative(key="Q3", name="Q3 Program")
    db_session.add(initiative)
    await db_session.flush()
    connector = JiraConnector(await jira_connection(db_session), db_session)

    issues = [
        _issue("1", "INIT-1", "Initiative"),  # anchor — above epic level
        _issue("10", "EPIC-1", "Epic", parent_id="1"),
        _issue("11", "EPIC-2", "Epic", parent_id="1"),
        _issue("100", "STORY-1", "Story", parent_id="10"),
        _issue("101", "STORY-2", "Story", parent_id="10"),
        _issue("102", "STORY-3", "Story", parent_id="11"),
        _issue("1000", "SUB-1", "Sub-task", parent_id="100"),
    ]
    result = await _map(db_session, connector, issues, "initiative", initiative.id)

    assert result.projects_created == 2
    assert result.tasks_created == 4  # 3 stories + 1 sub-task
    assert result.skipped == 1  # the initiative anchor has no epic ancestor

    projects = (
        await db_session.execute(
            select(Project).where(Project.initiative_id == initiative.id)
        )
    ).scalars().all()
    assert len(projects) == 2

    epic1_project = await _ref_entity(db_session, "10", "project")
    story1 = await db_session.get(Task, await _ref_entity(db_session, "100", "task"))
    sub1 = await db_session.get(Task, await _ref_entity(db_session, "1000", "task"))
    assert story1.project_id == epic1_project
    assert story1.parent_id is None  # parent is the epic (the project itself) → top-level
    assert sub1.parent_id == story1.id  # sub-task nests under its story in the same project
    # the initiative anchor is never turned into a task
    assert (
        await db_session.execute(
            select(ExternalRef).where(ExternalRef.external_id == "1")
        )
    ).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_map_subtree_into_initiative_is_idempotent(db_session):
    initiative = Initiative(key="Q3", name="Q3 Program")
    db_session.add(initiative)
    await db_session.flush()
    connector = JiraConnector(await jira_connection(db_session), db_session)
    issues = [_issue("10", "EPIC-1", "Epic"), _issue("100", "STORY-1", "Story", parent_id="10")]

    await _map(db_session, connector, issues, "initiative", initiative.id)
    again = await _map(db_session, connector, issues, "initiative", initiative.id)

    assert again.projects_created == 0
    assert again.projects_linked == 1
    project_count = (
        await db_session.execute(select(func.count()).select_from(Project))
    ).scalar()
    assert project_count == 1


# --- service: create a link (orchestration + persistence as a subtree binding) ---
def _patch_jira(monkeypatch, tree: list[dict]) -> None:
    async def fake_get_issue(self, key_or_id):
        return tree[0]

    async def fake_fetch(self, root_key):
        return tree

    monkeypatch.setattr(JiraConnector, "get_issue", fake_get_issue)
    monkeypatch.setattr(JiraConnector, "fetch_descendant_tree", fake_fetch)


@pytest.mark.asyncio
async def test_create_link_into_project_persists_link(db_session, monkeypatch):
    project = Project(key="PLAT", name="Platform")
    db_session.add(project)
    await db_session.flush()
    connection = await jira_connection(db_session)
    assert connection.id is not None
    _patch_jira(
        monkeypatch,
        [_issue("100", "PLAT-1", "Epic"), _issue("101", "PLAT-2", "Story", parent_id="100")],
    )

    binding, result = await tracker_links.create_or_sync(
        db_session,
        connection_id=connection.id,
        root_key="PLAT-1",
        target_type="project",
        target_id=project.id,
    )

    assert result.tasks_created == 2
    assert binding.target_type == "project"
    link = (await db_session.execute(select(TrackerBinding))).scalar_one()
    assert (link.provider, link.scope_kind) == (Provider.jira, "subtree")
    assert link.scope["root_id"] == "100"
    assert link.scope["root_type"] == "Epic"
    assert link.last_synced_at is not None


@pytest.mark.asyncio
async def test_create_link_rejects_missing_target(db_session, monkeypatch):
    connection = await jira_connection(db_session)
    assert connection.id is not None
    _patch_jira(monkeypatch, [_issue("100", "PLAT-1", "Epic")])

    with pytest.raises(tracker_links.TrackerLinkError):
        await tracker_links.create_or_sync(
            db_session,
            connection_id=connection.id,
            root_key="PLAT-1",
            target_type="project",
            target_id=999,
        )


@pytest.mark.asyncio
async def test_resync_link_is_idempotent(db_session, monkeypatch):
    project = Project(key="PLAT", name="Platform")
    db_session.add(project)
    await db_session.flush()
    connection = await jira_connection(db_session)
    assert connection.id is not None
    _patch_jira(monkeypatch, [_issue("100", "PLAT-1", "Story")])

    link, created = await tracker_links.create_or_sync(
        db_session,
        connection_id=connection.id,
        root_key="PLAT-1",
        target_type="project",
        target_id=project.id,
    )
    assert link.id is not None
    _, resynced = await tracker_links.resync(db_session, link.id)

    assert created.tasks_created == 1
    assert resynced.skipped == 1
    link_count = (
        await db_session.execute(select(func.count()).select_from(TrackerBinding))
    ).scalar()
    assert link_count == 1
