"""Draft plans (USER_FLOWS §C10): CRUD, and finalising a reviewed plan into the project's
bound tracker — epics before stories, content only, and a re-push updates instead of
duplicating."""

import pytest

from app.connectors.jira import JiraConnector
from app.core.security import hash_password
from app.models.base import TaskType, TrackingMode, UserRole
from app.models.draft import DraftPlan, DraftTask
from app.models.project import Project
from app.models.user import User
from app.schemas.entities import DraftFinalizeResult
from app.services import draft_sync
from tests.helpers import bind_project, jira_connection


async def _seed_admin(session) -> None:
    session.add(
        User(
            email="architect@example.com",
            hashed_password=hash_password("secret123"),
            role=UserRole.admin,
        )
    )
    await session.commit()


async def _token(client) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "architect@example.com", "password": "secret123"},
    )
    return resp.json()["access_token"]


@pytest.mark.asyncio
async def test_draft_plan_crud_via_api(client, db_session):
    await _seed_admin(db_session)
    headers = {"Authorization": f"Bearer {await _token(client)}"}
    project_id = (
        await client.post(
            "/api/v1/projects", json={"key": "PLAT", "name": "Platform"}, headers=headers
        )
    ).json()["id"]

    created = await client.post(
        f"/api/v1/projects/{project_id}/draft-plans",
        json={"title": "Q3 plan", "source": "https://docs/prd"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    plan_id = created.json()["id"]
    assert created.json()["status"] == "draft"

    epic = (
        await client.post(
            f"/api/v1/draft-plans/{plan_id}/tasks",
            json={"name": "Auth epic", "type": "summary"},
            headers=headers,
        )
    ).json()
    story = await client.post(
        f"/api/v1/draft-plans/{plan_id}/tasks",
        json={"name": "Login", "parent_id": epic["id"], "estimate_days": 4, "story_points": 5},
        headers=headers,
    )
    assert story.status_code == 201, story.text

    detail = (await client.get(f"/api/v1/draft-plans/{plan_id}", headers=headers)).json()
    assert {t["name"] for t in detail["tasks"]} == {"Auth epic", "Login"}
    login = next(t for t in detail["tasks"] if t["name"] == "Login")
    assert login["story_points"] == 5
    assert login["external_key"] is None  # not pushed yet

    # The plan shows up in the project listing.
    plans = (
        await client.get(f"/api/v1/projects/{project_id}/draft-plans", headers=headers)
    ).json()
    assert [p["id"] for p in plans] == [plan_id]

    # Delete the plan; its tasks go with it.
    deleted = await client.delete(f"/api/v1/draft-plans/{plan_id}", headers=headers)
    assert deleted.status_code == 204
    assert (await client.get(f"/api/v1/draft-plans/{plan_id}", headers=headers)).status_code == 404


async def _seed_plan(session) -> tuple[DraftPlan, DraftTask, DraftTask]:
    project = Project(key="PLAT", name="Platform")
    session.add(project)
    await session.flush()
    assert project.id is not None
    # The project mirrors Jira; its binding says which field holds story points.
    connection = await jira_connection(session)
    await bind_project(
        session,
        connection,
        project.id,
        {"project_key": "PLAT"},
        mapping={"estimate_field": "customfield_10016"},
    )
    plan = DraftPlan(project_id=project.id, title="Q3 plan")
    session.add(plan)
    await session.flush()
    epic = DraftTask(plan_id=plan.id, name="Auth epic", type=TaskType.summary, sort_order=0)
    session.add(epic)
    await session.flush()
    story = DraftTask(
        plan_id=plan.id,
        name="Login",
        type=TaskType.task,
        parent_id=epic.id,
        story_points=5,
        sort_order=1,
    )
    session.add(story)
    await session.commit()
    return plan, epic, story


def _fake_jira(monkeypatch, calls: list[dict]) -> None:
    counter = {"n": 0}

    async def fake_create(
        self,
        *,
        summary,
        issue_type,
        description=None,
        story_points=None,
        parent_key=None,
        project_key=None,
        estimate_field=None,
    ):
        counter["n"] += 1
        n = counter["n"]
        calls.append(
            {
                "summary": summary,
                "issue_type": issue_type,
                "parent_key": parent_key,
                "story_points": story_points,
                "estimate_field": estimate_field,
            }
        )
        return {"id": f"100{n}", "key": f"PLAT-{n}"}

    async def fake_update(
        self,
        issue_id_or_key,
        *,
        summary=None,
        description=None,
        story_points=None,
        estimate_field=None,
    ):
        calls.append({"update": issue_id_or_key, "summary": summary})

    # Jira's REST writes (the connector's `create_item`/`update_item` call these).
    monkeypatch.setattr(JiraConnector, "_create_issue", fake_create)
    monkeypatch.setattr(JiraConnector, "_update_issue", fake_update)


async def _finalize(session, plan_id: int) -> DraftFinalizeResult:
    return await draft_sync.finalize_plan(
        session, plan_id, connection_id=None, user_id=None, author=None
    )


@pytest.mark.asyncio
async def test_push_creates_epic_before_story(db_session, monkeypatch):
    plan, _epic, story = await _seed_plan(db_session)
    calls: list[dict] = []
    _fake_jira(monkeypatch, calls)

    result = await _finalize(db_session, plan.id)

    assert (result.mode, result.provider) == ("tracker", "jira")
    assert (result.created, result.updated, result.failed) == (2, 0, 0)
    # Epic is created before its story, and the story is linked to the epic's key.
    assert calls[0]["issue_type"] == "Epic"
    assert calls[1]["issue_type"] == "Story"
    assert calls[1]["parent_key"] == "PLAT-1"
    assert calls[1]["story_points"] == 5
    assert calls[1]["estimate_field"] == "customfield_10016"  # the binding's mapping
    await db_session.refresh(plan)
    await db_session.refresh(story)
    assert plan.status == "synced"
    assert plan.synced_at is not None
    assert (story.external_provider, story.external_key) == ("jira", "PLAT-2")


@pytest.mark.asyncio
async def test_repush_updates_instead_of_duplicating(db_session, monkeypatch):
    plan, _epic, _story = await _seed_plan(db_session)
    calls: list[dict] = []
    _fake_jira(monkeypatch, calls)

    await _finalize(db_session, plan.id)
    calls.clear()
    result = await _finalize(db_session, plan.id)

    assert (result.created, result.updated, result.failed) == (0, 2, 0)
    assert all("update" in c for c in calls)


@pytest.mark.asyncio
async def test_finalize_into_a_mirrored_project_without_a_binding_errors(db_session):
    project = Project(key="NOJIRA", name="No Jira", tracking_mode=TrackingMode.mirrored.value)
    db_session.add(project)
    await db_session.flush()
    plan = DraftPlan(project_id=project.id, title="orphan")
    db_session.add(plan)
    await db_session.commit()

    with pytest.raises(draft_sync.DraftPushError, match="no tracker binding"):
        await _finalize(db_session, plan.id)
