"""A project's tracking (USER_FLOWS §C12): reading it, adjusting the binding, and switching
between native and mirrored tracking with a previewed plan — the preview is exactly what apply
does (actions and resulting state)."""

from __future__ import annotations

from typing import Any

from sqlmodel import select

from app.core.config import settings
from app.core.crypto import encrypt_token
from app.core.security import hash_password
from app.models.base import Provider, UserRole
from app.models.integration import Connection, ExternalRef, TrackerBinding
from app.models.project import Project, Task, TaskStatusHistory
from app.models.user import User
from app.services import tracker_sync


async def _login(client: Any, email: str, password: str) -> dict[str, str]:
    resp = await client.post("/api/v1/auth/login", data={"username": email, "password": password})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _admin(client: Any, session: Any) -> dict[str, str]:
    session.add(
        User(email="admin@example.com", hashed_password=hash_password("secret123"),
             role=UserRole.admin)
    )
    await session.commit()
    return await _login(client, "admin@example.com", "secret123")


async def _demo_jira(session: Any) -> Connection:
    connection = Connection(
        provider=Provider.jira,
        name="Jira",
        encrypted_token=encrypt_token("demo-token"),
        config={"demo": True, "base_url": "https://jira.example.com"},
    )
    session.add(connection)
    await session.commit()
    return connection


async def _native_project(client: Any, admin: dict[str, str], key: str = "SHOP") -> int:
    resp = await client.post(
        "/api/v1/projects", json={"key": key, "name": key.title()}, headers=admin
    )
    assert resp.status_code == 201, resp.text
    return int(resp.json()["id"])


async def _task(client: Any, admin: dict[str, str], project: int, name: str, **extra: Any) -> int:
    resp = await client.post(
        "/api/v1/tasks",
        json={"project_id": project, "name": name, "duration": 1, **extra},
        headers=admin,
    )
    assert resp.status_code == 201, resp.text
    return int(resp.json()["id"])


def _switch_body(connection_id: int | None = None, **extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"to_mode": "mirrored" if connection_id else "native", **extra}
    if connection_id is not None:
        body.update(connection_id=connection_id, scope={"project_key": "SHOP"})
    return body


def _plan(result: dict[str, Any]) -> list[tuple[int, str, str | None]]:
    return [(a["task_id"], a["action"], a["detail"]) for a in result["actions"]]


async def test_native_project_reads_as_native_and_new_projects_follow_the_default(
    client, db_session, monkeypatch
):
    admin = await _admin(client, db_session)
    project = await _native_project(client, admin)
    tracking = (await client.get(f"/api/v1/projects/{project}/tracking", headers=admin)).json()
    assert tracking["mode"] == "native" and tracking["binding"] is None
    assert tracking["history"] == [] and tracking["can_edit"] is True
    assert tracking["trackers_enabled"] == ["jira"]

    monkeypatch.setattr(settings, "TRACKING_DEFAULT_MODE", "mirrored")
    other = (
        await client.post("/api/v1/projects", json={"key": "OPS", "name": "Ops"}, headers=admin)
    ).json()
    assert other["tracking_mode"] == "mirrored"


async def test_bind_a_tracker_keeping_canopy_work_separate(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "DEMO_MODE", True)
    admin = await _admin(client, db_session)
    project = await _native_project(client, admin)
    mine = await _task(client, admin, project, "Canopy-only spike")
    connection = await _demo_jira(db_session)
    url = f"/api/v1/projects/{project}/tracking/switch"

    preview = (await client.post(url, json=_switch_body(connection.id), headers=admin)).json()
    assert preview["applied"] is False and preview["dry_run"] is True
    assert _plan(preview) == [(mine, "keep", None)]
    assert (await client.get(f"/api/v1/projects/{project}/tracking", headers=admin)).json()[
        "mode"
    ] == "native"  # a preview changes nothing

    applied = (
        await client.post(url, json=_switch_body(connection.id, dry_run=False), headers=admin)
    ).json()
    assert applied["applied"] is True and _plan(applied) == _plan(preview)
    assert applied["synced_created"] == 4  # the first sync pulled the tracker's items
    tracking = (await client.get(f"/api/v1/projects/{project}/tracking", headers=admin)).json()
    assert tracking["mode"] == "mirrored" and tracking["binding"]["provider"] == "jira"
    assert tracking["binding"]["scope"] == {"project_key": "SHOP"}
    # The full sync stored the tracker's statuses: the board's columns are Jira's now.
    assert [s["name"] for s in tracking["binding"]["status_map"]] == [
        "To Do",
        "In Progress",
        "In Review",
        "Done",
    ]
    assert (tracking["canopy_owned"], tracking["tracker_owned"]) == (1, 4)
    spike = await db_session.get(Task, mine)
    assert spike.status_owner == "canopy"


