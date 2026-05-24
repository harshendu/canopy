import pytest

from app.connectors.jira import JiraConnector
from app.core.crypto import encrypt_token
from app.core.security import hash_password
from app.models.base import Provider, TaskType, UserRole
from app.models.draft import DraftPlan, DraftTask
from app.models.integration import Connection
from app.models.project import Project
from app.models.user import User
from app.services import draft_sync


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
    assert login["jira_key"] is None  # not pushed yet

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
    session.add(
        Connection(
            provider=Provider.jira,
            name="jira",
            encrypted_token=encrypt_token("api-token"),
            config={
                "base_url": "https://example.atlassian.net",
                "email": "a@b.com",
                "project_id": project.id,
                "jira_project_key": "PLAT",
                "story_point_field": "customfield_10016",
            },
        )
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
        self, *, summary, issue_type, description=None, story_points=None, parent_key=None
    ):
        counter["n"] += 1
        n = counter["n"]
        calls.append(
            {
                "summary": summary,
                "issue_type": issue_type,
                "parent_key": parent_key,
                "story_points": story_points,
            }
        )
        return {"id": f"100{n}", "key": f"PLAT-{n}"}

    async def fake_update(
        self, issue_id_or_key, *, summary=None, description=None, story_points=None
    ):
        calls.append({"update": issue_id_or_key, "summary": summary})

    monkeypatch.setattr(JiraConnector, "create_issue", fake_create)
    monkeypatch.setattr(JiraConnector, "update_issue", fake_update)


@pytest.mark.asyncio
async def test_push_creates_epic_before_story(db_session, monkeypatch):
    plan, _epic, story = await _seed_plan(db_session)
    calls: list[dict] = []
    _fake_jira(monkeypatch, calls)

    result = await draft_sync.push_plan_to_jira(db_session, plan.id)

    assert (result.created, result.updated, result.failed) == (2, 0, 0)
    # Epic is created before its story, and the story is linked to the epic's key.
    assert calls[0]["issue_type"] == "Epic"
    assert calls[1]["issue_type"] == "Story"
    assert calls[1]["parent_key"] == "PLAT-1"
    assert calls[1]["story_points"] == 5
    await db_session.refresh(plan)
    await db_session.refresh(story)
    assert plan.status == "synced"
    assert plan.synced_at is not None
    assert story.jira_key == "PLAT-2"


@pytest.mark.asyncio
async def test_repush_updates_instead_of_duplicating(db_session, monkeypatch):
    plan, _epic, _story = await _seed_plan(db_session)
    calls: list[dict] = []
    _fake_jira(monkeypatch, calls)

    await draft_sync.push_plan_to_jira(db_session, plan.id)
    calls.clear()
    result = await draft_sync.push_plan_to_jira(db_session, plan.id)

    assert (result.created, result.updated, result.failed) == (0, 2, 0)
    assert all("update" in c for c in calls)


@pytest.mark.asyncio
async def test_push_without_jira_connection_errors(db_session, monkeypatch):
    project = Project(key="NOJIRA", name="No Jira")
    db_session.add(project)
    await db_session.flush()
    plan = DraftPlan(project_id=project.id, title="orphan")
    db_session.add(plan)
    await db_session.commit()

    with pytest.raises(draft_sync.DraftPushError):
        await draft_sync.push_plan_to_jira(db_session, plan.id)
