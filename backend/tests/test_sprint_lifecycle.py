"""Delivery methods, the team board and the sprint lifecycle through the API (USER_FLOWS §C11)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest
from sqlmodel import select

from app.core.crypto import encrypt_token
from app.core.security import hash_password
from app.models.base import Provider, UserRole
from app.models.integration import Connection
from app.models.project import Task
from app.models.sprint import TaskSprintHistory
from app.models.user import User
from tests.helpers import bind_project


async def _token(client: Any, email: str, password: str = "pw12345678") -> str:
    resp = await client.post("/api/v1/auth/login", data={"username": email, "password": password})
    return resp.json()["access_token"]


def _hdr(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def team_world(client: Any, db_session: Any) -> dict[str, Any]:
    db_session.add(
        User(email="admin@example.com", hashed_password=hash_password("secret123"),
             role=UserRole.admin)
    )
    await db_session.commit()
    admin = _hdr(await _token(client, "admin@example.com", "secret123"))
    eng_user = (
        await client.post(
            "/api/v1/auth/register",
            json={"email": "eng@example.com", "password": "pw12345678", "role": "engineer"},
            headers=admin,
        )
    ).json()["id"]
    manager_user = (
        await client.post(
            "/api/v1/auth/register",
            json={"email": "em@example.com", "password": "pw12345678",
                  "role": "engineering_manager"},
            headers=admin,
        )
    ).json()["id"]
    ada = (
        await client.post(
            "/api/v1/team/engineers", json={"name": "Ada", "user_id": eng_user}, headers=admin
        )
    ).json()["id"]
    await client.post(
        "/api/v1/team/engineers", json={"name": "Max", "user_id": manager_user}, headers=admin
    )
    team = (
        await client.post("/api/v1/teams", json={"key": "OPS", "name": "Ops"}, headers=admin)
    ).json()
    pod = (
        await client.post(
            f"/api/v1/teams/{team['id']}/pods", json={"name": "Core"}, headers=admin
        )
    ).json()
    projects = []
    for key in ("ALPHA", "BETA"):
        pid = (
            await client.post(
                "/api/v1/projects", json={"key": key, "name": key, "pod_id": pod["id"]},
                headers=admin,
            )
        ).json()["id"]
        projects.append(pid)
    outside = (
        await client.post("/api/v1/projects", json={"key": "SOLO", "name": "Solo"},
                          headers=admin)
    ).json()["id"]
    return {
        "admin": admin,
        "eng": _hdr(await _token(client, "eng@example.com")),
        "em": _hdr(await _token(client, "em@example.com")),
        "team": team["id"],
        "pod": pod["id"],
        "projects": projects,
        "outside": outside,
        "ada": ada,
    }


async def _task(client: Any, w: dict[str, Any], project: int, name: str, **extra: Any) -> int:
    resp = await client.post(
        "/api/v1/tasks",
        json={"project_id": project, "name": name, "duration": 2, **extra},
        headers=w["admin"],
    )
    assert resp.status_code == 201, resp.text
    return int(resp.json()["id"])


async def test_delivery_method_settings_and_gate(client, team_world):
    w = team_world
    url = f"/api/v1/teams/{w['team']}/delivery"
    read = (await client.get(url, headers=w["eng"])).json()
    assert read["delivery_method"] == "kanban" and read["effective_method"] == "kanban"
    assert read["can_manage"] is False

    denied = await client.put(url, json={"delivery_method": "both"}, headers=w["em"])
    assert denied.status_code == 403
    saved = await client.put(
        url, json={"delivery_method": "both", "estimate_unit": "points", "sprint_length_days": 7},
        headers=w["admin"],
    )
    assert saved.status_code == 200 and saved.json()["delivery_method"] == "both"

    off = await client.patch(
        "/api/v1/admin/features/tracking.sprints", json={"enabled": False}, headers=w["admin"]
    )
    assert off.status_code == 200
    gated = (await client.get(url, headers=w["admin"])).json()
    assert gated["delivery_method"] == "both" and gated["effective_method"] == "kanban"
    listed = await client.get(f"/api/v1/teams/{w['team']}/sprints", headers=w["admin"])
    assert listed.status_code == 403 and listed.json()["detail"]["code"] == "feature_disabled"


async def test_sprint_lifecycle_end_to_end(client, team_world, db_session):
    w = team_world
    admin = w["admin"]
    a1 = await _task(client, w, w["projects"][0], "API", story_points=5)
    a2 = await _task(client, w, w["projects"][0], "UI", story_points=3)
    b1 = await _task(client, w, w["projects"][1], "Infra", story_points=8)
    solo = await _task(client, w, w["outside"], "Elsewhere")

    kanban = await client.post(f"/api/v1/teams/{w['team']}/sprints", json={}, headers=admin)
    assert kanban.status_code == 409 and kanban.json()["detail"]["code"] == "team_is_kanban"
    await client.put(
        f"/api/v1/teams/{w['team']}/delivery", json={"delivery_method": "sprint"}, headers=admin
    )
    s1 = (await client.post(f"/api/v1/teams/{w['team']}/sprints", json={}, headers=admin)).json()
    assert s1["name"] == "Sprint 1" and s1["state"] == "planned"
    assert s1["start_date"] == date.today().isoformat()
    s2 = (await client.post(f"/api/v1/teams/{w['team']}/sprints", json={}, headers=admin)).json()
    assert s2["start_date"] == (date.fromisoformat(s1["end_date"]) + timedelta(days=1)).isoformat()

    # Plan work from two projects of the team into one sprint.
    planned = await client.post(
        f"/api/v1/sprints/{s1['id']}/tasks", json={"task_ids": [a1, a2, b1]}, headers=admin
    )
    assert planned.status_code == 200
    assert planned.json()["task_count"] == 3 and planned.json()["scope"] == 16.0
    outside = await client.post(
        f"/api/v1/sprints/{s1['id']}/tasks", json={"task_ids": [solo]}, headers=admin
    )
    assert outside.status_code == 422 and outside.json()["detail"]["code"] == "outside_team"

    detail = (await client.get(f"/api/v1/sprints/{s1['id']}", headers=w["eng"])).json()
    assert {t["id"] for t in detail["tasks"]} == {a1, a2, b1}
    assert detail["capacity"]["unit"] == "points" and detail["capacity"]["committed"] == 16.0

    started = await client.post(f"/api/v1/sprints/{s1['id']}/start", headers=admin)
    assert started.status_code == 200
    assert started.json()["state"] == "active" and started.json()["committed"] == 16.0
    again = await client.post(f"/api/v1/sprints/{s2['id']}/start", headers=admin)
    assert again.status_code == 409 and again.json()["detail"]["code"] == "active_sprint"
    kanban_now = await client.put(
        f"/api/v1/teams/{w['team']}/delivery", json={"delivery_method": "kanban"}, headers=admin
    )
    assert kanban_now.status_code == 409

    # The board narrows to the active sprint, across both projects.
    board = (
        await client.get(f"/api/v1/teams/{w['team']}/board?sprint=active", headers=admin)
    ).json()
    on_board = {t["id"] for lane in board["lanes"] for t in lane["tasks"]}
    assert on_board == {a1, a2, b1} and board["team_id"] == w["team"]
    assert board["sprint_id"] == s1["id"] and board["delivery_method"] == "sprint"

    # Finish one, then complete the sprint: the rest carries into Sprint 2.
    await client.post(f"/api/v1/tasks/{a1}/move", json={"to_status": "Done"}, headers=admin)
    done = await client.post(
        f"/api/v1/sprints/{s1['id']}/complete",
        json={"carry_over": "next", "next_sprint_id": s2["id"]},
        headers=admin,
    )
    assert done.status_code == 200, done.text
    assert done.json()["state"] == "completed" and done.json()["completed"] == 5.0
    carried = (await client.get(f"/api/v1/sprints/{s2['id']}", headers=admin)).json()
    assert {t["id"] for t in carried["tasks"]} == {a2, b1}
    moves = (
        await db_session.execute(
            select(TaskSprintHistory).where(TaskSprintHistory.task_id == a2)
        )
    ).scalars().all()
    assert [(m.from_sprint_id, m.to_sprint_id) for m in moves] == [
        (None, s1["id"]), (s1["id"], s2["id"])
    ]

    report = (await client.get(f"/api/v1/sprints/{s1['id']}/report", headers=admin)).json()
    assert report["committed"] == 16.0 and report["completed"] == 5.0
    assert report["reliability"] == round(5 / 16, 2)
    assert report["burndown"] and report["burndown"][0]["ideal"] == 16.0

    velocity = (await client.get(f"/api/v1/teams/{w['team']}/velocity", headers=admin)).json()
    assert [p["completed"] for p in velocity["points"]] == [5.0]
    assert velocity["sufficient"] is False and velocity["forecast"]["sufficient"] is False

    reopened = await client.post(f"/api/v1/sprints/{s1['id']}/reopen", headers=admin)
    assert reopened.status_code == 200 and reopened.json()["state"] == "active"


async def test_membership_owned_by_a_syncing_tracker_is_refused(client, team_world, db_session):
    w = team_world
    await client.put(
        f"/api/v1/teams/{w['team']}/delivery", json={"delivery_method": "both"}, headers=w["admin"]
    )
    mirrored = await _task(client, w, w["projects"][0], "From Jira")
    task = await db_session.get(Task, mirrored)
    task.status_owner = "jira"
    connection = Connection(
        provider=Provider.jira, name="j", encrypted_token=encrypt_token("t"), config={}
    )
    db_session.add(connection)
    await db_session.flush()
    # The project mirrors Jira, sprints included (its board).
    await bind_project(
        db_session, connection, w["projects"][0], {"board_id": 7}, sync_iterations=True
    )
    await db_session.commit()
    sprint = (
        await client.post(f"/api/v1/teams/{w['team']}/sprints", json={}, headers=w["admin"])
    ).json()
    refused = await client.post(
        f"/api/v1/sprints/{sprint['id']}/tasks", json={"task_ids": [mirrored]},
        headers=w["admin"],
    )
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "membership_externally_owned"


async def test_team_board_folds_unknown_statuses_by_category(client, team_world, db_session):
    w = team_world
    columns = [
        {"name": "Ready", "category": "todo"},
        {"name": "Doing", "category": "in_progress"},
        {"name": "Shipped", "category": "done"},
    ]
    saved = await client.put(
        f"/api/v1/teams/{w['team']}/workflow", json={"columns": columns}, headers=w["admin"]
    )
    assert saved.status_code == 200
    native = await _task(client, w, w["projects"][0], "Native")
    mirrored = await _task(client, w, w["projects"][1], "Mirrored")
    from app.services import workflow as wf

    task = await db_session.get(Task, mirrored)
    task.status_owner = "jira"
    wf.record_transition(
        db_session, task, "In Code Review", category="in_progress",
        source=wf.StatusSource.sync,
    )
    await db_session.commit()

    board = (await client.get(f"/api/v1/teams/{w['team']}/board", headers=w["admin"])).json()
    assert [lane["status"] for lane in board["lanes"]] == ["Ready", "Doing", "Shipped"]
    doing = next(lane for lane in board["lanes"] if lane["status"] == "Doing")
    card = next(t for t in doing["tasks"] if t["id"] == mirrored)
    assert card["status"] == "In Code Review" and card["movable"] is False
    ready = next(lane for lane in board["lanes"] if lane["status"] == "Ready")
    assert native in {t["id"] for t in ready["tasks"]}


async def test_my_sprint_and_staged_sprint_changes(client, team_world):
    w = team_world
    admin = w["admin"]
    await client.put(
        f"/api/v1/teams/{w['team']}/delivery", json={"delivery_method": "sprint"}, headers=admin
    )
    mine = await _task(client, w, w["projects"][0], "Mine", assignee_engineer_id=w["ada"])
    other = await _task(client, w, w["projects"][0], "Staged")
    sprint = (
        await client.post(f"/api/v1/teams/{w['team']}/sprints", json={}, headers=admin)
    ).json()
    await client.post(f"/api/v1/sprints/{sprint['id']}/tasks", json={"task_ids": [mine]},
                      headers=admin)
    await client.post(f"/api/v1/sprints/{sprint['id']}/start", headers=admin)

    workspace = (await client.get("/api/v1/me/workspace", headers=w["eng"])).json()
    assert [s["sprint"]["id"] for s in workspace["my_sprints"]] == [sprint["id"]]
    assert [t["id"] for t in workspace["my_sprints"][0]["tasks"]] == [mine]

    staged = await client.post(
        "/api/v1/proposals",
        json={
            "scope_level": "project",
            "scope_id": w["projects"][0],
            "title": "Pull into the sprint",
            "items": [{"entity_type": "task", "action": "update", "entity_id": other,
                       "payload": {"sprint_id": sprint["id"]}}],
        },
        headers=admin,
    )
    assert staged.status_code == 201, staged.text
    applied = await client.post(f"/api/v1/proposals/{staged.json()['id']}/apply", headers=admin)
    assert applied.status_code == 200, applied.text
    detail = (await client.get(f"/api/v1/sprints/{sprint['id']}", headers=admin)).json()
    assert other in {t["id"] for t in detail["tasks"]}
