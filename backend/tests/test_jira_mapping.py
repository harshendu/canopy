import pytest
from sqlmodel import func, select

from app.connectors.jira import JiraConnector
from app.core.crypto import encrypt_token
from app.models.base import Provider
from app.models.integration import Connection, ExternalRef
from app.models.project import Project, Task


async def _make_connector(session) -> JiraConnector:
    project = Project(key="PLAT", name="Platform")
    session.add(project)
    await session.flush()
    connection = Connection(
        provider=Provider.jira,
        name="jira",
        encrypted_token=encrypt_token("api-token"),
        config={
            "base_url": "https://example.atlassian.net",
            "email": "a@b.com",
            "project_id": project.id,
            "jira_project_key": "PLAT",
        },
    )
    session.add(connection)
    await session.flush()
    return JiraConnector(connection, session)


def _issue(ext_id: str, key: str, issuetype: str, updated: str, parent_id: str | None = None):
    fields = {
        "summary": f"Issue {key}",
        "status": {"name": "To Do"},
        "issuetype": {"name": issuetype},
        "updated": updated,
    }
    if parent_id:
        fields["parent"] = {"id": parent_id}
    return {"id": ext_id, "key": key, "fields": fields}


@pytest.mark.asyncio
async def test_upsert_is_idempotent(db_session):
    connector = await _make_connector(db_session)
    issue = _issue("10001", "PLAT-1", "Story", "2026-05-01T10:00:00.000+0000")

    action1, _, _ = await connector._upsert_issue(issue)
    await db_session.commit()
    action2, _, _ = await connector._upsert_issue(issue)
    await db_session.commit()

    assert action1 == "created"
    assert action2 == "skipped"  # same `updated` -> not stale
    task_count = (await db_session.execute(select(func.count()).select_from(Task))).scalar()
    ref_count = (await db_session.execute(select(func.count()).select_from(ExternalRef))).scalar()
    assert task_count == 1
    assert ref_count == 1


@pytest.mark.asyncio
async def test_newer_update_refreshes(db_session):
    connector = await _make_connector(db_session)
    await connector._upsert_issue(_issue("10001", "PLAT-1", "Story", "2026-05-01T10:00:00.000+0000"))
    await db_session.commit()
    action, _, _ = await connector._upsert_issue(
        _issue("10001", "PLAT-1", "Story", "2026-05-02T10:00:00.000+0000")
    )
    await db_session.commit()
    assert action == "updated"


@pytest.mark.asyncio
async def test_epic_parent_wiring(db_session):
    connector = await _make_connector(db_session)
    await connector._upsert_issue(_issue("20000", "PLAT-10", "Epic", "2026-05-01T10:00:00.000+0000"))
    await connector._upsert_issue(
        _issue("20001", "PLAT-11", "Story", "2026-05-01T10:00:00.000+0000", parent_id="20000")
    )
    await connector._wire_parents([("20001", "20000")])
    await db_session.commit()

    story_ref = (
        await db_session.execute(
            select(ExternalRef).where(ExternalRef.external_id == "20001")
        )
    ).scalar_one()
    epic_ref = (
        await db_session.execute(
            select(ExternalRef).where(ExternalRef.external_id == "20000")
        )
    ).scalar_one()
    story = await db_session.get(Task, story_ref.entity_id)
    assert story.parent_id == epic_ref.entity_id
