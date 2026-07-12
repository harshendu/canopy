import pytest
from sqlmodel import func, select

from app.connectors.jira import JiraConnector
from app.core.crypto import encrypt_token
from app.models.base import Provider
from app.models.integration import Connection, ExternalRef
from app.models.project import Project, Task
from app.models.team import Engineer


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


def _issue(
    ext_id: str,
    key: str,
    issuetype: str,
    updated: str,
    parent_id: str | None = None,
    assignee: tuple[str, str] | None = None,
):
    fields = {
        "summary": f"Issue {key}",
        "status": {"name": "To Do"},
        "issuetype": {"name": issuetype},
        "updated": updated,
    }
    if parent_id:
        fields["parent"] = {"id": parent_id}
    if assignee:
        fields["assignee"] = {"accountId": assignee[0], "displayName": assignee[1]}
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
    await connector._upsert_issue(
        _issue("10001", "PLAT-1", "Story", "2026-05-01T10:00:00.000+0000")
    )
    await db_session.commit()
    action, _, _ = await connector._upsert_issue(
        _issue("10001", "PLAT-1", "Story", "2026-05-02T10:00:00.000+0000")
    )
    await db_session.commit()
    assert action == "updated"


@pytest.mark.asyncio
async def test_epic_parent_wiring(db_session):
    connector = await _make_connector(db_session)
    await connector._upsert_issue(
        _issue("20000", "PLAT-10", "Epic", "2026-05-01T10:00:00.000+0000")
    )
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


async def _task_for(db_session, ext_id: str) -> Task:
    ref = (
        await db_session.execute(select(ExternalRef).where(ExternalRef.external_id == ext_id))
    ).scalar_one()
    return await db_session.get(Task, ref.entity_id)


@pytest.mark.asyncio
async def test_assignee_creates_engineer_and_reuses_by_account_id(db_session):
    connector = await _make_connector(db_session)
    await connector._upsert_issue(
        _issue("30001", "PLAT-20", "Story", "2026-05-01T10:00:00.000+0000",
               assignee=("acc-1", "Dana Lee"))
    )
    await connector._upsert_issue(
        _issue("30002", "PLAT-21", "Story", "2026-05-01T10:00:00.000+0000",
               assignee=("acc-1", "Dana Lee"))
    )
    await db_session.commit()

    engineers = (await db_session.execute(select(Engineer))).scalars().all()
    assert len(engineers) == 1
    assert engineers[0].name == "Dana Lee"
    assert engineers[0].jira_account_id == "acc-1"
    for ext_id in ("30001", "30002"):
        task = await _task_for(db_session, ext_id)
        assert task.assignee_engineer_id == engineers[0].id


@pytest.mark.asyncio
async def test_assignee_matches_existing_engineer_by_name_and_backfills_account(db_session):
    connector = await _make_connector(db_session)
    existing = Engineer(name="Dana Lee")
    db_session.add(existing)
    await db_session.flush()

    await connector._upsert_issue(
        _issue("30003", "PLAT-22", "Story", "2026-05-01T10:00:00.000+0000",
               assignee=("acc-1", "dana lee"))
    )
    await db_session.commit()

    engineers = (await db_session.execute(select(Engineer))).scalars().all()
    assert len(engineers) == 1  # matched, not duplicated
    assert engineers[0].jira_account_id == "acc-1"
    task = await _task_for(db_session, "30003")
    assert task.assignee_engineer_id == existing.id


@pytest.mark.asyncio
async def test_same_display_name_different_account_creates_second_engineer(db_session):
    """Two Jira users sharing a display name must not collapse onto one Engineer."""
    connector = await _make_connector(db_session)
    first = Engineer(name="Dana Lee", jira_account_id="acc-1")
    db_session.add(first)
    await db_session.flush()

    await connector._upsert_issue(
        _issue("30010", "PLAT-30", "Story", "2026-05-01T10:00:00.000+0000",
               assignee=("acc-2", "Dana Lee"))
    )
    await db_session.commit()

    engineers = (
        await db_session.execute(select(Engineer).order_by(Engineer.id))
    ).scalars().all()
    assert len(engineers) == 2
    assert engineers[0].jira_account_id == "acc-1"  # untouched
    assert engineers[1].jira_account_id == "acc-2"
    task = await _task_for(db_session, "30010")
    assert task.assignee_engineer_id == engineers[1].id


@pytest.mark.asyncio
async def test_unassigned_issue_leaves_local_owner_untouched(db_session):
    connector = await _make_connector(db_session)
    local_owner = Engineer(name="Local Owner")
    db_session.add(local_owner)
    await db_session.flush()

    await connector._upsert_issue(
        _issue("30004", "PLAT-23", "Story", "2026-05-01T10:00:00.000+0000")
    )
    await db_session.commit()
    task = await _task_for(db_session, "30004")
    assert task.assignee_engineer_id is None

    # Assign locally, then a newer unassigned update arrives: ownership must survive.
    task.assignee_engineer_id = local_owner.id
    await db_session.commit()
    await connector._upsert_issue(
        _issue("30004", "PLAT-23", "Story", "2026-05-02T10:00:00.000+0000")
    )
    await db_session.commit()
    task = await _task_for(db_session, "30004")
    assert task.assignee_engineer_id == local_owner.id


@pytest.mark.asyncio
async def test_jira_assignee_overrides_local_owner(db_session):
    connector = await _make_connector(db_session)
    local_owner = Engineer(name="Local Owner")
    db_session.add(local_owner)
    await db_session.flush()

    await connector._upsert_issue(
        _issue("30005", "PLAT-24", "Story", "2026-05-01T10:00:00.000+0000")
    )
    await db_session.commit()
    task = await _task_for(db_session, "30005")
    task.assignee_engineer_id = local_owner.id
    await db_session.commit()

    await connector._upsert_issue(
        _issue("30005", "PLAT-24", "Story", "2026-05-02T10:00:00.000+0000",
               assignee=("acc-2", "Sam Roy"))
    )
    await db_session.commit()
    task = await _task_for(db_session, "30005")
    sam = (
        await db_session.execute(select(Engineer).where(Engineer.jira_account_id == "acc-2"))
    ).scalar_one()
    assert task.assignee_engineer_id == sam.id