async def test_match_adopts_tasks_and_preview_equals_apply(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "DEMO_MODE", True)
    admin = await _admin(client, db_session)
    project = await _native_project(client, admin)
    funnel = await _task(client, admin, project, "Emit checkout funnel events")
    dashboards = await _task(client, admin, project, "payment error dashboards")  # case-blind
    other = await _task(client, admin, project, "Unrelated work")
    connection = await _demo_jira(db_session)
    url = f"/api/v1/projects/{project}/tracking/switch"
    body = _switch_body(connection.id, strategy="match")

    preview = (await client.post(url, json=body, headers=admin)).json()
    assert _plan(preview) == [
        (funnel, "adopt", "matched SHOP-201"),
        (dashboards, "adopt", "matched SHOP-202"),
        (other, "keep", None),
    ]
    assert preview["counts"] == {"adopt": 2, "keep": 1}
    applied = (await client.post(url, json={**body, "dry_run": False}, headers=admin)).json()
    assert _plan(applied) == _plan(preview) and applied["counts"] == preview["counts"]

    db_session.expire_all()
    adopted = await db_session.get(Task, funnel)
    assert (adopted.status_owner, adopted.key, adopted.status) == ("jira", "SHOP-201", "Done")
    assert (await db_session.get(Task, other)).status_owner == "canopy"
    # The first sync brought the rest (epic + SHOP-203) without duplicating the adopted two.
    tasks = (
        await db_session.execute(select(Task).where(Task.project_id == project))
    ).scalars().all()
    assert len(tasks) == 5
    assert sorted(t.key for t in tasks if t.status_owner == "jira") == [
        "SHOP-200",
        "SHOP-201",
        "SHOP-202",
        "SHOP-203",
    ]


async def test_back_to_native_releases_tasks_and_remaps_unknown_statuses(client, db_session):
    admin = await _admin(client, db_session)
    project = Project(key="SHOP", name="Shop", tracking_mode="mirrored")
    connection = Connection(
        provider=Provider.jira, name="Jira", config={"base_url": "https://jira.example.com"}
    )
    db_session.add_all([project, connection])
    await db_session.flush()
    assert project.id is not None and connection.id is not None
    binding = TrackerBinding(
        connection_id=connection.id,
        provider=Provider.jira,
        target_type="project",
        target_id=project.id,
        scope={"project_key": "SHOP"},
    )
    doing = Task(project_id=project.id, name="Doing it", status="Doing",
                 status_category="in_progress", status_owner="jira", key="SHOP-1")
    known = Task(project_id=project.id, name="Known", status="To Do", status_category="todo",
                 status_owner="jira", key="SHOP-2")
    db_session.add_all([binding, doing, known])
    await db_session.flush()
    for task in (doing, known):
        assert task.id is not None
        db_session.add(ExternalRef(provider=Provider.jira, external_id=f"9{task.id}",
                                   external_key=task.key, entity_type="task",
                                   entity_id=task.id, connection_id=connection.id))
    doing_id, known_id, project_id = doing.id, known.id, project.id
    connection_id = connection.id
    await db_session.commit()
    url = f"/api/v1/projects/{project_id}/tracking/switch"

    preview = (await client.post(url, json={"to_mode": "native"}, headers=admin)).json()
    assert _plan(preview) == [
        (doing_id, "remap", "Doing → In Progress"),
        (known_id, "release", "jira"),
    ]
    assert any("leave Jira" in w for w in preview["warnings"])
    applied = (
        await client.post(url, json={"to_mode": "native", "dry_run": False}, headers=admin)
    ).json()
    assert _plan(applied) == _plan(preview)

    db_session.expire_all()
    moved = await db_session.get(Task, doing_id)
    assert (moved.status_owner, moved.status, moved.status_category) == (
        "canopy",
        "In Progress",
        "in_progress",
    )
    row = (
        await db_session.execute(
            select(TaskStatusHistory).where(TaskStatusHistory.task_id == doing_id)
        )
    ).scalars().one()
    assert (row.from_status, row.author, row.source) == ("Doing", "tracking switch", "canopy")
    refs = (await db_session.execute(select(ExternalRef))).scalars().all()
    assert all(r.detached_at is not None for r in refs)  # kept as "formerly SHOP-…" history
    links = (await client.get(f"/api/v1/tasks/{doing_id}/links", headers=admin)).json()
    assert links["tracker"]["key"] == "SHOP-1"
    tracking = (
        await client.get(f"/api/v1/projects/{project_id}/tracking", headers=admin)
    ).json()
    assert tracking["mode"] == "native" and tracking["binding"] is None
    assert [h["provider"] for h in tracking["history"]] == ["jira"]
    assert tracking["history"][0]["detached_at"] is not None
    # A detached project stays detached: the connection feeds nothing now.
    fresh = await db_session.get(Connection, connection_id)
    assert fresh is not None
    assert await tracker_sync.bindings_for_connection(db_session, fresh) == []


