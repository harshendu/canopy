from datetime import datetime, timedelta

import pytest
from sqlmodel import select

from app.core.security import hash_password
from app.models.activity import ActivityEvent
from app.models.base import utcnow
from app.models.project import Initiative, Project, Task, TaskStatusHistory
from app.models.user import User
from app.services import flow_metrics

# --- pure: DORA ------------------------------------------------------------------

def _pt(kind: str, at: datetime) -> flow_metrics.ActivityPoint:
    return flow_metrics.ActivityPoint(kind=kind, at=at)


def test_compute_dora_frequency_cfr_and_recovery() -> None:
    base = datetime(2026, 5, 1, 9, 0, 0)
    events = [
        _pt("deploy", base),
        _pt("deploy", base + timedelta(days=1)),
        _pt("deploy", base + timedelta(days=2)),
        _pt("deploy", base + timedelta(days=3)),
        _pt("incident_open", base + timedelta(days=2, hours=1)),
        _pt("incident_close", base + timedelta(days=2, hours=4)),  # 3h recovery
    ]
    dora = flow_metrics.compute_dora(events, window_weeks=2.0)
    assert dora.deploys == 4
    assert dora.deploy_frequency_per_week == 2.0
    assert dora.failures == 1
    assert dora.change_fail_rate == 0.25
    assert dora.recovered_incidents == 1
    assert dora.mean_recovery_hours == 3.0


def test_compute_dora_no_deploys_cfr_is_none() -> None:
    dora = flow_metrics.compute_dora([_pt("incident_open", datetime(2026, 5, 1))], 4.0)
    assert dora.deploys == 0
    assert dora.change_fail_rate is None
    assert dora.mean_recovery_hours is None  # open never closed


# --- pure: flow ------------------------------------------------------------------

def test_compute_flow_sufficient() -> None:
    flow = flow_metrics.compute_flow(
        throughput=[2, 0, 3, 1], cycle_samples=[4, 6, 10], wip=5, aging_wip=2
    )
    assert flow.sufficient is True
    assert flow.completed_items == 3
    assert flow.throughput_per_week == 1.5
    assert flow.cycle_time_median_days == 6.0
    assert flow.cycle_time_p85_days == 10
    assert flow.wip == 5
    assert flow.aging_wip == 2


def test_compute_flow_insufficient_history() -> None:
    flow = flow_metrics.compute_flow(throughput=[1], cycle_samples=[3], wip=1, aging_wip=0)
    assert flow.sufficient is False
    assert flow.reason is not None


# --- API -------------------------------------------------------------------------

async def _seed_admin(session) -> None:
    session.add(
        User(email="a@e.com", hashed_password=hash_password("secret123"), role="admin")
    )
    await session.commit()


async def _token(client) -> str:
    resp = await client.post(
        "/api/v1/auth/login", data={"username": "a@e.com", "password": "secret123"}
    )
    return resp.json()["access_token"]


@pytest.mark.asyncio
async def test_project_delivery_endpoint(client, db_session) -> None:
    await _seed_admin(db_session)
    headers = {"Authorization": f"Bearer {await _token(client)}"}

    project = Project(key="PLAT", name="Platform")
    db_session.add(project)
    await db_session.flush()
    now = utcnow()
    # two deploys + one incident opened & closed (2h)
    db_session.add_all(
        [
            ActivityEvent(project_id=project.id, kind="deploy", summary="d1"),
            ActivityEvent(project_id=project.id, kind="deploy", summary="d2"),
            ActivityEvent(project_id=project.id, kind="incident_open", summary="i1"),
            ActivityEvent(project_id=project.id, kind="incident_close", summary="i1 done"),
        ]
    )
    # a done task with status history (completed recently)
    task = Task(project_id=project.id, name="T", status="Done")
    db_session.add(task)
    await db_session.flush()
    db_session.add(
        TaskStatusHistory(task_id=task.id, to_status="Done", changed_at=now - timedelta(days=2))
    )
    await db_session.commit()

    resp = await client.get(
        f"/api/v1/projects/{project.id}/delivery", params={"weeks": 8}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scope_level"] == "project"
    assert body["window_weeks"] == 8
    assert body["dora"]["deploys"] == 2
    assert body["dora"]["failures"] == 1
    assert body["dora"]["change_fail_rate"] == 0.5
    assert body["flow"]["completed_items"] == 1
    assert any("Team-level only" in n for n in body["notes"])


@pytest.mark.asyncio
async def test_initiative_delivery_aggregates_projects(client, db_session) -> None:
    await _seed_admin(db_session)
    headers = {"Authorization": f"Bearer {await _token(client)}"}

    initiative = Initiative(key="Q3", name="Q3")
    db_session.add(initiative)
    await db_session.flush()
    p1 = Project(key="A", name="A", initiative_id=initiative.id)
    p2 = Project(key="B", name="B", initiative_id=initiative.id)
    db_session.add_all([p1, p2])
    await db_session.flush()
    db_session.add_all(
        [
            ActivityEvent(project_id=p1.id, kind="deploy", summary="d"),
            ActivityEvent(project_id=p2.id, kind="deploy", summary="d"),
            ActivityEvent(project_id=p2.id, kind="deploy", summary="d"),
        ]
    )
    await db_session.commit()

    resp = await client.get(
        f"/api/v1/initiatives/{initiative.id}/delivery", headers=headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scope_level"] == "initiative"
    assert body["dora"]["deploys"] == 3  # summed across both projects


@pytest.mark.asyncio
async def test_delivery_404_for_missing_project(client, db_session) -> None:
    await _seed_admin(db_session)
    headers = {"Authorization": f"Bearer {await _token(client)}"}
    resp = await client.get("/api/v1/projects/999/delivery", headers=headers)
    assert resp.status_code == 404
    # an empty-but-valid scope reports zeros + an instrumentation note
    project = (
        await client.post("/api/v1/projects", json={"key": "E", "name": "E"}, headers=headers)
    ).json()
    empty = (
        await client.get(f"/api/v1/projects/{project['id']}/delivery", headers=headers)
    ).json()
    assert empty["dora"]["deploys"] == 0
    assert any("No deploy/incident activity" in n for n in empty["notes"])
    # ensure no stray rows leaked
    assert (await db_session.execute(select(ActivityEvent))).scalars().first() is None
