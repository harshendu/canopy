"""The pluggable work-tracker layer (USER_FLOWS §J0/§J9): the `WorkTracker` contract every
tracker must keep, the import boundary around the engine, provider-neutral tracker links,
ingest, webhooks and task links, `/meta/trackers`, mirrored projects' tracker-owned columns,
the WIP scope shared by the board and the move check, card-move rules, PR → task key matching
and the nightly changelog backfill."""

from __future__ import annotations

import ast
import hashlib
import hmac
import json
from pathlib import Path
from typing import Any

import pytest
from sqlmodel import select

import app.webhooks.trackers as tracker_webhook
from app.connectors import get_connector
from app.connectors.tracker import WorkTracker, registered_trackers
from app.core.config import settings
from app.core.crypto import encrypt_token
from app.core.security import hash_password
from app.main import app as main_app
from app.models.base import Provider, TaskType, UserRole
from app.models.integration import Connection, ExternalRef, PullRequest, TrackerBinding
from app.models.project import Project, Task, TaskStatusHistory
from app.models.user import User
from app.schemas.entities import IngestIssue
from app.services import ingest, tracker_sync
from tests.conftest import TestSession

APP = Path(__file__).resolve().parents[1] / "app"
TRACKERS = sorted(registered_trackers().items(), key=lambda kv: kv[0].value)
TRACKER_IDS = [p.value for p, _ in TRACKERS]


def _overrides(cls: type[WorkTracker], name: str) -> bool:
    """True when `cls` (or a base below `WorkTracker`) defines `name` itself."""
    mro = cls.__mro__
    return any(name in klass.__dict__ for klass in mro[: mro.index(WorkTracker)])


# --------------------------------------------------------------------------- #
# The WorkTracker contract (every registered tracker)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(("provider", "cls"), TRACKERS, ids=TRACKER_IDS)
def test_tracker_implements_what_it_declares(provider: Provider, cls: type[WorkTracker]) -> None:
    caps = cls.capabilities
    assert cls.label, "a tracker needs a display label"
    if caps.direct_read:
        assert _overrides(cls, "fetch_items")
        if caps.hierarchy:
            assert _overrides(cls, "fetch_item") and _overrides(cls, "fetch_subtree")
    if caps.status_categories:
        assert _overrides(cls, "list_statuses")
    if caps.status_history:
        assert _overrides(cls, "fetch_status_changes")
    if caps.iterations:
        assert _overrides(cls, "fetch_iterations")
    if caps.create_items:
        assert _overrides(cls, "create_item")
    if caps.update_items:
        assert _overrides(cls, "update_item")
    if caps.webhooks:
        assert cls.webhook_signature_header or _overrides(cls, "verify_webhook")
        assert _overrides(cls, "parse_webhook")
    # The UI renders the connection and binding forms from these.
    assert cls.config_schema.model_json_schema()["type"] == "object"
    assert cls.scope_schema.model_json_schema()["type"] == "object"


@pytest.mark.parametrize(("provider", "cls"), TRACKERS, ids=TRACKER_IDS)
def test_tracker_has_no_way_to_write_status(provider: Provider, cls: type[WorkTracker]) -> None:
    """canopy never writes status to a tracker: no tracker exposes a transition."""
    names = [n.casefold() for n in dir(cls)]
    for forbidden in ("transition", "set_status", "update_status", "move_item"):
        assert not [n for n in names if forbidden in n], forbidden


@pytest.mark.parametrize(
    ("provider", "cls"),
    [(p, c) for p, c in TRACKERS if c.capabilities.webhooks],
    ids=[p.value for p, c in TRACKERS if c.capabilities.webhooks],
)
def test_tracker_webhook_verification_fails_closed(
    provider: Provider, cls: type[WorkTracker]
) -> None:
    body = b'{"event": "updated"}'
    header = cls.webhook_signature_header
    assert header is not None
    good = hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    assert cls.verify_webhook({header: f"sha256={good}"}, body, "s3cret")
    assert not cls.verify_webhook({header: f"sha256={good}"}, body, "")  # no secret
    assert not cls.verify_webhook({}, body, "s3cret")  # no signature
    assert not cls.verify_webhook({header: "sha256=" + "0" * 64}, body, "s3cret")  # forged
    assert not cls.verify_webhook({header: f"sha256={good}"}, body + b" ", "s3cret")  # altered


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
            out |= {f"{node.module}.{a.name}" for a in node.names}
    return out


