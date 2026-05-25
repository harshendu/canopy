"""Bounded agency: an `agent`-scoped token is restricted from one-way-door / external-write
actions (the reversibility distinction is the human-in-the-loop policy), while two-way-door
actions run freely."""

import pytest

from app.core.security import hash_password
from app.models.base import UserRole
from app.models.user import User


async def _seed_admin(session) -> None:
    session.add(
        User(email="a@e.com", hashed_password=hash_password("secret123"), role=UserRole.admin)
    )
    await session.commit()


async def _full_token(client) -> str:
    resp = await client.post(
        "/api/v1/auth/login", data={"username": "a@e.com", "password": "secret123"}
    )
    return resp.json()["access_token"]


async def _agent_token(client, full_headers) -> str:
    resp = await client.post("/api/v1/auth/agent-token", json={}, headers=full_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["scope"] == "agent"
    return resp.json()["access_token"]


async def _project(client, headers) -> int:
    return (
        await client.post(
            "/api/v1/projects", json={"key": "PLAT", "name": "Platform"}, headers=headers
        )
    ).json()["id"]


@pytest.mark.asyncio
async def test_agent_can_do_two_way_door_work(client, db_session) -> None:
    await _seed_admin(db_session)
    full = {"Authorization": f"Bearer {await _full_token(client)}"}
    project_id = await _project(client, full)
    agent = {"Authorization": f"Bearer {await _agent_token(client, full)}"}

    # creating a task is a reversible action — open to agents
    created = await client.post(
        "/api/v1/tasks",
        json={"project_id": project_id, "name": "T", "duration": 2},
        headers=agent,
    )
    assert created.status_code == 201, created.text


@pytest.mark.asyncio
async def test_one_way_door_acceptance_gated_for_agents(client, db_session) -> None:
    await _seed_admin(db_session)
    full = {"Authorization": f"Bearer {await _full_token(client)}"}
    project_id = await _project(client, full)
    agent = {"Authorization": f"Bearer {await _agent_token(client, full)}"}

    async def _make_adr(reversibility: str) -> int:
        return (
            await client.post(
                "/api/v1/architecture/adrs",
                json={
                    "project_id": project_id,
                    "title": f"ADR {reversibility}",
                    "context": "c",
                    "decision": "d",
                    "consequences": "x",
                    "reversibility": reversibility,
                    "status": "under_discussion",
                },
                headers=full,
            )
        ).json()["id"]

    # one-way door: agent is blocked from accepting; a human can.
    one_way = await _make_adr("one_way")
    blocked = await client.patch(
        f"/api/v1/architecture/adrs/{one_way}", json={"status": "accepted"}, headers=agent
    )
    assert blocked.status_code == 403
    ok = await client.patch(
        f"/api/v1/architecture/adrs/{one_way}", json={"status": "accepted"}, headers=full
    )
    assert ok.status_code == 200

    # two-way door: agent may accept (bias to action on reversible decisions).
    two_way = await _make_adr("two_way")
    accepted = await client.patch(
        f"/api/v1/architecture/adrs/{two_way}", json={"status": "accepted"}, headers=agent
    )
    assert accepted.status_code == 200, accepted.text


@pytest.mark.asyncio
async def test_external_write_actions_gated_for_agents(client, db_session) -> None:
    await _seed_admin(db_session)
    full = {"Authorization": f"Bearer {await _full_token(client)}"}
    project_id = await _project(client, full)
    agent = {"Authorization": f"Bearer {await _agent_token(client, full)}"}

    plan = (
        await client.post(
            f"/api/v1/projects/{project_id}/draft-plans",
            json={"title": "Plan"},
            headers=full,
        )
    ).json()
    # push-to-jira is an external write → agent blocked before any Jira logic runs.
    pushed = await client.post(
        f"/api/v1/draft-plans/{plan['id']}/push-to-jira", json={}, headers=agent
    )
    assert pushed.status_code == 403
    # a human is NOT blocked by the agency gate (fails later for lack of a Jira connection).
    human_push = await client.post(
        f"/api/v1/draft-plans/{plan['id']}/push-to-jira", json={}, headers=full
    )
    assert human_push.status_code != 403
