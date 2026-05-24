from datetime import date

import pytest

from app.core.security import hash_password
from app.models.base import DependencyType, TaskType, UserRole
from app.models.project import Dependency, Initiative, Milestone, Project, Task
from app.models.team import Allocation, Engineer
from app.models.user import User


async def _seed_user(session, email: str, role: UserRole) -> None:
    session.add(User(email=email, hashed_password=hash_password("secret123"), role=role))
    await session.commit()


async def _token(client, email: str = "architect@example.com") -> str:
    resp = await client.post(
        "/api/v1/auth/login", data={"username": email, "password": "secret123"}
    )
    return resp.json()["access_token"]


async def _seed_initiative(session) -> dict:
    """An initiative with two projects, a cross-project dependency, an allocation, a milestone."""
    init = Initiative(key="Q3", name="Q3 Platform")
    session.add(init)
    await session.flush()
    pa = Project(key="PA", name="Alpha", initiative_id=init.id, start_date=date(2026, 1, 1))
    pb = Project(key="PB", name="Beta", initiative_id=init.id, start_date=date(2026, 1, 1))
    session.add(pa)
    session.add(pb)
    await session.flush()
    eng = Engineer(name="Dana")
    session.add(eng)
    await session.flush()
    a1 = Task(project_id=pa.id, name="A1", duration=5, start=date(2026, 1, 1),
              end=date(2026, 1, 6), type=TaskType.task)
    a2 = Task(project_id=pa.id, name="A2", duration=3, start=date(2026, 1, 6),
              end=date(2026, 1, 9), type=TaskType.task)
    b1 = Task(project_id=pb.id, name="B1", duration=4, start=date(2026, 1, 9),
              end=date(2026, 1, 13), type=TaskType.task)
    session.add_all([a1, a2, b1])
    await session.flush()
    session.add(Dependency(predecessor_id=a1.id, successor_id=a2.id, type=DependencyType.FS))
    session.add(Dependency(predecessor_id=a2.id, successor_id=b1.id, type=DependencyType.FS))
    session.add(
        Allocation(engineer_id=eng.id, project_id=pa.id, percent_allocation=100.0,
                   start_date=date(2026, 1, 1), end_date=date(2026, 2, 1))
    )
    session.add(Milestone(project_id=pa.id, name="GA", target_date=date(2026, 2, 1)))
    await session.commit()
    return {"initiative_id": init.id, "pa": pa.id, "pb": pb.id, "engineer_id": eng.id}