def test_only_the_registry_and_provider_specific_reads_import_a_concrete_tracker() -> None:
    """The engine, links, ingest, drafts, workflow and board talk to `WorkTracker` only, so a
    new tracker is one module. Jira's own features (epic doc fields, Agile reads) are the
    allowed exceptions."""
    concrete = {f"app.connectors.{p.value}" for p in registered_trackers()}
    allowed = {
        APP / "connectors" / "__init__.py",
        APP / "services" / "doc_graph.py",  # Jira epic doc-field harvest
        APP / "api" / "v1" / "connectors" / "_shared.py",  # provider-specific reads
    }
    offenders = []
    for path in sorted(APP.rglob("*.py")):
        if path in allowed or path.stem in {p.value for p in registered_trackers()}:
            continue
        hits = {m for m in _imports(path) for c in concrete if m == c or m.startswith(c + ".")}
        if hits:
            offenders.append(f"{path.relative_to(APP)}: {sorted(hits)}")
    assert offenders == []


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


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


async def _user(client: Any, admin: dict[str, str], role: str) -> tuple[int, dict[str, str]]:
    created = await client.post(
        "/api/v1/auth/register",
        json={"email": f"{role}@example.com", "password": "pw12345678", "role": role},
        headers=admin,
    )
    return created.json()["id"], await _login(client, f"{role}@example.com", "pw12345678")


async def _demo_jira(session: Any, **config: Any) -> Connection:
    connection = Connection(
        provider=Provider.jira,
        name="jira",
        encrypted_token=encrypt_token("demo-token"),
        config={
            "demo": True,
            "base_url": "https://jira.example.com",
            "jira_project_key": "SHOP",
            **config,
        },
    )
    session.add(connection)
    await session.commit()
    return connection


async def _project(session: Any, key: str, **fields: Any) -> Project:
    project = Project(key=key, name=key.title(), **fields)
    session.add(project)
    await session.commit()
    return project


# --------------------------------------------------------------------------- #
# Retired names (the pre-tracker aliases, one release after the port)
# --------------------------------------------------------------------------- #

RETIRED = (
    "/jira-links",
    "push-to-jira",
    "jira_account_id",
    "jira_issue_id",
    '"jira_key"',
    "legacy_connection_id",
    "legacy_provider",
    "legacy_label",
    "JiraLink",
)


def test_no_retired_name_remains_in_the_api() -> None:
    """Every Jira-named surface kept its old name as an alias for one release; that release is
    over. What stays Jira-named is Jira's own (Agile boards/sprints, epic doc fields, the
    one-issue changelog replay)."""
    spec = main_app.openapi()
    text = json.dumps(spec)
    assert [name for name in RETIRED if name in text] == []
    schemas = spec["components"]["schemas"]
    assert "jira" not in schemas["TaskExternalLinksRead"]["properties"]
    assert "sprint" not in schemas["TaskRead"]["properties"]  # `sprint_id` is the membership
    jira_paths = sorted(p for p in spec["paths"] if "/jira" in p)
    assert all(p.startswith("/api/v1/connectors/jira/") for p in jira_paths), jira_paths


# --------------------------------------------------------------------------- #
# Tracker links
# --------------------------------------------------------------------------- #


