"""What a runner needs from the work API (docs/AGENT_EXECUTION.md §15): release with the
session's usage, and report usage after the session ended the claim itself — by the claim's own
token, within a day."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from app.core.security import hash_password
from app.models.base import UserRole, utcnow
from app.models.project import Project
from app.models.team import Engineer
from app.models.user import User
from app.models.work import WorkClaim

API = "/api/v1"


async def _setup(client: Any, db: Any) -> tuple[dict[str, str], int]:
    arch = User(email="arch@e.com", full_name="Ari Arch", role=UserRole.architect,
                hashed_password=hash_password("secret123"))
    db.add(arch)
    await db.flush()
    db.add(Engineer(name="Ari Arch", user_id=arch.id))
    project = Project(key="PAY", name="Payments")
    db.add(project)
    await db.commit()
    login = await client.post(f"{API}/auth/login",
                              data={"username": "arch@e.com", "password": "secret123"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    task = (await client.post(f"{API}/tasks", headers=headers, json={
        "project_id": project.id, "name": "Webhooks", "status": "To Do"})).json()
    await client.post(f"{API}/tasks/{task['id']}/delegation", json={"delegation": "agent"},
                      headers=headers)
    await client.post(f"{API}/projects/{project.id}/agent-intake", json={"state": "on"},
                      headers=headers)
    return headers, int(task["id"])


async def _token(client: Any, headers: dict[str, str], label: str) -> dict[str, str]:
    minted = await client.post(f"{API}/auth/agent-token", json={"label": label}, headers=headers)
    return {"Authorization": f"Bearer {minted.json()['access_token']}"}


@pytest.mark.asyncio
async def test_a_runner_reports_what_its_sessions_cost(client: Any, db_session: Any) -> None:
    person, task_id = await _setup(client, db_session)
    runner = await _token(client, person, "runner-1")
    other = await _token(client, person, "runner-2")

    first = (await client.post(f"{API}/work/claims", json={"role": "implementer",
                                                          "task_id": task_id,
                                                          "agent": {"runner": "sdk"}},
                               headers=runner)).json()["claim"]
    released = await client.post(f"{API}/work/claims/{first['id']}/release", headers=runner,
                                 json={"reason": "session ended without a hand-off",
                                       "usage": {"cost_usd": 0.42, "turns": 12}})
    assert released.status_code == 200, released.text
    assert released.json()["usage"] == {"cost_usd": 0.42, "turns": 12}

    # The next session hands off itself; its runner reports the cost afterwards.
    second = (await client.post(f"{API}/work/claims", json={"role": "implementer",
                                                           "task_id": task_id},
                                headers=runner)).json()["claim"]
    await client.post(f"{API}/work/claims/{second['id']}/release", headers=runner,
                      json={"reason": "done for now"})
    report = await client.post(f"{API}/work/claims/{second['id']}/usage", headers=runner,
                               json={"cost_usd": 1.25, "turns": 30, "model": "x",
                                     "outcome": "success"})
    assert report.status_code == 200, report.text
    assert report.json()["usage"]["cost_usd"] == 1.25
    assert report.json()["usage"]["reported_by"] == "runner"
    stranger = await client.post(f"{API}/work/claims/{second['id']}/usage", headers=other,
                                 json={"cost_usd": 9})
    assert stranger.status_code == 403
    assert stranger.json()["detail"]["code"] == "not_claim_holder"

    claim = await db_session.get(WorkClaim, second["id"])
    claim.finished_at = utcnow() - timedelta(hours=25)
    await db_session.commit()
    late = await client.post(f"{API}/work/claims/{second['id']}/usage", headers=runner,
                             json={"cost_usd": 2})
    assert late.status_code == 409 and late.json()["detail"]["code"] == "usage_too_late"