@pytest.mark.asyncio
async def test_scenario_snapshot_edit_compare_apply(client, db_session):
    await _seed_user(db_session, "architect@example.com", UserRole.admin)
    ids = await _seed_initiative(db_session)
    headers = {"Authorization": f"Bearer {await _token(client)}"}
    init_id, pa, pb, eng = ids["initiative_id"], ids["pa"], ids["pb"], ids["engineer_id"]

    # Create the scenario (snapshots the initiative).
    created = await client.post(
        f"/api/v1/initiatives/{init_id}/scenarios",
        json={"title": "Add an engineer & cut scope"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    sid = created.json()["id"]

    detail = (await client.get(f"/api/v1/scenarios/{sid}", headers=headers)).json()
    assert detail["counts"]["tasks"] == 3
    assert detail["counts"]["dependencies"] == 2
    assert detail["counts"]["milestones"] == 1
    assert detail["counts"]["allocations"] == 1
    assert detail["counts"]["projects"] == 2

    # Find the scenario task ids via the gantt view.
    gantt_pa = (
        await client.get(f"/api/v1/scenarios/{sid}/gantt?project_id={pa}", headers=headers)
    ).json()
    a2_sid = next(t["id"] for t in gantt_pa["tasks"] if t["text"] == "A2")

    # Edit: stretch A2, add a new task in PB + a dependency to it, add PTO for the engineer.
    assert (
        await client.patch(
            f"/api/v1/scenario-tasks/{a2_sid}", json={"duration": 9}, headers=headers
        )
    ).status_code == 200
    new_task = await client.post(
        f"/api/v1/scenarios/{sid}/tasks",
        json={"project_id": pb, "name": "B2", "duration": 2},
        headers=headers,
    )
    assert new_task.status_code == 201, new_task.text
    b2_sid = new_task.json()["id"]
    gantt_pb = (
        await client.get(f"/api/v1/scenarios/{sid}/gantt?project_id={pb}", headers=headers)
    ).json()
    b1_sid = next(t["id"] for t in gantt_pb["tasks"] if t["text"] == "B1")
    assert (
        await client.post(
            f"/api/v1/scenarios/{sid}/dependencies",
            json={"predecessor_id": b1_sid, "successor_id": b2_sid, "type": "FS"},
            headers=headers,
        )
    ).status_code == 201
    assert (
        await client.post(
            f"/api/v1/scenarios/{sid}/availability",
            json={"engineer_id": eng, "start_date": "2026-01-12", "end_date": "2026-01-23",
                  "capacity_factor": 0.0},
            headers=headers,
        )
    ).status_code == 201

    # Views recompute over the snapshot.
    cp = (await client.get(f"/api/v1/scenarios/{sid}/critical-path", headers=headers)).json()
    assert cp["spans_projects"] is True
    cap = (await client.get(f"/api/v1/scenarios/{sid}/capacity", headers=headers)).json()
    assert any(r["engineer_id"] == eng for r in cap["rows"])

    # Compare shows the deltas.
    compare = (await client.get(f"/api/v1/scenarios/{sid}/compare", headers=headers)).json()
    assert compare["diff"]["tasks_added"] == 1
    assert compare["diff"]["tasks_changed"] == 1
    assert compare["diff"]["deps_added"] == 1
    assert compare["diff"]["availability_changed"] == 1
    assert compare["conflicts"] == []

    # Apply writes back to live and replans.
    applied = await client.post(f"/api/v1/scenarios/{sid}/apply", json={}, headers=headers)
    assert applied.status_code == 200, applied.text
    assert applied.json()["status"] == "applied"
    assert applied.json()["created"] >= 1
    assert sorted(applied.json()["replanned_projects"]) == sorted([pa, pb])

    # Live now has the new task, the stretched duration, and the availability row.
    live_pb = (await client.get(f"/api/v1/tasks?project_id={pb}", headers=headers)).json()
    assert any(t["name"] == "B2" for t in live_pb)
    live_pa = (await client.get(f"/api/v1/tasks?project_id={pa}", headers=headers)).json()
    assert next(t for t in live_pa if t["name"] == "A2")["duration"] == 9
    avail = (
        await client.get(f"/api/v1/team/availability?engineer_id={eng}", headers=headers)
    ).json()
    assert len(avail) == 1

    # A re-edit is blocked once applied.
    assert (
        await client.post(
            f"/api/v1/scenarios/{sid}/tasks",
            json={"project_id": pb, "name": "late", "duration": 1},
            headers=headers,
        )
    ).status_code == 409


@pytest.mark.asyncio
async def test_scenario_apply_detects_stale_upstream(client, db_session):
    await _seed_user(db_session, "architect@example.com", UserRole.admin)
    ids = await _seed_initiative(db_session)
    headers = {"Authorization": f"Bearer {await _token(client)}"}
    init_id, pa = ids["initiative_id"], ids["pa"]

    sid = (
        await client.post(
            f"/api/v1/initiatives/{init_id}/scenarios",
            json={"title": "stale test"},
            headers=headers,
        )
    ).json()["id"]

    # Someone adds a task to the live project after the snapshot was captured.
    assert (
        await client.post(
            "/api/v1/tasks",
            json={"project_id": pa, "name": "Surprise", "duration": 2},
            headers=headers,
        )
    ).status_code == 201

    blocked = await client.post(f"/api/v1/scenarios/{sid}/apply", json={}, headers=headers)
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["reason"] == "stale"

    forced = await client.post(
        f"/api/v1/scenarios/{sid}/apply", json={"force": True}, headers=headers
    )
    assert forced.status_code == 200, forced.text
    assert forced.json()["status"] == "applied"


@pytest.mark.asyncio
async def test_scenario_writes_require_planner(client, db_session):
    await _seed_user(db_session, "architect@example.com", UserRole.admin)
    await _seed_user(db_session, "viewer@example.com", UserRole.viewer)
    ids = await _seed_initiative(db_session)
    admin = {"Authorization": f"Bearer {await _token(client)}"}
    viewer = {"Authorization": f"Bearer {await _token(client, 'viewer@example.com')}"}

    # A viewer cannot create a scenario.
    assert (
        await client.post(
            f"/api/v1/initiatives/{ids['initiative_id']}/scenarios",
            json={"title": "nope"},
            headers=viewer,
        )
    ).status_code == 403

    sid = (
        await client.post(
            f"/api/v1/initiatives/{ids['initiative_id']}/scenarios",
            json={"title": "ok"},
            headers=admin,
        )
    ).json()["id"]
    # ...but a viewer can read the views.
    assert (await client.get(f"/api/v1/scenarios/{sid}", headers=viewer)).status_code == 200
    # ...and cannot apply.
    assert (
        await client.post(f"/api/v1/scenarios/{sid}/apply", json={}, headers=viewer)
    ).status_code == 403