async def test_tracker_links_map_a_subtree_idempotently(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "DEMO_MODE", True)
    admin = await _admin(client, db_session)
    project = await _project(db_session, "SHOP")
    connection = await _demo_jira(db_session)
    listing = {"target_type": "project", "target_id": project.id}

    created = await client.post(
        "/api/v1/tracker-links",
        json={"connection_id": connection.id, "root_key": "SHOP-200", **listing},
        headers=admin,
    )
    assert created.status_code == 201, created.text
    result = created.json()
    assert result["tasks_created"] == 4  # the epic and its three stories
    link = result["link"]
    assert (link["provider"], link["root_key"], link["root_type"]) == ("jira", "SHOP-200", "Epic")
    assert link["url"] == "https://jira.example.com/browse/SHOP-200"

    listed = await client.get("/api/v1/tracker-links", params=listing, headers=admin)
    assert [row["id"] for row in listed.json()] == [link["id"]]
    again = (await client.post(f"/api/v1/tracker-links/{link['id']}/resync", headers=admin)).json()
    assert again["tasks_created"] == 0  # a re-sync updates, never duplicates

    tasks = (
        await db_session.execute(select(Task).where(Task.project_id == project.id))
    ).scalars().all()
    leaves = [t for t in tasks if t.type != TaskType.summary]
    assert len(leaves) == 3 and {t.status_owner for t in leaves} == {"jira"}  # status: Jira's

    gone = await client.delete(f"/api/v1/tracker-links/{link['id']}", headers=admin)
    assert gone.status_code == 204
    assert (await client.get("/api/v1/tracker-links", params=listing, headers=admin)).json() == []
    # Unlinking keeps what was mapped.
    kept = (
        await db_session.execute(select(Task).where(Task.project_id == project.id))
    ).scalars().all()
    assert len(kept) == 4


async def test_tracker_link_refuses_a_non_tracker_connection(client, db_session):
    admin = await _admin(client, db_session)
    project = await _project(db_session, "SHOP")
    github = Connection(provider=Provider.github, name="gh", config={"owner": "o", "repo": "r"})
    db_session.add(github)
    await db_session.commit()
    resp = await client.post(
        "/api/v1/tracker-links",
        json={
            "connection_id": github.id,
            "root_key": "X-1",
            "target_type": "project",
            "target_id": project.id,
        },
        headers=admin,
    )
    assert resp.status_code == 400 and "not a work tracker" in resp.json()["detail"]


# --------------------------------------------------------------------------- #
# Neutral ingest
# --------------------------------------------------------------------------- #


async def test_ingest_lands_in_the_bound_project_and_needs_a_target_when_ambiguous(db_session):
    first = await _project(db_session, "ALPHA")
    second = await _project(db_session, "BETA")
    connection = Connection(provider=Provider.jira, name="jira", config={})
    db_session.add(connection)
    await db_session.flush()
    assert connection.id is not None
    db_session.add(
        TrackerBinding(
            connection_id=connection.id,
            provider=Provider.jira,
            target_type="project",
            target_id=first.id,
            scope={"project_key": "ALPHA"},
        )
    )
    await db_session.commit()
    items = [
        IngestIssue(external_id="1", external_key="ALPHA-1", summary="Epic", kind="epic"),
        IngestIssue(
            external_id="2",
            external_key="ALPHA-2",
            summary="Story",
            parent_external_id="1",
            status="Doing",
            status_category="in_progress",
            estimate=3,
        ),
    ]
    result = await ingest.ingest_issues(db_session, connection, items)
    assert (result.created, result.updated, result.provider) == (2, 0, "jira")
    tasks = {
        t.name: t
        for t in (
            await db_session.execute(select(Task).where(Task.project_id == first.id))
        ).scalars().all()
    }
    assert tasks["Epic"].type == TaskType.summary
    story = tasks["Story"]
    assert story.parent_id == tasks["Epic"].id
    assert (story.status, story.status_category, story.story_points) == ("Doing", "in_progress", 3)

    db_session.add(
        TrackerBinding(
            connection_id=connection.id,
            provider=Provider.jira,
            target_type="project",
            target_id=second.id,
            scope={"project_key": "BETA"},
        )
    )
    await db_session.commit()
    other = [IngestIssue(external_id="9", external_key="BETA-1", summary="Beta story")]
    with pytest.raises(ValueError, match="several targets"):
        await ingest.ingest_issues(db_session, connection, other)
    pinned = await ingest.ingest_issues(db_session, connection, other, project_id=second.id)
    assert pinned.created == 1


