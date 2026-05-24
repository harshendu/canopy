import pytest
from sqlmodel import func, select

from app.connectors.jira import JiraConnector
from app.core.crypto import encrypt_token
from app.models.base import Provider, TaskType
from app.models.integration import Connection, ExternalRef, JiraLink
from app.models.project import Initiative, Project, Task
from app.services import jira_linking


async def _connection(session, project_id: int = 1) -> Connection:
    connection = Connection(
        provider=Provider.jira,
        name="jira",
        encrypted_token=encrypt_token("api-token"),
        config={
            "base_url": "https://example.atlassian.net",
            "email": "a@b.com",
            "project_id": project_id,
            "jira_project_key": "PLAT",
        },
    )
    session.add(connection)
    await session.flush()
    return connection


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
    connector = JiraConnector(await _connection(db_session, project.id), db_session)

    issues = [
        _issue("100", "PLAT-1", "Epic"),
        _issue("101", "PLAT-2", "Story", parent_id="100"),
        _issue("102", "PLAT-3", "Story", parent_id="100"),
    ]
    result = await connector.map_subtree_into_project(issues, project.id)

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
    connector = JiraConnector(await _connection(db_session, project.id), db_session)
    issues = [_issue("100", "PLAT-1", "Epic"), _issue("101", "PLAT-2", "Story", parent_id="100")]

    await connector.map_subtree_into_project(issues, project.id)
    again = await connector.map_subtree_into_project(issues, project.id)

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
    connector = JiraConnector(await _connection(db_session), db_session)

    issues = [
        _issue("1", "INIT-1", "Initiative"),  # anchor — above epic level
        _issue("10", "EPIC-1", "Epic", parent_id="1"),
        _issue("11", "EPIC-2", "Epic", parent_id="1"),
        _issue("100", "STORY-1", "Story", parent_id="10"),
        _issue("101", "STORY-2", "Story", parent_id="10"),
        _issue("102", "STORY-3", "Story", parent_id="11"),
        _issue("1000", "SUB-1", "Sub-task", parent_id="100"),
    ]
    result = await connector.map_subtree_into_initiative(issues, initiative.id)

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
    connector = JiraConnector(await _connection(db_session), db_session)
    issues = [_issue("10", "EPIC-1", "Epic"), _issue("100", "STORY-1", "Story", parent_id="10")]

    await connector.map_subtree_into_initiative(issues, initiative.id)
    again = await connector.map_subtree_into_initiative(issues, initiative.id)

    assert again.projects_created == 0
    assert again.projects_linked == 1
    project_count = (
        await db_session.execute(select(func.count()).select_from(Project))
    ).scalar()
    assert project_count == 1


# --- service: create a link (orchestration + persistence) ---
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
    connection = await _connection(db_session, project.id)
    assert connection.id is not None
    _patch_jira(
        monkeypatch,
        [_issue("100", "PLAT-1", "Epic"), _issue("101", "PLAT-2", "Story", parent_id="100")],
    )

    result = await jira_linking.create_or_sync_link(
        db_session,
        connection_id=connection.id,
        jira_key="PLAT-1",
        target_type="project",
        target_id=project.id,
    )

    assert result.tasks_created == 2
    assert result.link.target_type == "project"
    link = (await db_session.execute(select(JiraLink))).scalar_one()
    assert link.jira_issue_id == "100"
    assert link.jira_issue_type == "Epic"
    assert link.last_synced_at is not None


@pytest.mark.asyncio
async def test_create_link_rejects_missing_target(db_session, monkeypatch):
    connection = await _connection(db_session)
    assert connection.id is not None
    _patch_jira(monkeypatch, [_issue("100", "PLAT-1", "Epic")])

    with pytest.raises(jira_linking.JiraLinkError):
        await jira_linking.create_or_sync_link(
            db_session,
            connection_id=connection.id,
            jira_key="PLAT-1",
            target_type="project",
            target_id=999,
        )


@pytest.mark.asyncio
async def test_resync_link_is_idempotent(db_session, monkeypatch):
    project = Project(key="PLAT", name="Platform")
    db_session.add(project)
    await db_session.flush()
    connection = await _connection(db_session, project.id)
    assert connection.id is not None
    _patch_jira(monkeypatch, [_issue("100", "PLAT-1", "Story")])

    created = await jira_linking.create_or_sync_link(
        db_session,
        connection_id=connection.id,
        jira_key="PLAT-1",
        target_type="project",
        target_id=project.id,
    )
    resynced = await jira_linking.resync_link(db_session, created.link.id)

    assert created.tasks_created == 1
    assert resynced.skipped == 1
    link_count = (await db_session.execute(select(func.count()).select_from(JiraLink))).scalar()
    assert link_count == 1