async def test_publish_hands_open_work_to_the_tracker(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "DEMO_MODE", True)
    admin = await _admin(client, db_session)
    project = await _native_project(client, admin)
    todo = await _task(client, admin, project, "Write the spec")
    started = await _task(client, admin, project, "Build it", status="In Progress")
    done = await _task(client, admin, project, "Old work", status="Done")
    connection = await _demo_jira(db_session)
    url = f"/api/v1/projects/{project}/tracking/switch"
    body = _switch_body(connection.id, strategy="publish")

    preview = (await client.post(url, json=body, headers=admin)).json()
    assert _plan(preview) == [
        (todo, "publish", None),
        (started, "publish", None),
        (done, "keep", None),  # finished work stays canopy-owned history
    ]
    assert any("1 started task" in w for w in preview["warnings"])
    applied = (await client.post(url, json={**body, "dry_run": False}, headers=admin)).json()
    assert _plan(applied) == _plan(preview)
    assert applied["published"] == {"created": 2, "skipped": 0, "failed": 0, "errors": []}
    db_session.expire_all()
    published = await db_session.get(Task, todo)
    assert published.status_owner == "jira" and published.key.startswith("SHOP-")
    assert (await db_session.get(Task, done)).status_owner == "canopy"

    again = await client.post(f"/api/v1/projects/{project}/tracking/publish", headers=admin)
    assert again.status_code == 200 and again.json()["created"] == 0  # idempotent


async def test_switch_rules_preview_for_agents_apply_for_humans(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "DEMO_MODE", True)
    admin = await _admin(client, db_session)
    project = await _native_project(client, admin)
    connection = await _demo_jira(db_session)
    url = f"/api/v1/projects/{project}/tracking/switch"
    agent = (await client.post("/api/v1/auth/agent-token", json={}, headers=admin)).json()
    agent_headers = {"Authorization": f"Bearer {agent['access_token']}"}

    assert (await client.post(url, json=_switch_body(connection.id),
                              headers=agent_headers)).status_code == 200
    refused = await client.post(url, json=_switch_body(connection.id, dry_run=False),
                                headers=agent_headers)
    assert refused.status_code == 403

    created = await client.post(
        "/api/v1/auth/register",
        json={"email": "eng@example.com", "password": "pw12345678", "role": "engineer"},
        headers=admin,
    )
    assert created.status_code in (200, 201)
    engineer = await _login(client, "eng@example.com", "pw12345678")
    assert (await client.post(url, json=_switch_body(connection.id),
                              headers=engineer)).status_code == 403
    # Nothing to switch to: already native.
    same = await client.post(url, json={"to_mode": "native"}, headers=admin)
    assert same.status_code == 400
    github = Connection(provider=Provider.github, name="gh", config={"owner": "o", "repo": "r"})
    db_session.add(github)
    await db_session.commit()
    not_tracker = await client.post(url, json=_switch_body(github.id), headers=admin)
    assert not_tracker.status_code == 400


async def test_adjust_the_binding_and_sync_the_project(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "DEMO_MODE", True)
    admin = await _admin(client, db_session)
    project = await _native_project(client, admin)
    assert (
        await client.put(f"/api/v1/projects/{project}/tracking", json={"mapping": {}},
                         headers=admin)
    ).status_code == 409
    assert (
        await client.post(f"/api/v1/projects/{project}/tracking/sync", headers=admin)
    ).status_code == 409
    connection = await _demo_jira(db_session)
    await client.post(
        f"/api/v1/projects/{project}/tracking/switch",
        json=_switch_body(connection.id, dry_run=False),
        headers=admin,
    )

    synced = await client.post(f"/api/v1/projects/{project}/tracking/sync?full=true",
                               headers=admin)
    assert synced.status_code == 200 and synced.json()["created"] == 0  # already pulled

    moved = await client.put(
        f"/api/v1/projects/{project}/tracking",
        json={"scope": {"project_key": "SHOP2"}, "mapping": {"epic_types": ["Epic"]}},
        headers=admin,
    )
    assert moved.status_code == 200, moved.text
    binding = moved.json()["binding"]
    assert binding["scope"] == {"project_key": "SHOP2"}
    assert binding["mapping"] == {"epic_types": ["Epic"]}
    assert binding["status_map"] == []  # a new scope: its statuses come with the next sync
    bad = await client.put(
        f"/api/v1/projects/{project}/tracking",
        json={"scope": {"board_id": "not-a-number"}},
        headers=admin,
    )
    assert bad.status_code == 400