async def test_ingest_endpoint_refuses_a_non_tracker_connection(client, db_session):
    admin = await _admin(client, db_session)
    github = Connection(provider=Provider.github, name="gh", config={"owner": "o", "repo": "r"})
    db_session.add(github)
    await db_session.commit()
    resp = await client.post(
        f"/api/v1/connectors/connections/{github.id}/ingest/issues",
        json={"issues": []},
        headers=admin,
    )
    assert resp.status_code == 400


# --------------------------------------------------------------------------- #
# Webhooks
# --------------------------------------------------------------------------- #


async def test_generic_webhook_is_404_for_anything_but_a_webhook_tracker(client):
    for path in ("/webhooks/nope", "/webhooks/gdrive"):
        assert (await client.post(path, content=b"{}")).status_code == 404


async def test_jira_webhook_is_routed_by_binding_scope(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "JIRA_WEBHOOK_SECRET", "s3cret")
    monkeypatch.setattr(tracker_webhook, "async_session_factory", TestSession)
    queued: list[tuple[str, tuple[Any, ...]]] = []

    async def fake_enqueue(name: str, *args: Any) -> None:
        queued.append((name, args))

    monkeypatch.setattr(tracker_webhook, "enqueue", fake_enqueue)
    project = await _project(db_session, "SHOP")
    connection = Connection(provider=Provider.jira, name="jira", config={})
    db_session.add(connection)
    await db_session.flush()
    assert connection.id is not None
    db_session.add(
        TrackerBinding(
            connection_id=connection.id,
            provider=Provider.jira,
            target_type="project",
            target_id=project.id,
            scope={"project_key": "SHOP"},
        )
    )
    await db_session.commit()

    for key, expected in (("SHOP-1", 1), ("OTHER-1", 0)):
        body = json.dumps({"issue": {"id": "1", "key": key}}).encode()
        signature = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
        resp = await client.post(
            "/webhooks/jira",
            content=body,
            headers={"X-Hub-Signature": signature, "Content-Type": "application/json"},
        )
        assert resp.status_code == 202 and resp.json() == {"enqueued": expected}, key
    assert queued == [("process_webhook", (connection.id, {"issue": {"id": "1", "key": "SHOP-1"}}))]


# --------------------------------------------------------------------------- #
# /meta/trackers
# --------------------------------------------------------------------------- #


async def test_meta_trackers_lists_trackers_and_what_they_support(client, db_session, monkeypatch):
    admin = await _admin(client, db_session)
    data = (await client.get("/api/v1/meta/trackers", headers=admin)).json()
    jira = next(t for t in data["trackers"] if t["provider"] == "jira")
    assert jira["enabled"] is True and jira["label"] == "Jira"
    assert jira["capabilities"]["create_items"] and jira["capabilities"]["webhooks"]
    assert jira["webhook_path"] == "/webhooks/jira"
    assert jira["webhook_secret_setting"] == "JIRA_WEBHOOK_SECRET"
    assert "properties" in jira["config_schema"] and "properties" in jira["scope_schema"]
    assert data["default_tracking_mode"] == "native"

    monkeypatch.setattr(settings, "TRACKERS_ENABLED", "")
    off = (await client.get("/api/v1/meta/trackers", headers=admin)).json()
    assert not any(t["enabled"] for t in off["trackers"])


# --------------------------------------------------------------------------- #
# Task links + PR key matching
# --------------------------------------------------------------------------- #


async def test_task_links_name_the_tracker_item(client, db_session):
    admin = await _admin(client, db_session)
    project = await _project(db_session, "SHOP")
    connection = Connection(
        provider=Provider.jira, name="jira", config={"base_url": "https://acme.example.com"}
    )
    task = Task(project_id=project.id, name="Mirrored", status_owner="jira", key="SHOP-7")
    db_session.add_all([connection, task])
    await db_session.flush()
    assert task.id is not None
    db_session.add(
        ExternalRef(
            provider=Provider.jira,
            external_id="70",
            external_key="SHOP-7",
            entity_type="task",
            entity_id=task.id,
            connection_id=connection.id,
        )
    )
    await db_session.commit()
    links = (await client.get(f"/api/v1/tasks/{task.id}/links", headers=admin)).json()
    assert links["tracker"] == {
        "provider": "jira",
        "label": "Jira",
        "key": "SHOP-7",
        "url": "https://acme.example.com/browse/SHOP-7",
    }


