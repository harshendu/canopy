"""Agent work on a mirrored project (docs/AGENT_EXECUTION.md §17, Phase 3): the tracker owns the
status, so canopy **clears** moves instead of making them — a claim that pulls a ticket, a
hand-off, a person's gate approval — and the tracker's own move (seen on the next sync) consumes
the clearance. A move canopy didn't clear is recorded as `moved_without_clearance`: the running
claim ends and an alert fires. Stage policies attach to the tracker's statuses (the binding)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from sqlmodel import select

from app.core.security import hash_password
from app.models.base import Provider, UserRole, utcnow
from app.models.integration import Connection, TrackerBinding
from app.models.policy import StagePolicy
from app.models.project import Project, Task
from app.models.team import Engineer
from app.models.user import User
from app.models.work import WorkClaim, WorkEvent
from app.schemas.entities import IngestIssue
from app.services import ingest

API = "/api/v1"

STATUSES = [
    {"name": "To Do", "category": "todo", "position": 0},
    {"name": "In Progress", "category": "in_progress", "position": 1},
    {"name": "In Review", "category": "in_progress", "position": 2},
    {"name": "Done", "category": "done", "position": 3},
]

POLICIES = {
    "In Progress": {
        "worked_by": "implementer", "artifact": "handoff", "pulls_from": ["To Do"],
        "checkpoints": {"plan": {"required": False, "approval_when": ["never"]},
                        "handoff": {"approval_when": ["tag:needs-signoff"]}},
    },
    "In Review": {
        "worked_by": "reviewer", "artifact": "review",
        "enter": {"checks": [{"check": "artifact", "params": {"kind": "handoff"},
                              "enforcement": "block"}]},
    },
}


async def _login(client: Any, email: str) -> dict[str, str]:
    resp = await client.post(f"{API}/auth/login", data={"username": email, "password": "secret123"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _mint(client: Any, headers: dict[str, str], **body: Any) -> dict[str, str]:
    resp = await client.post(f"{API}/auth/agent-token", json=body, headers=headers)
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


class _Tracker:
    """Plays the tracker: every sync carries a later `updated`, so it is never skipped."""

    def __init__(self, db: Any, connection: Connection, project_id: int) -> None:
        self.db, self.connection, self.project_id, self.tick = db, connection, project_id, 0

    async def show(self, key: str, status: str) -> None:
        # A sync runs in its own session: read what the API committed, not a stale copy.
        self.db.expire_all()
        await self.db.refresh(self.connection)
        self.tick += 1
        number = key.split("-")[1]
        await ingest.ingest_issues(self.db, self.connection, [IngestIssue(
            external_id=number, external_key=key, summary=f"Ticket {key}", status=status,
            updated=f"2026-11-01T10:{self.tick:02d}:00.000+0000",
        )], project_id=self.project_id)
        await self.db.commit()


async def _world(client: Any, db: Any) -> tuple[dict[str, str], int, _Tracker, dict[str, int]]:
    arch = User(email="arch@e.com", full_name="Ari Arch", role=UserRole.architect,
                hashed_password=hash_password("secret123"))
    db.add(arch)
    await db.flush()
    db.add(Engineer(name="Ari Arch", user_id=arch.id))
    project = Project(key="SHOP", name="Shop", tracking_mode="mirrored")
    connection = Connection(provider=Provider.jira, name="jira", config={})
    db.add_all([project, connection])
    await db.flush()
    assert project.id is not None and connection.id is not None
    db.add(TrackerBinding(connection_id=connection.id, provider=Provider.jira,
                          target_type="project", target_id=project.id,
                          scope={"project_key": "SHOP"}, status_map=STATUSES))
    await db.commit()
    tracker = _Tracker(db, connection, project.id)
    for key in ("SHOP-1", "SHOP-2"):
        await tracker.show(key, "To Do")
    ids = {t.key: t.id for t in (await db.execute(
        select(Task).where(Task.project_id == project.id))).scalars().all() if t.key and t.id}
    return await _login(client, "arch@e.com"), project.id, tracker, ids


async def _task(db: Any, task_id: int) -> Task:
    task = await db.get(Task, task_id)
    assert task is not None
    await db.refresh(task)  # the API wrote it in another session
    return task


@pytest.mark.asyncio
async def test_mirrored_agent_work_clears_instead_of_moving(client: Any, db_session: Any) -> None:
    arch, pid, tracker, ids = await _world(client, db_session)
    one, two = ids["SHOP-1"], ids["SHOP-2"]

    # Policies attach to the tracker's statuses — stored on the binding — and the template's
    # columns can't be applied to a tracker.
    url = f"{API}/projects/{pid}/workflow/policy"
    before = (await client.get(url, headers=arch)).json()
    assert before["scope"] == "tracker" and before["can_edit"] and not before["configured"]
    saved = await client.put(url, json={"policies": POLICIES}, headers=arch)
    assert saved.status_code == 200, saved.text
    assert saved.json()["configured"] and saved.json()["roles"] == ["implementer", "reviewer"]
    owners = {(p.owner_type, p.status_name) for p in (
        await db_session.execute(select(StagePolicy))).scalars().all()}
    assert owners == {("binding", "In Progress"), ("binding", "In Review")}
    template = await client.post(f"{API}/projects/{pid}/workflow/apply-template",
                                 json={"dry_run": False}, headers=arch)
    assert template.status_code == 409
    assert template.json()["detail"]["code"] == "workflow_externally_owned"

    # Mirrored tickets can be delegated now.
    for task_id in (one, two):
        delegated = await client.post(f"{API}/tasks/{task_id}/delegation",
                                      json={"delegation": "agent"}, headers=arch)
        assert delegated.status_code == 200, delegated.text
    await client.post(f"{API}/projects/{pid}/agent-intake", json={"state": "on"}, headers=arch)

    # Claiming pulls nothing in the tracker: canopy clears the move for the session to make.
    impl = await _mint(client, arch, label="impl", roles=["implementer"])
    claim = await client.post(f"{API}/work/claims", json={"role": "implementer",
                                                          "task_id": one}, headers=impl)
    assert claim.status_code == 200, claim.text
    body = claim.json()
    assert body["claim"]["stage"] == "In Progress"
    assert body["tracker_transition"]["key"] == "SHOP-1"
    assert body["tracker_transition"]["to_status"] == "In Progress"
    assert body["brief"]["stage"]["tracker"]["provider"] == "jira"
    task = await _task(db_session, one)
    assert task.status == "To Do" and task.clearance_status == "In Progress"
    claim_id = body["claim"]["id"]

    # The session moves the ticket; the sync shows it — the cleared move, so the claim goes on.
    await tracker.show("SHOP-1", "In Progress")
    task = await _task(db_session, one)
    assert task.status == "In Progress" and task.clearance_status is None
    live = await db_session.get(WorkClaim, claim_id)
    assert live is not None and live.state == "active"

    # Handing off clears the next move instead of making it; until the tracker shows it,
    # nothing is offered to anyone.
    handoff = await client.post(f"{API}/work/claims/{claim_id}/submit",
                                json={"handoff": {"summary": "done"}}, headers=impl)
    assert handoff.status_code == 200, handoff.text
    result = handoff.json()
    assert result["moved_to"] is None and result["cleared_to"] == "In Review"
    assert result["tracker_transition"]["to_status"] == "In Review"
    assert (await _task(db_session, one)).status == "In Progress"
    rev = await _mint(client, arch, label="rev", roles=["reviewer"])
    queue = (await client.get(f"{API}/work/queue", params={"role": "implementer",
                                                           "project_id": pid},
                              headers=impl)).json()
    assert [i["task_id"] for i in queue["ready"]] == [two]  # SHOP-1 waits for its tracker
    assert queue["reasons"].get("awaiting_tracker_move") == 1
    reviewing = (await client.get(f"{API}/work/queue", params={"role": "reviewer",
                                                               "project_id": pid},
                                  headers=rev)).json()
    assert reviewing["ready"] == []
    execution = (await client.get(f"{API}/tasks/{one}/execution", headers=arch)).json()
    assert execution["tracker_transition"]["to_status"] == "In Review"
    board = (await client.get(f"{API}/projects/{pid}/board", headers=arch)).json()
    cards = {c["key"]: c for lane in board["lanes"] for c in lane["tasks"]}
    assert cards["SHOP-1"]["awaiting_move"] == "In Review"

    # The tracker shows the move: the reviewer can claim it, with no move to make.
    await tracker.show("SHOP-1", "In Review")
    review = await client.post(f"{API}/work/claims", json={"role": "reviewer", "task_id": one},
                               headers=rev)
    assert review.status_code == 200, review.text
    assert review.json()["tracker_transition"] is None
    review_claim = review.json()["claim"]["id"]

    # A move canopy didn't clear: recorded, the claim ends, an alert fires.
    await tracker.show("SHOP-1", "Done")
    ended = await db_session.get(WorkClaim, review_claim)
    await db_session.refresh(ended)
    assert ended is not None and ended.state == "superseded"
    kinds = [e.kind for e in (await db_session.execute(
        select(WorkEvent).where(WorkEvent.task_id == one).order_by(WorkEvent.id)
    )).scalars().all()]
    assert kinds.count("cleared") == 2 and kinds.count("tracker_moved") == 2
    assert kinds[-1] in ("moved_without_clearance", "claim_ended")
    assert "moved_without_clearance" in kinds
    alerts = (await client.get(f"{API}/projects/{pid}/alerts", headers=arch)).json()["alerts"]
    assert any(a["kind"] == "moved_without_clearance" and a["entity_id"] == one for a in alerts)

    # A person's approval clears too: SHOP-2's hand-off needs a sign-off (its tag), and
    # approving it clears the move rather than making it.
    task = await _task(db_session, two)
    task.tags = ["needs-signoff"]
    await db_session.commit()
    second = (await client.post(f"{API}/work/claims", json={"role": "implementer",
                                                            "task_id": two},
                                headers=impl)).json()
    await tracker.show("SHOP-2", "In Progress")
    held = await client.post(f"{API}/work/claims/{second['claim']['id']}/submit",
                             json={"handoff": {"summary": "ready"}}, headers=impl)
    assert held.status_code == 200, held.text
    gate = held.json()["gate"]
    assert gate is not None and gate["kind"] == "handoff_approval"
    assert held.json()["cleared_to"] is None  # held for a person, nothing cleared yet
    admin = User(email="lead@e.com", role=UserRole.admin,
                 hashed_password=hash_password("secret123"))
    db_session.add(admin)
    await db_session.commit()
    lead = await _login(client, "lead@e.com")
    decided = await client.post(f"{API}/gates/{gate['id']}/decide",
                                json={"decision": "approve", "subject_revision": 1}, headers=lead)
    assert decided.status_code == 200, decided.text
    assert decided.json()["tracker_transition"]["to_status"] == "In Review"
    task = await _task(db_session, two)
    assert task.status == "In Progress" and task.clearance_status == "In Review"

    # A clearance the tracker still doesn't show after a day raises an alert.
    task.clearance_at = utcnow() - timedelta(hours=30)
    await db_session.commit()
    alerts = (await client.get(f"{API}/projects/{pid}/alerts", headers=arch)).json()["alerts"]
    assert any(a["kind"] == "clearance_waiting" and a["entity_id"] == two for a in alerts)

    # Taking the task back drops what was cleared.
    await client.post(f"{API}/tasks/{two}/delegation", json={"delegation": None}, headers=arch)
    assert (await _task(db_session, two)).clearance_status is None
