import pytest

from app.core.security import hash_password
from app.models.base import CriterionStatus
from app.models.spec import SpecCriterion
from app.models.user import User
from app.services import specs as spec_service

# --- pure: readiness ------------------------------------------------------------

def _crit(status: CriterionStatus) -> SpecCriterion:
    return SpecCriterion(spec_id=1, text="x", status=status)


def test_readiness_excludes_waived() -> None:
    criteria = [
        _crit(CriterionStatus.met),
        _crit(CriterionStatus.met),
        _crit(CriterionStatus.unmet),
        _crit(CriterionStatus.waived),  # excluded from both
    ]
    met, total, ratio = spec_service.readiness(criteria)
    assert met == 2
    assert total == 3  # waived dropped
    assert ratio == round(2 / 3, 3)


def test_readiness_empty_is_zero() -> None:
    assert spec_service.readiness([]) == (0, 0, 0.0)


# --- API ------------------------------------------------------------------------

async def _seed_admin(session) -> None:
    session.add(
        User(
            email="architect@example.com",
            hashed_password=hash_password("secret123"),
            role="admin",
        )
    )
    await session.commit()


async def _token(client) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "architect@example.com", "password": "secret123"},
    )
    return resp.json()["access_token"]


async def _project(client, headers) -> int:
    return (
        await client.post(
            "/api/v1/projects", json={"key": "PLAT", "name": "Platform"}, headers=headers
        )
    ).json()["id"]


@pytest.mark.asyncio
async def test_spec_lifecycle_and_self_audit(client, db_session) -> None:
    await _seed_admin(db_session)
    headers = {"Authorization": f"Bearer {await _token(client)}"}
    project_id = await _project(client, headers)

    spec = await client.post(
        "/api/v1/specs",
        json={
            "project_id": project_id,
            "title": "Probabilistic forecast",
            "problem": "Give an honest ship date for knowledge work.",
            "out_of_scope": "Resource leveling.",
        },
        headers=headers,
    )
    assert spec.status_code == 201, spec.text
    spec_id = spec.json()["id"]
    assert spec.json()["status"] == "draft"

    # two acceptance criteria
    c1 = (
        await client.post(
            f"/api/v1/specs/{spec_id}/criteria",
            json={"text": "Reports P50 and P85", "verification": "test_forecast"},
            headers=headers,
        )
    ).json()
    await client.post(
        f"/api/v1/specs/{spec_id}/criteria",
        json={"text": "Says 'insufficient' under 3 weeks data"},
        headers=headers,
    )

    # a task implementing the spec
    task = (
        await client.post(
            "/api/v1/tasks",
            json={"project_id": project_id, "name": "Build forecast", "duration": 3},
            headers=headers,
        )
    ).json()
    linked = await client.patch(
        f"/api/v1/tasks/{task['id']}", json={"spec_id": spec_id}, headers=headers
    )
    assert linked.status_code == 200
    assert linked.json()["spec_id"] == spec_id

    # detail bundle: 2 criteria, 1 linked task, 0% ready
    detail = (await client.get(f"/api/v1/specs/{spec_id}", headers=headers)).json()
    assert len(detail["criteria"]) == 2
    assert len(detail["linked_tasks"]) == 1
    assert detail["linked_tasks"][0]["id"] == task["id"]
    assert detail["criteria_total"] == 2
    assert detail["criteria_met"] == 0
    assert detail["acceptance_ratio"] == 0.0

    # self-audit: mark one met
    audited = await client.patch(
        f"/api/v1/criteria/{c1['id']}",
        json={"status": "met", "verification": "verified by test_forecast"},
        headers=headers,
    )
    assert audited.status_code == 200
    assert audited.json()["status"] == "met"

    detail = (await client.get(f"/api/v1/specs/{spec_id}", headers=headers)).json()
    assert detail["criteria_met"] == 1
    assert detail["acceptance_ratio"] == 0.5


@pytest.mark.asyncio
async def test_delete_spec_unlinks_tasks(client, db_session) -> None:
    await _seed_admin(db_session)
    headers = {"Authorization": f"Bearer {await _token(client)}"}
    project_id = await _project(client, headers)
    spec_id = (
        await client.post(
            "/api/v1/specs",
            json={"project_id": project_id, "title": "S", "problem": "p"},
            headers=headers,
        )
    ).json()["id"]
    task = (
        await client.post(
            "/api/v1/tasks",
            json={"project_id": project_id, "name": "T", "duration": 1},
            headers=headers,
        )
    ).json()
    await client.patch(f"/api/v1/tasks/{task['id']}", json={"spec_id": spec_id}, headers=headers)

    deleted = await client.delete(f"/api/v1/specs/{spec_id}", headers=headers)
    assert deleted.status_code == 204
    # the task survives, unlinked
    after = (await client.get(f"/api/v1/tasks/{task['id']}/history", headers=headers)).status_code
    assert after == 200
    task_after = (
        await client.patch(
            f"/api/v1/tasks/{task['id']}", json={"name": "T2"}, headers=headers
        )
    ).json()
    assert task_after["spec_id"] is None


@pytest.mark.asyncio
async def test_create_spec_rejects_missing_project(client, db_session) -> None:
    await _seed_admin(db_session)
    headers = {"Authorization": f"Bearer {await _token(client)}"}
    resp = await client.post(
        "/api/v1/specs",
        json={"project_id": 999, "title": "S", "problem": "p"},
        headers=headers,
    )
    assert resp.status_code == 404
