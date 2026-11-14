"""Linear and the generic tracker (USER_FLOWS §J0): the same engine, bindings, board, switching,
links, drafts and webhooks as Jira — Linear read over GraphQL (served offline by the demo mock),
the generic tracker fed only by ingest or its signed webhook."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from sqlmodel import select

import app.webhooks.trackers as tracker_webhook
from app.connectors import get_connector
from app.connectors.generic import GenericTracker
from app.connectors.linear import LinearTracker
from app.core.config import settings
from app.core.crypto import encrypt_token
from app.core.security import hash_password
from app.models.base import Provider, TaskType, UserRole
from app.models.integration import Connection, ExternalRef, TrackerBinding
from app.models.project import Project, Task, TaskStatusHistory
from app.models.sprint import Sprint
from app.models.user import User
from app.services import tracker_sync
from app.services.tracker_types import KIND_EPIC, KIND_ITEM, ItemRef, Scope
from tests.conftest import TestSession

ALL = "jira,linear,generic"


async def _admin(client: Any, session: Any) -> dict[str, str]:
    session.add(
        User(email="admin@example.com", hashed_password=hash_password("secret123"),
             role=UserRole.admin)
    )
    await session.commit()
    resp = await client.post(
        "/api/v1/auth/login", data={"username": "admin@example.com", "password": "secret123"}
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _linear(session: Any) -> Connection:
    connection = Connection(
        provider=Provider.linear,
        name="Linear",
        encrypted_token=encrypt_token("lin_api_demo"),
        config={"demo": True, "workspace_url_key": "example", "team_key": "ENG"},
    )
    session.add(connection)
    await session.commit()
    return connection


async def _project(client: Any, admin: dict[str, str], key: str = "SRCH") -> int:
    resp = await client.post(
        "/api/v1/projects", json={"key": key, "name": key.title()}, headers=admin
    )
    return int(resp.json()["id"])


def _sign(body: bytes, prefix: str = "") -> str:
    return prefix + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()


# --------------------------------------------------------------------------- #
# Linear
# --------------------------------------------------------------------------- #


def test_linear_normalizes_issues_states_and_links() -> None:
    tracker = LinearTracker.__new__(LinearTracker)
    tracker.config = {"workspace_url_key": "acme"}
    parent = tracker.normalize(
        {
            "id": "a",
            "identifier": "ENG-1",
            "title": "Epic-ish",
            "state": {"name": "In Progress", "type": "started"},
            "children": {"nodes": [{"id": "b"}]},
            "updatedAt": "2026-05-01T10:00:00.000Z",
        }
    )
    assert (parent.kind, parent.status_category, parent.key) == (KIND_EPIC, "in_progress", "ENG-1")
    child = tracker.normalize(
        {
            "id": "b",
            "identifier": "ENG-2",
            "title": "Leaf",
            "state": {"name": "Won't do", "type": "canceled"},
            "parent": {"id": "a"},
            "estimate": 3,
            "assignee": {"id": "u1", "name": "Ana Lima", "email": "ana@example.com"},
        }
    )
    assert (child.kind, child.status_category, child.parent_external_id) == (
        KIND_ITEM,
        "cancelled",
        "a",
    )
    assert child.estimate == 3 and child.assignee is not None
    assert child.url == "https://linear.app/acme/issue/ENG-2"
    labelled = tracker.normalize(
        {"id": "c", "identifier": "ENG-3", "title": "x", "labels": {"nodes": [{"name": "Epic"}]}}
    )
    assert labelled.kind == KIND_EPIC
    assert LinearTracker.browse_url({}, "ENG-1") is None


async def test_bind_a_project_to_linear_mirrors_issues_states_and_cycles(
    client, db_session, monkeypatch
):
    monkeypatch.setattr(settings, "DEMO_MODE", True)
    monkeypatch.setattr(settings, "TRACKERS_ENABLED", ALL)
    admin = await _admin(client, db_session)
    team = (
        await client.post("/api/v1/teams", json={"key": "SRCH", "name": "Search"}, headers=admin)
    ).json()
    pod = (
        await client.post(f"/api/v1/teams/{team['id']}/pods", json={"name": "Core"},
                          headers=admin)
    ).json()
    project = await _project(client, admin)
    await client.patch(f"/api/v1/projects/{project}", json={"pod_id": pod["id"]}, headers=admin)
    connection = await _linear(db_session)

    applied = await client.post(
        f"/api/v1/projects/{project}/tracking/switch",
        json={"to_mode": "mirrored", "connection_id": connection.id,
              "scope": {"team_key": "ENG"}, "sync_iterations": True, "dry_run": False},
        headers=admin,
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["synced_created"] == 4
    tracking = (await client.get(f"/api/v1/projects/{project}/tracking", headers=admin)).json()
    assert tracking["binding"]["label"] == "Linear"
    assert [(s["name"], s["category"]) for s in tracking["binding"]["status_map"]] == [
        ("Backlog", "todo"),
        ("Todo", "todo"),
        ("In Progress", "in_progress"),
        ("In Review", "in_progress"),
        ("Done", "done"),
        ("Canceled", "cancelled"),
    ]
    workflow = (await client.get(f"/api/v1/projects/{project}/workflow", headers=admin)).json()
    assert workflow["scope"] == "tracker" and workflow["name"] == "Linear workflow"

    tasks = {
        t.key: t
        for t in (
            await db_session.execute(select(Task).where(Task.project_id == project))
        ).scalars().all()
    }
    assert tasks["ENG-1"].type == TaskType.summary
    assert tasks["ENG-2"].parent_id == tasks["ENG-1"].id
    assert (tasks["ENG-2"].status, tasks["ENG-2"].status_category) == ("Done", "done")
    assert tasks["ENG-3"].status_owner == "linear" and tasks["ENG-3"].story_points == 2
    cycle = (await db_session.execute(select(Sprint))).scalars().one()
    assert (cycle.name, cycle.state, cycle.owner) == ("Cycle 7", "active", "linear")
    assert {tasks["ENG-2"].sprint_id, tasks["ENG-3"].sprint_id} == {cycle.id}

    links = (await client.get(f"/api/v1/tasks/{tasks['ENG-3'].id}/links", headers=admin)).json()
    assert links["tracker"] == {
        "provider": "linear",
        "label": "Linear",
        "key": "ENG-3",
        "url": "https://linear.app/example/issue/ENG-3",
    }
    # The first sync replayed each new issue's history: exact transitions, not sync guesses.
    rows = (
        await db_session.execute(
            select(TaskStatusHistory).where(TaskStatusHistory.task_id == tasks["ENG-3"].id)
        )
    ).scalars().all()
    assert [(r.from_status, r.to_status, r.source) for r in rows] == [
        ("Todo", "In Progress", "backfill")
    ]
    binding = (await db_session.execute(select(TrackerBinding))).scalars().one()
    linear = get_connector(connection, db_session)
    again = await tracker_sync.backfill_task_history(
        linear, tracker_sync.view_of(binding), tasks["ENG-3"].id
    )
    assert again == 0  # idempotent


async def test_linear_links_drafts_and_content_writes(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "DEMO_MODE", True)
    monkeypatch.setattr(settings, "TRACKERS_ENABLED", ALL)
    admin = await _admin(client, db_session)
    project = await _project(client, admin)
    connection = await _linear(db_session)

    linked = await client.post(
        "/api/v1/tracker-links",
        json={"connection_id": connection.id, "root_key": "ENG-1", "target_type": "project",
              "target_id": project},
        headers=admin,
    )
    assert linked.status_code == 201, linked.text
    assert linked.json()["tasks_created"] == 4
    assert linked.json()["link"]["url"] == "https://linear.app/example/issue/ENG-1"

    linear = get_connector(connection, db_session)
    scope = Scope(kind="project", values={"team_key": "ENG"})
    from app.services.tracker_types import ItemDraft, ItemPatch

    ref = await linear.create_item(scope, ItemDraft(title="New work", estimate=2.4))
    assert ref.key is not None and ref.key.startswith("ENG-")
    await linear.update_item(scope, ItemRef(ref.external_id, ref.key), ItemPatch(title="Renamed"))
    assert await linear.fetch_item(scope, "ENG-404") is None


async def test_linear_webhook_is_verified_and_routed_by_team(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "TRACKERS_ENABLED", ALL)
    monkeypatch.setattr(settings, "LINEAR_WEBHOOK_SECRET", "s3cret")
    monkeypatch.setattr(tracker_webhook, "async_session_factory", TestSession)
    queued: list[tuple[Any, ...]] = []

    async def fake_enqueue(name: str, *args: Any) -> None:
        queued.append((name, *args))

    monkeypatch.setattr(tracker_webhook, "enqueue", fake_enqueue)
    project = Project(key="SRCH", name="Search", tracking_mode="mirrored")
    connection = Connection(provider=Provider.linear, name="Linear", config={})
    db_session.add_all([project, connection])
    await db_session.flush()
    assert project.id is not None and connection.id is not None
    db_session.add(TrackerBinding(connection_id=connection.id, provider=Provider.linear,
                                  target_type="project", target_id=project.id,
                                  scope={"team_key": "ENG"}))
    await db_session.commit()

    def payload(identifier: str) -> bytes:
        return json.dumps({
            "action": "update", "type": "Issue",
            "data": {"id": "lin-9", "identifier": identifier, "title": "Hooked",
                     "state": {"name": "In Progress", "type": "started"}},
        }).encode()

    body = payload("ENG-9")
    accepted = await client.post("/webhooks/linear", content=body,
                                 headers={"Linear-Signature": _sign(body)})
    assert accepted.status_code == 202 and accepted.json() == {"enqueued": 1}
    other = payload("OPS-1")
    ignored = await client.post("/webhooks/linear", content=other,
                                headers={"Linear-Signature": _sign(other)})
    assert ignored.json() == {"enqueued": 0}
    assert (await client.post("/webhooks/linear", content=body,
                              headers={"Linear-Signature": "0" * 64})).status_code == 401
    assert len(queued) == 1 and queued[0][1] == connection.id

    monkeypatch.setattr(settings, "LINEAR_WEBHOOK_SECRET", "")
    assert (await client.post("/webhooks/linear", content=body,
                              headers={"Linear-Signature": _sign(body)})).status_code == 403
    monkeypatch.setattr(settings, "TRACKERS_ENABLED", "jira")
    assert (await client.post("/webhooks/linear", content=body)).status_code == 404

    # Processing the event upserts the issue into the bound project.
    tracker = get_connector(connection, db_session)
    result = await tracker.handle_webhook(json.loads(body))
    assert result.created == 1
    task = (await db_session.execute(select(Task).where(Task.key == "ENG-9"))).scalars().one()
    assert (task.project_id, task.status_owner, task.status_category) == (
        project.id,
        "linear",
        "in_progress",
    )
    removed = tracker.parse_webhook({"action": "remove", "type": "Issue",
                                     "data": {"id": "lin-9", "identifier": "ENG-9"}})
    assert removed is not None and removed.deleted is True
    assert tracker.parse_webhook({"type": "Comment", "data": {"id": "x"}}) is None


# --------------------------------------------------------------------------- #
# The generic tracker (ingest / webhook only)
# --------------------------------------------------------------------------- #


async def test_generic_tracker_is_fed_by_ingest_and_its_webhook(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "TRACKERS_ENABLED", ALL)
    admin = await _admin(client, db_session)
    project = await _project(client, admin, "OPS")
    created = await client.post(
        "/api/v1/connectors/connections",
        json={"provider": "generic", "name": "Shortcut export",
              "config": {"tracker_name": "Shortcut",
                         "item_url_template": "https://app.example.com/story/{key}"}},
        headers=admin,
    )
    assert created.status_code == 201, created.text
    connection_id = created.json()["id"]
    applied = await client.post(
        f"/api/v1/projects/{project}/tracking/switch",
        json={"to_mode": "mirrored", "connection_id": connection_id,
              "scope": {"project_key": "OPS"}, "dry_run": False},
        headers=admin,
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["synced_created"] == 0  # canopy never reads a generic tracker
    refused = await client.post(f"/api/v1/projects/{project}/tracking/sync", headers=admin)
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "not_directly_readable"
    match = await client.post(
        f"/api/v1/projects/{project}/tracking/switch",
        json={"to_mode": "native"}, headers=admin,
    )
    assert match.status_code == 200  # previewing a way back is fine

    items = [
        {"external_id": "s-1", "external_key": "SC-1", "summary": "Ops epic", "kind": "epic"},
        {"external_id": "s-2", "external_key": "SC-2", "summary": "Rotate keys",
         "parent_external_id": "s-1", "status": "Started", "status_category": "in_progress"},
    ]
    ingested = await client.post(
        f"/api/v1/connectors/connections/{connection_id}/ingest/issues",
        json={"issues": items}, headers=admin,
    )
    assert ingested.status_code == 200 and ingested.json()["created"] == 2
    task = (await db_session.execute(select(Task).where(Task.key == "SC-2"))).scalars().one()
    assert (task.status_owner, task.status_category) == ("generic", "in_progress")
    links = (await client.get(f"/api/v1/tasks/{task.id}/links", headers=admin)).json()
    assert links["tracker"]["url"] == "https://app.example.com/story/SC-2"

    # Its webhook carries one normalized item, signed like the others.
    monkeypatch.setattr(settings, "GENERIC_WEBHOOK_SECRET", "s3cret")
    monkeypatch.setattr(tracker_webhook, "async_session_factory", TestSession)
    queued: list[Any] = []

    async def fake_enqueue(name: str, *args: Any) -> None:
        queued.append(args)

    monkeypatch.setattr(tracker_webhook, "enqueue", fake_enqueue)
    event = {"item": {"external_id": "s-3", "external_key": "SC-3", "summary": "Patch",
                      "status": "Done", "status_category": "done"},
             "scope": {"project_key": "OPS"}}
    body = json.dumps(event).encode()
    resp = await client.post("/webhooks/generic", content=body,
                             headers={"X-Canopy-Signature": _sign(body, "sha256=")})
    assert resp.status_code == 202 and resp.json() == {"enqueued": 1}
    connection = await db_session.get(Connection, connection_id)
    assert connection is not None
    tracker = get_connector(connection, db_session)
    assert isinstance(tracker, GenericTracker)
    assert (await tracker.handle_webhook(event)).created == 1
    refs = (await db_session.execute(select(ExternalRef))).scalars().all()
    assert {r.external_key for r in refs} == {"SC-1", "SC-2", "SC-3"}


async def test_admin_lists_the_trackers_this_instance_uses(client, db_session, monkeypatch):
    admin = await _admin(client, db_session)
    listed = (await client.get("/api/v1/admin/integrations", headers=admin)).json()
    assert {row["provider"] for row in listed} == {"jira", "github", "gdrive"}
    monkeypatch.setattr(settings, "TRACKERS_ENABLED", "jira,linear")
    listed = (await client.get("/api/v1/admin/integrations", headers=admin)).json()
    assert {row["provider"] for row in listed} == {"jira", "github", "gdrive", "linear"}
