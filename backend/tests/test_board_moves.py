"""Native tracking: creating tasks with a status, moving cards, ownership, WIP limits, ranks and
the board/workflow endpoints (USER_FLOWS §C9)."""

from __future__ import annotations

from typing import Any

import pytest
from sqlmodel import select

from app.core.security import hash_password
from app.models.base import UserRole
from app.models.integration import ExternalRef
from app.models.project import Task, TaskStatusHistory
from app.models.user import User


async def _token(client: Any, email: str, password: str = "pw12345678") -> str:
    resp = await client.post("/api/v1/auth/login", data={"username": email, "password": password})
    return resp.json()["access_token"]


def _hdr(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def world(client: Any, db_session: Any) -> dict[str, Any]:
    db_session.add(
        User(email="admin@example.com", hashed_password=hash_password("secret123"),
             role=UserRole.admin)
    )
    await db_session.commit()
    admin = _hdr(await _token(client, "admin@example.com", "secret123"))
    headers: dict[str, dict[str, str]] = {"admin": admin}
    ids: dict[str, int] = {}
    for role in ("engineering_manager", "engineer", "viewer"):
        created = await client.post(
            "/api/v1/auth/register",
            json={"email": f"{role}@example.com", "password": "pw12345678", "role": role},
            headers=admin,
        )
        ids[role] = created.json()["id"]
        headers[role] = _hdr(await _token(client, f"{role}@example.com"))
    ada = (
        await client.post(
            "/api/v1/team/engineers",
            json={"name": "Ada", "user_id": ids["engineer"]},
            headers=admin,
        )
    ).json()["id"]
    bob = (
        await client.post("/api/v1/team/engineers", json={"name": "Bob"}, headers=admin)
    ).json()["id"]
    project = (
        await client.post(
            "/api/v1/projects", json={"key": "CHK", "name": "Checkout"}, headers=admin
        )
    ).json()["id"]
    return {"h": headers, "project": project, "ada": ada, "bob": bob}


async def _task(client: Any, world: dict[str, Any], name: str, **extra: Any) -> dict[str, Any]:
    resp = await client.post(
        "/api/v1/tasks",
        json={"project_id": world["project"], "name": name, "duration": 1, **extra},
        headers=world["h"]["admin"],
    )
    assert resp.status_code == 201, resp.text
    return dict(resp.json())


async def _move(client: Any, headers: dict[str, str], task_id: int, **body: Any) -> Any:
    return await client.post(f"/api/v1/tasks/{task_id}/move", json=body, headers=headers)


async def test_new_task_gets_a_key_and_a_first_status_with_history(client, world, db_session):
    first = await _task(client, world, "Design API")
    asked = await _task(client, world, "Build API", status="In Progress")
    half = await _task(client, world, "Half done", percent_complete=50)
    phase = await _task(client, world, "Phase 1", type="summary")

    assert first["key"] == "CHK-1" and first["status"] == "Backlog"
    assert first["status_category"] == "todo" and first["status_owner"] == "canopy"
    assert asked["status"] == "In Progress" and asked["status_category"] == "in_progress"
    assert half["status"] == "In Progress"  # started work lands in the first started column
    assert phase["status"] is None and phase["key"] == "CHK-4"  # phases carry no status
    rows = (
        await db_session.execute(
            select(TaskStatusHistory).where(TaskStatusHistory.task_id == first["id"])
        )
    ).scalars().all()
    assert [(r.from_status, r.to_status, r.to_category, r.source) for r in rows] == [
        (None, "Backlog", "todo", "canopy")
    ]

    bad = await client.post(
        "/api/v1/tasks",
        json={"project_id": world["project"], "name": "X", "status": "Shipped"},
        headers=world["h"]["admin"],
    )
    assert bad.status_code == 422
    assert bad.json()["detail"]["code"] == "unknown_status"


async def test_move_records_history_and_reconciles_progress(client, world, db_session):
    task = await _task(client, world, "Ship it")
    moved = await _move(client, world["h"]["admin"], task["id"], to_status="done")
    assert moved.status_code == 200, moved.text
    body = moved.json()
    assert body["changed"] is True
    assert body["task"]["status"] == "Done"  # canonical column name, case-insensitive match
    assert body["task"]["percent_complete"] == 100.0

    back = await _move(client, world["h"]["admin"], task["id"], to_status="In Review")
    assert back.json()["task"]["percent_complete"] == 0.0  # left done
    rows = (
        await db_session.execute(
            select(TaskStatusHistory)
            .where(TaskStatusHistory.task_id == task["id"])
            .order_by(TaskStatusHistory.id)
        )
    ).scalars().all()
    assert [r.to_status for r in rows] == ["Backlog", "Done", "In Review"]
    assert rows[1].author == "admin@example.com"

    unknown = await _move(client, world["h"]["admin"], task["id"], to_status="Shipped")
    assert unknown.status_code == 422 and unknown.json()["detail"]["code"] == "unknown_status"
    stale = await _move(
        client, world["h"]["admin"], task["id"], to_status="Done", expected_status="Backlog"
    )
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "stale"


async def test_mirrored_task_status_cannot_be_moved_but_can_be_reordered(
    client, world, db_session
):
    task = await _task(client, world, "Tokenise cards")
    row = await db_session.get(Task, task["id"])
    row.status_owner = "jira"
    db_session.add(
        ExternalRef(provider="jira", external_id="9", external_key="SHOP-9", entity_type="task",
                    entity_id=task["id"])
    )
    await db_session.commit()

    refused = await _move(client, world["h"]["admin"], task["id"], to_status="Done")
    assert refused.status_code == 409
    detail = refused.json()["detail"]
    assert detail["code"] == "status_externally_owned" and detail["provider"] == "jira"

    reorder = await _move(client, world["h"]["admin"], task["id"], position="top")
    assert reorder.status_code == 200 and reorder.json()["changed"] is False


async def test_engineers_move_own_cards_and_pull_unassigned_ones(client, world):
    mine = await _task(client, world, "Mine", assignee_engineer_id=world["ada"])
    theirs = await _task(client, world, "Theirs", assignee_engineer_id=world["bob"])
    free = await _task(client, world, "Free")
    eng = world["h"]["engineer"]

    assert (await _move(client, eng, mine["id"], to_status="In Progress")).status_code == 200
    assert (await _move(client, eng, theirs["id"], to_status="In Progress")).status_code == 403
    pulled = await _move(client, eng, free["id"], to_status="In Progress")
    assert pulled.status_code == 200
    assert pulled.json()["task"]["assignee_engineer_id"] == world["ada"]
    viewer = world["h"]["viewer"]
    assert (await _move(client, viewer, mine["id"], to_status="Done")).status_code == 403


async def test_wip_limits_warn_or_block(client, world):
    admin = world["h"]["admin"]
    columns = [
        {"name": "To Do", "category": "todo"},
        {"name": "Doing", "category": "in_progress", "wip_limit": 1},
        {"name": "Done", "category": "done"},
    ]
    saved = await client.put(
        f"/api/v1/projects/{world['project']}/workflow",
        json={"name": "Lean", "wip_enforcement": "warn", "columns": columns},
        headers=admin,
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["scope"] == "project" and saved.json()["inherited"] is False
    a = await _task(client, world, "A", status="Doing")
    b = await _task(client, world, "B")
    warned = await _move(client, admin, b["id"], to_status="Doing")
    assert warned.status_code == 200 and warned.json()["warnings"] == ["wip_limit_exceeded"]

    await client.put(
        f"/api/v1/projects/{world['project']}/workflow",
        json={"name": "Lean", "wip_enforcement": "block", "columns": columns},
        headers=admin,
    )
    await _move(client, admin, b["id"], to_status="To Do")
    blocked = await _move(client, admin, b["id"], to_status="Doing")
    assert blocked.status_code == 409 and blocked.json()["detail"]["code"] == "wip_limit_reached"
    assert a["status"] == "Doing"

    board = (
        await client.get(f"/api/v1/projects/{world['project']}/board", headers=admin)
    ).json()
    doing = next(lane for lane in board["lanes"] if lane["status"] == "Doing")
    assert doing["wip_limit"] == 1 and doing["over_limit"] is False
    assert board["wip_enforcement"] == "block"


async def test_ranks_place_cards_between_neighbours(client, world):
    admin = world["h"]["admin"]
    a = await _task(client, world, "A")
    b = await _task(client, world, "B")
    c = await _task(client, world, "C")
    # Put C between A and B, then B at the top.
    assert (
        await _move(client, admin, c["id"], after_task_id=a["id"], before_task_id=b["id"])
    ).status_code == 200
    assert (await _move(client, admin, b["id"], position="top")).status_code == 200
    board = (
        await client.get(f"/api/v1/projects/{world['project']}/board", headers=admin)
    ).json()
    backlog = next(lane for lane in board["lanes"] if lane["status"] == "Backlog")
    assert [t["name"] for t in backlog["tasks"]] == ["B", "A", "C"]

    # Squeezing repeatedly between two neighbours exhausts the gap and triggers a renumber.
    for _ in range(12):
        resp = await _move(client, admin, b["id"], after_task_id=a["id"], before_task_id=c["id"])
        assert resp.status_code == 200
        resp = await _move(client, admin, b["id"], position="top")
    board = (
        await client.get(f"/api/v1/projects/{world['project']}/board", headers=admin)
    ).json()
    backlog = next(lane for lane in board["lanes"] if lane["status"] == "Backlog")
    assert [t["name"] for t in backlog["tasks"]] == ["B", "A", "C"]


async def test_native_tracking_gate_off_refuses_status_writes(client, world):
    admin = world["h"]["admin"]
    task = await _task(client, world, "A")
    off = await client.patch(
        "/api/v1/admin/features/tracking.native", json={"enabled": False}, headers=admin
    )
    assert off.status_code == 200
    refused = await _move(client, admin, task["id"], to_status="Done")
    assert refused.status_code == 403
    assert refused.json()["detail"]["code"] == "native_tracking_disabled"
    created = await _task(client, world, "No status")
    assert created["status"] is None


async def test_workflow_rename_and_removal(client, world):
    admin = world["h"]["admin"]
    review = await _task(client, world, "Reviewing", status="In Review")
    backlog = await _task(client, world, "Later")
    columns = [
        {"name": "To Do", "category": "todo"},
        {"name": "In Progress", "category": "in_progress"},
        {"name": "Code review", "category": "in_progress", "previous_name": "In Review"},
        {"name": "Done", "category": "done"},
    ]
    url = f"/api/v1/projects/{world['project']}/workflow"
    refused = await client.put(url, json={"columns": columns}, headers=admin)
    assert refused.status_code == 422  # Backlog holds a task and has no destination
    assert refused.json()["detail"]["columns"] == ["Backlog"]
    ok = await client.put(
        url, json={"columns": columns, "move_tasks_to": {"Backlog": "To Do"}}, headers=admin
    )
    assert ok.status_code == 200, ok.text
    tasks = {
        t["id"]: t
        for t in (
            await client.get(
                f"/api/v1/tasks?project_id={world['project']}", headers=admin
            )
        ).json()
    }
    assert tasks[review["id"]]["status"] == "Code review"  # renamed in place
    assert tasks[backlog["id"]]["status"] == "To Do"  # moved, with a transition
    missing_done = await client.put(
        url, json={"columns": [{"name": "To Do", "category": "todo"}]}, headers=admin
    )
    assert missing_done.status_code == 422


async def test_team_workflow_is_shared_and_needs_a_team_seat(client, world, db_session):
    admin, manager = world["h"]["admin"], world["h"]["engineering_manager"]
    team = (
        await client.post("/api/v1/teams", json={"key": "PAY", "name": "Payments"}, headers=admin)
    ).json()
    url = f"/api/v1/teams/{team['id']}/workflow"
    inherited = (await client.get(url, headers=manager)).json()
    assert inherited["inherited"] is True and inherited["scope"] == "default"
    body = {
        "columns": [
            {"name": "Ready", "category": "todo"},
            {"name": "Doing", "category": "in_progress", "wip_limit": 3},
            {"name": "Shipped", "category": "done"},
        ]
    }
    assert (await client.put(url, json=body, headers=manager)).status_code == 403
    assert (await client.put(url, json=body, headers=admin)).status_code == 200

    pod = (
        await client.post(f"/api/v1/teams/{team['id']}/pods", json={"name": "Core"},
                          headers=admin)
    ).json()
    await client.patch(
        f"/api/v1/projects/{world['project']}", json={"pod_id": pod["id"]}, headers=admin
    )
    project_wf = (
        await client.get(f"/api/v1/projects/{world['project']}/workflow", headers=admin)
    ).json()
    assert project_wf["scope"] == "team" and project_wf["inherited"] is True
    created = await _task(client, world, "Team task")
    assert created["status"] == "Ready"