async def test_pull_requests_link_to_tasks_by_any_key(db_session):
    project = await _project(db_session, "SHOP")
    native = Task(project_id=project.id, name="Native", key="SHOP-12")
    mirrored = Task(project_id=project.id, name="Mirrored", key="PAY-7", status_owner="jira")
    db_session.add_all([native, mirrored])
    await db_session.flush()
    assert mirrored.id is not None
    db_session.add(
        ExternalRef(
            provider=Provider.jira,
            external_id="77",
            external_key="PAY-7",
            entity_type="task",
            entity_id=mirrored.id,
        )
    )
    await db_session.commit()

    for number, title, branch in (
        (1, "Speed up checkout", "feat/shop-12-checkout"),
        (2, "PAY-7: retry captures", None),
        (3, "No key here", "main"),
    ):
        await ingest.upsert_pull_request(
            db_session, repo="o/r", number=number, title=title, state="open", branch=branch
        )
    await db_session.commit()
    prs = {
        pr.number: pr.task_id
        for pr in (await db_session.execute(select(PullRequest))).scalars().all()
    }
    assert prs == {1: native.id, 2: mirrored.id, 3: None}
    assert ingest.issue_keys("SHOP-1 then shop-1, ENG-42", None) == ["SHOP-1", "ENG-42"]


# --------------------------------------------------------------------------- #
# Mirrored projects: the tracker owns the columns
# --------------------------------------------------------------------------- #


async def test_mirrored_project_shows_its_trackers_columns(client, db_session):
    admin = await _admin(client, db_session)
    project = await _project(db_session, "SHOP", tracking_mode="mirrored")
    connection = Connection(provider=Provider.jira, name="jira", config={})
    db_session.add(connection)
    await db_session.flush()
    assert connection.id is not None
    db_session.add(
        TrackerBinding(
            connection_id=connection.id,
            provider=Provider.jira,
            target_type="project",
            target_id=project.id,
            scope={"project_key": "SHOP"},
            status_map=[
                {"name": "Open", "category": "todo", "position": 0},
                {"name": "Doing", "category": "in_progress", "position": 1},
                {"name": "Closed", "category": "done", "position": 2},
            ],
        )
    )
    await db_session.commit()

    workflow = (
        await client.get(f"/api/v1/projects/{project.id}/workflow", headers=admin)
    ).json()
    assert workflow["scope"] == "tracker" and workflow["name"] == "Jira workflow"
    assert [c["name"] for c in workflow["columns"]] == ["Open", "Doing", "Closed"]
    refused = await client.put(
        f"/api/v1/projects/{project.id}/workflow",
        json={"columns": [{"name": "Mine", "category": "todo"}]},
        headers=admin,
    )
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "workflow_externally_owned"
    board = (await client.get(f"/api/v1/projects/{project.id}/board", headers=admin)).json()
    assert [lane["status"] for lane in board["lanes"] if lane["in_workflow"]] == [
        "Open",
        "Doing",
        "Closed",
    ]


# --------------------------------------------------------------------------- #
# WIP: the board counts what the move check enforces
# --------------------------------------------------------------------------- #


