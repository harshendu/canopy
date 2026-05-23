from datetime import date

import pytest

from app.core.security import hash_password
from app.models.base import UserRole
from app.models.user import User
from app.services.retro import RetroInputs, generate_project_retro

# --- Pure generator ----------------------------------------------------------


def test_generate_project_retro_renders_state():
    body = generate_project_retro(
        RetroInputs(
            project_name="Platform",
            generated_on=date(2026, 5, 23),
            completed_milestones=["Beta (2026-04-01)"],
            total_tasks=10,
            completed_tasks=6,
            drifted_tasks=2,
            open_drift_events=3,
            adr_total=4,
            adr_accepted=2,
            adr_superseded=1,
        )
    )
    assert "# Retrospective — Platform" in body
    assert "6/10 tasks complete (60%)" in body
    assert "Beta (2026-04-01)" in body
    assert "2 task(s) ended off their baseline" in body
    assert "churn 25%" in body  # 1/4 superseded


def test_generate_project_retro_handles_empty_project():
    body = generate_project_retro(
        RetroInputs(project_name="New", generated_on=date(2026, 1, 1))
    )
    assert "0/0 tasks complete (0%)" in body
    assert "No milestones marked complete" in body


# --- API ---------------------------------------------------------------------


async def _seed_admin(session) -> None:
    session.add(
        User(
            email="architect@example.com",
            hashed_password=hash_password("secret123"),
            role=UserRole.admin,
        )
    )
    await session.commit()


async def _token(client, email: str = "architect@example.com", password: str = "secret123") -> str:
    resp = await client.post(
        "/api/v1/auth/login", data={"username": email, "password": password}
    )
    return resp.json()["access_token"]


@pytest.mark.asyncio
async def test_project_retro_autoseeds_comments_and_follow_ups(client, db_session):
    await _seed_admin(db_session)
    headers = {"Authorization": f"Bearer {await _token(client)}"}
    project_id = (
        await client.post(
            "/api/v1/projects", json={"key": "PLAT", "name": "Platform"}, headers=headers
        )
    ).json()["id"]
    # Some state to seed from.
    await client.post(
        "/api/v1/milestones",
        json={"project_id": project_id, "name": "Beta", "status": "hit"},
        headers=headers,
    )

    created = await client.post(
        f"/api/v1/projects/{project_id}/retrospectives", json={}, headers=headers
    )
    assert created.status_code == 201, created.text
    retro = created.json()
    assert retro["kind"] == "project_retro"
    assert "Retrospective — Platform" in retro["body"]
    retro_id = retro["id"]

    # Comment thread.
    c = await client.post(
        f"/api/v1/projects/{project_id}/retrospectives/{retro_id}/comments",
        json={"body": "Estimation was optimistic"},
        headers=headers,
    )
    assert c.status_code == 201
    detail = (
        await client.get(
            f"/api/v1/projects/{project_id}/retrospectives/{retro_id}", headers=headers
        )
    ).json()
    assert [x["body"] for x in detail["comments"]] == ["Estimation was optimistic"]

    # Follow-up: mint a task and propose an ADR.
    task_resp = await client.post(
        f"/api/v1/projects/{project_id}/retrospectives/{retro_id}/follow-up",
        json={"action": "task", "title": "Add load tests"},
        headers=headers,
    )
    assert task_resp.json()["created_task_id"] is not None
    adr_resp = await client.post(
        f"/api/v1/projects/{project_id}/retrospectives/{retro_id}/follow-up",
        json={"action": "adr", "title": "Adopt load testing"},
        headers=headers,
    )
    assert adr_resp.json()["created_adr_id"] is not None

    # Close it.
    closed = await client.patch(
        f"/api/v1/projects/{project_id}/retrospectives/{retro_id}",
        json={"status": "closed"},
        headers=headers,
    )
    assert closed.json()["status"] == "closed"


@pytest.mark.asyncio
async def test_retro_rbac_engineer_comments_viewer_readonly(client, db_session):
    await _seed_admin(db_session)
    admin = {"Authorization": f"Bearer {await _token(client)}"}
    for role in ("engineer", "viewer"):
        await client.post(
            "/api/v1/auth/register",
            json={"email": f"{role}@x.com", "password": "pw12345678", "role": role},
            headers=admin,
        )
    eng = {"Authorization": f"Bearer {await _token(client, 'engineer@x.com', 'pw12345678')}"}
    viewer = {"Authorization": f"Bearer {await _token(client, 'viewer@x.com', 'pw12345678')}"}

    project_id = (
        await client.post(
            "/api/v1/projects", json={"key": "PLAT", "name": "Platform"}, headers=admin
        )
    ).json()["id"]

    # Engineers can't create a retro (planner-owned)...
    assert (
        await client.post(
            f"/api/v1/projects/{project_id}/retrospectives", json={}, headers=eng
        )
    ).status_code == 403
    retro_id = (
        await client.post(
            f"/api/v1/projects/{project_id}/retrospectives", json={}, headers=admin
        )
    ).json()["id"]
    # ...but they can comment.
    assert (
        await client.post(
            f"/api/v1/projects/{project_id}/retrospectives/{retro_id}/comments",
            json={"body": "+1"},
            headers=eng,
        )
    ).status_code == 201
    # Viewers can read but not comment.
    assert (
        await client.get(
            f"/api/v1/projects/{project_id}/retrospectives/{retro_id}", headers=viewer
        )
    ).status_code == 200
    assert (
        await client.post(
            f"/api/v1/projects/{project_id}/retrospectives/{retro_id}/comments",
            json={"body": "nope"},
            headers=viewer,
        )
    ).status_code == 403