async def test_a_tracker_connection_with_a_project_binds_it_and_delete_keeps_history(
    client, db_session
):
    admin = await _admin(client, db_session)
    project = await _native_project(client, admin)
    config = {"base_url": "https://jira.example.com", "jira_project_key": "SHOP",
              "story_point_field": "customfield_10016"}
    # The pre-binding shape (`config.project_id`) is refused, not silently ignored.
    old_shape = {"provider": "jira", "name": "Jira", "config": {**config, "project_id": project}}
    refused = await client.post("/api/v1/connectors/connections", json=old_shape, headers=admin)
    assert refused.status_code == 422 and "beside config" in refused.json()["detail"]
    body = {"provider": "jira", "name": "Jira", "project_id": project, "config": config}
    created = await client.post("/api/v1/connectors/connections", json=body, headers=admin)
    assert created.status_code == 201, created.text
    connection_id = created.json()["id"]
    tracking = (await client.get(f"/api/v1/projects/{project}/tracking", headers=admin)).json()
    assert tracking["mode"] == "mirrored"
    assert tracking["binding"]["connection_id"] == connection_id
    assert tracking["binding"]["scope"] == {"project_key": "SHOP"}
    assert tracking["binding"]["mapping"] == {"estimate_field": "customfield_10016"}
    again = await client.post("/api/v1/connectors/connections", json=body, headers=admin)
    assert again.status_code == 409 and again.json()["detail"]["code"] == "project_already_bound"

    url = f"/api/v1/connectors/connections/{connection_id}"
    in_use = await client.delete(url, headers=admin)
    assert in_use.status_code == 409 and in_use.json()["detail"]["project_ids"] == [project]
    await client.post(
        f"/api/v1/projects/{project}/tracking/switch",
        json={"to_mode": "native", "dry_run": False},
        headers=admin,
    )
    assert (await client.delete(url, headers=admin)).status_code == 204
    # Its past binding still names it, so it is deactivated rather than deleted.
    connection = await db_session.get(Connection, connection_id)
    assert connection is not None and connection.active is False
    # GitHub connections (nothing names them) are still deleted outright.
    gh = await client.post(
        "/api/v1/connectors/connections",
        # (GitHub keeps its own `project_id` config key — it binds nothing.)
        json={"provider": "github", "name": "gh",
              "config": {"owner": "o", "repo": "r", "project_id": project}},
        headers=admin,
    )
    assert (
        await client.delete(f"/api/v1/connectors/connections/{gh.json()['id']}", headers=admin)
    ).status_code == 204
    db_session.expire_all()
    assert await db_session.get(Connection, gh.json()["id"]) is None


async def test_one_tracker_scope_feeds_one_project(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "DEMO_MODE", True)
    admin = await _admin(client, db_session)
    first = await _native_project(client, admin, "SHOP")
    second = await _native_project(client, admin, "SHOP2")
    connection = await _demo_jira(db_session)
    bound = await client.post(
        f"/api/v1/projects/{first}/tracking/switch",
        json={**_switch_body(connection.id), "scope": {"project_key": "SHOP", "board_id": 1},
              "dry_run": False},
        headers=admin,
    )
    assert bound.status_code == 200, bound.text
    # The same Jira project (a board only adds sprints) can't feed a second canopy project.
    clash = await client.post(
        f"/api/v1/projects/{second}/tracking/switch", json=_switch_body(connection.id),
        headers=admin,
    )
    assert clash.status_code == 400 and "already feeds SHOP" in clash.json()["detail"]
    other = await client.post(
        f"/api/v1/projects/{second}/tracking/switch",
        json={**_switch_body(connection.id), "scope": {"project_key": "OPS"}},
        headers=admin,
    )
    assert other.status_code == 200, other.text