async def test_team_wip_limit_counts_every_project_on_the_team_columns(client, db_session):
    admin = await _admin(client, db_session)
    team = (
        await client.post("/api/v1/teams", json={"key": "PAY", "name": "Payments"}, headers=admin)
    ).json()
    pod = (
        await client.post(
            f"/api/v1/teams/{team['id']}/pods", json={"name": "Core"}, headers=admin
        )
    ).json()
    ids = []
    for key in ("ALPHA", "BETA"):
        created = await client.post(
            "/api/v1/projects", json={"key": key, "name": key.title()}, headers=admin
        )
        pid = created.json()["id"]
        await client.patch(f"/api/v1/projects/{pid}", json={"pod_id": pod["id"]}, headers=admin)
        ids.append(pid)
    alpha, beta = ids
    columns = [
        {"name": "To Do", "category": "todo"},
        {"name": "Doing", "category": "in_progress", "wip_limit": 1},
        {"name": "Done", "category": "done"},
    ]
    saved = await client.put(
        f"/api/v1/teams/{team['id']}/workflow",
        json={"wip_enforcement": "block", "columns": columns},
        headers=admin,
    )
    assert saved.status_code == 200, saved.text

    async def task(project_id: int, name: str, **extra: Any) -> dict[str, Any]:
        resp = await client.post(
            "/api/v1/tasks",
            json={"project_id": project_id, "name": name, "duration": 1, **extra},
            headers=admin,
        )
        assert resp.status_code == 201, resp.text
        return dict(resp.json())

    await task(alpha, "Alpha work", status="Doing")
    waiting = await task(beta, "Beta work")

    board = (await client.get(f"/api/v1/projects/{beta}/board", headers=admin)).json()
    doing = next(lane for lane in board["lanes"] if lane["status"] == "Doing")
    assert (doing["wip"], doing["scope_wip"], doing["over_limit"]) == (0, 1, False)
    blocked = await client.post(
        f"/api/v1/tasks/{waiting['id']}/move", json={"to_status": "Doing"}, headers=admin
    )
    assert blocked.status_code == 409 and blocked.json()["detail"]["code"] == "wip_limit_reached"

    # With its own columns, Beta counts only its own cards.
    own = await client.put(
        f"/api/v1/projects/{beta}/workflow",
        json={"wip_enforcement": "block", "columns": columns},
        headers=admin,
    )
    assert own.status_code == 200, own.text
    moved = await client.post(
        f"/api/v1/tasks/{waiting['id']}/move", json={"to_status": "Doing"}, headers=admin
    )
    assert moved.status_code == 200, moved.text


# --------------------------------------------------------------------------- #
# Card-move rules (shared by the board's viewer and POST /tasks/{id}/move)
# --------------------------------------------------------------------------- #


async def test_move_rules_for_viewers_engineers_and_planners_outside_the_project(
    client, db_session
):
    admin = await _admin(client, db_session)
    viewer_id, viewer = await _user(client, admin, "viewer")
    engineer_id, engineer = await _user(client, admin, "engineer")
    manager_id, manager = await _user(client, admin, "engineering_manager")

    async def person(name: str, user_id: int | None = None) -> int:
        body: dict[str, Any] = {"name": name}
        if user_id is not None:
            body["user_id"] = user_id
        resp = await client.post("/api/v1/team/engineers", json=body, headers=admin)
        return int(resp.json()["id"])

    ada = await person("Ada", engineer_id)
    eve = await person("Eve", manager_id)
    owner = await person("Owner")
    await person("Vic", viewer_id)
    project = (
        await client.post("/api/v1/projects", json={"key": "CHK", "name": "Checkout"},
                          headers=admin)
    ).json()["id"]
    # An owned project: a manager who doesn't own it can't plan it.
    await client.patch(
        f"/api/v1/projects/{project}", json={"owner_engineer_id": owner}, headers=admin
    )

    async def task(name: str, **extra: Any) -> int:
        resp = await client.post(
            "/api/v1/tasks",
            json={"project_id": project, "name": name, "duration": 1, **extra},
            headers=admin,
        )
        return int(resp.json()["id"])

    free = await task("Free")
    other = await task("Unassigned too")
    eves = await task("Eve's", assignee_engineer_id=eve)
    adas = await task("Ada's", assignee_engineer_id=ada)

    async def viewer_of(headers: dict[str, str]) -> dict[str, Any]:
        board = await client.get(f"/api/v1/projects/{project}/board", headers=headers)
        return dict(board.json()["viewer"])

    assert (await viewer_of(viewer))["engineer_id"] is None  # viewers move nothing
    assert await viewer_of(manager) == {"can_plan": False, "engineer_id": eve,
                                        "native_enabled": True}

    async def move(headers: dict[str, str], task_id: int, **body: Any) -> Any:
        return await client.post(f"/api/v1/tasks/{task_id}/move", json=body, headers=headers)

    # Reordering an unassigned card doesn't take it; moving it to another column does.
    assert (await move(engineer, free, position="top")).status_code == 403
    pulled = await move(engineer, free, to_status="In Progress")
    assert pulled.status_code == 200
    assert pulled.json()["task"]["assignee_engineer_id"] == ada
    # A manager outside the project still moves their own cards…
    assert (await move(manager, eves, to_status="In Progress")).status_code == 200
    # …but not someone else's: the refusal says why (ownership).
    refused = await move(manager, adas, to_status="In Progress")
    assert refused.status_code == 403
    assert refused.json()["detail"]["code"] == "not_initiative_lead"
    assert (await move(manager, other, to_status="In Progress")).status_code == 200


async def test_expected_status_accepts_the_no_status_label(client, db_session):
    """The board labels a status-less card "(no status)"; echoing that label (or "") as the
    expected status is not a conflict, anything else is."""
    admin = await _admin(client, db_session)
    project = await _project(db_session, "CHK")
    task = Task(project_id=project.id, name="Inbox card", status=None)
    db_session.add(task)
    await db_session.commit()
    url = f"/api/v1/tasks/{task.id}/move"
    stale = await client.post(url, json={"to_status": "To Do", "expected_status": "Done"},
                              headers=admin)
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "stale"
    moved = await client.post(
        url, json={"to_status": "To Do", "expected_status": "(no status)"}, headers=admin
    )
    assert moved.status_code == 200, moved.text


# --------------------------------------------------------------------------- #
# Nightly changelog backfill
# --------------------------------------------------------------------------- #


async def test_nightly_backfill_walks_the_refs_with_a_cursor(db_session, monkeypatch):
    monkeypatch.setattr(settings, "DEMO_MODE", True)
    project = await _project(db_session, "SHOP", tracking_mode="mirrored")
    connection = await _demo_jira(db_session)
    assert connection.id is not None
    binding = TrackerBinding(
        connection_id=connection.id,
        provider=Provider.jira,
        target_type="project",
        target_id=project.id,
        scope={"project_key": "SHOP"},
    )
    db_session.add(binding)
    refs: list[ExternalRef] = []
    for n in range(3):
        task = Task(project_id=project.id, name=f"Story {n}", status_owner="jira")
        db_session.add(task)
        await db_session.flush()
        assert task.id is not None
        ref = ExternalRef(
            provider=Provider.jira,
            external_id=f"93020{n + 1}",
            external_key=f"SHOP-20{n + 1}",
            entity_type="task",
            entity_id=task.id,
            connection_id=connection.id,
        )
        db_session.add(ref)
        refs.append(ref)
    await db_session.commit()
    tracker = get_connector(connection, db_session)
    assert isinstance(tracker, WorkTracker)
    view = tracker_sync.view_of(binding)

    # The demo changelog has two transitions per issue.
    assert await tracker_sync.backfill_pending(tracker, view, limit=2) == 4
    assert binding.backfill_cursor == refs[1].id
    assert await tracker_sync.backfill_pending(tracker, view, limit=2) == 2
    assert binding.backfill_cursor == refs[2].id
    assert await tracker_sync.backfill_pending(tracker, view, limit=2) == 0
    assert binding.backfill_cursor is None  # wrapped: the next night starts over
    rows = (await db_session.execute(select(TaskStatusHistory))).scalars().all()
    assert len(rows) == 6 and {r.source for r in rows} == {"backfill"}


# --------------------------------------------------------------------------- #
# Finalising a reviewed draft plan follows the project's tracking mode
# --------------------------------------------------------------------------- #


async def _draft_plan(client: Any, admin: dict[str, str], project_id: int) -> int:
    plan = (
        await client.post(
            f"/api/v1/projects/{project_id}/draft-plans", json={"title": "Q3"}, headers=admin
        )
    ).json()["id"]
    epic = (
        await client.post(
            f"/api/v1/draft-plans/{plan}/tasks",
            json={"name": "Auth epic", "type": "summary"},
            headers=admin,
        )
    ).json()
    await client.post(
        f"/api/v1/draft-plans/{plan}/tasks",
        json={"name": "Login", "parent_id": epic["id"], "estimate_days": 3, "story_points": 5},
        headers=admin,
    )
    return int(plan)


async def test_finalize_into_a_native_project_creates_canopy_tasks_once(client, db_session):
    admin = await _admin(client, db_session)
    project = (
        await client.post("/api/v1/projects", json={"key": "AUTH", "name": "Auth"},
                          headers=admin)
    ).json()["id"]
    plan = await _draft_plan(client, admin, project)

    agent = (await client.post("/api/v1/auth/agent-token", json={}, headers=admin)).json()
    agent_headers = {"Authorization": f"Bearer {agent['access_token']}"}
    url = f"/api/v1/draft-plans/{plan}/finalize"
    assert (await client.post(url, json={}, headers=agent_headers)).status_code == 403

    done = await client.post(url, json={}, headers=admin)
    assert done.status_code == 200, done.text
    result = done.json()
    assert (result["mode"], result["created"], result["failed"]) == ("native", 2, 0)
    tasks = {
        t.name: t
        for t in (
            await db_session.execute(select(Task).where(Task.project_id == project))
        ).scalars().all()
    }
    login = tasks["Login"]
    assert login.parent_id == tasks["Auth epic"].id and login.story_points == 5
    assert login.status_owner == "canopy" and login.status and login.key.startswith("AUTH-")

    again = (await client.post(url, json={}, headers=admin)).json()
    assert (again["created"], again["updated"]) == (0, 2)  # an update, never a duplicate
    count = (
        await db_session.execute(select(Task).where(Task.project_id == project))
    ).scalars().all()
    assert len(count) == 2


async def test_finalize_into_a_mirrored_project_pushes_content_to_its_tracker(
    client, db_session, monkeypatch
):
    monkeypatch.setattr(settings, "DEMO_MODE", True)
    admin = await _admin(client, db_session)
    project = await _project(db_session, "SHOP", tracking_mode="mirrored")
    connection = await _demo_jira(db_session)
    assert connection.id is not None
    db_session.add(
        TrackerBinding(
            connection_id=connection.id,
            provider=Provider.jira,
            target_type="project",
            target_id=project.id,
            scope={"project_key": "SHOP"},
        )
    )
    await db_session.commit()
    plan = await _draft_plan(client, admin, project.id)

    done = await client.post(f"/api/v1/draft-plans/{plan}/finalize", json={}, headers=admin)
    assert done.status_code == 200, done.text
    result = done.json()
    assert (result["mode"], result["provider"], result["created"]) == ("tracker", "jira", 2)
    assert all(r["external_key"].startswith("SHOP-") for r in result["results"])
    # Content only: no canopy task is created on push (the next sync pulls them back).
    assert (
        await db_session.execute(select(Task).where(Task.project_id == project.id))
    ).scalars().all() == []


async def test_a_sync_survives_a_tracker_that_hides_its_changelog(db_session, monkeypatch):
    """The first sync replays new items' changelogs, but only as a bonus: a tracker that
    refuses (no permission, no endpoint) still gets its items synced."""
    monkeypatch.setattr(settings, "DEMO_MODE", True)
    project = await _project(db_session, "SHOP", tracking_mode="mirrored")
    connection = await _demo_jira(db_session)
    assert connection.id is not None
    binding = TrackerBinding(
        connection_id=connection.id,
        provider=Provider.jira,
        target_type="project",
        target_id=project.id,
        scope={"project_key": "SHOP"},
    )
    db_session.add(binding)
    await db_session.commit()
    tracker = get_connector(connection, db_session)
    assert isinstance(tracker, WorkTracker)

    async def refuse(*_: Any, **__: Any) -> Any:
        raise RuntimeError("403 Forbidden")

    monkeypatch.setattr(type(tracker), "fetch_status_changes", refuse)
    result = await tracker_sync.sync_binding(tracker, tracker_sync.view_of(binding), full=True)
    assert result.created == 4
