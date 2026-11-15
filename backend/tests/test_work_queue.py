"""The agent work queue through the API (docs/AGENT_EXECUTION.md §6 to §9, §13): delegation and
intake, claims and their brief, fencing, plans and hand-offs, questions, parking, person moves,
the kill switch, bounded agency, token scope, idempotency, PR evidence and the alerts."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from sqlmodel import col, select

from app.connectors.github import GitHubConnector
from app.core.security import hash_password
from app.models.base import Provider, UserRole, utcnow
from app.models.gate import Gate
from app.models.integration import Connection
from app.models.project import Project, Task, TaskStatusHistory
from app.models.team import Engineer
from app.models.user import User
from app.models.work import WorkClaim, WorkEvent
from app.services import work_service

API = "/api/v1"


async def _login(client: Any, email: str) -> dict[str, str]:
    resp = await client.post(f"{API}/auth/login",
                             data={"username": email, "password": "secret123"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _mint(client: Any, headers: dict[str, str], **body: Any) -> dict[str, str]:
    resp = await client.post(f"{API}/auth/agent-token", json=body, headers=headers)
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


class World:
    """An architect (a planner) and an engineer, each with an engineer record, and a project."""

    arch: dict[str, str]
    eng: dict[str, str]
    agent: dict[str, str]
    project_id: int
    arch_engineer_id: int
    eng_engineer_id: int


async def _world(client: Any, db: Any) -> World:
    arch = User(email="arch@e.com", full_name="Ari Arch",
                hashed_password=hash_password("secret123"), role=UserRole.architect)
    eng = User(email="eng@e.com", full_name="Eli Eng",
               hashed_password=hash_password("secret123"), role=UserRole.engineer)
    db.add(arch)
    db.add(eng)
    await db.flush()
    arch_engineer = Engineer(name="Ari Arch", email="arch@e.com", user_id=arch.id,
                             github_login="ari-gh")
    eng_engineer = Engineer(name="Eli Eng", email="eng@e.com", user_id=eng.id,
                            github_login="eli-gh")
    project = Project(key="PAY", name="Payments")
    db.add_all([arch_engineer, eng_engineer, project])
    await db.commit()
    world = World()
    world.arch = await _login(client, "arch@e.com")
    world.eng = await _login(client, "eng@e.com")
    world.agent = await _mint(client, world.arch, label="ari-impl")
    assert project.id is not None and arch_engineer.id is not None
    assert eng_engineer.id is not None
    world.project_id = project.id
    world.arch_engineer_id = arch_engineer.id
    world.eng_engineer_id = eng_engineer.id
    return world


async def _task(client: Any, w: World, name: str, **body: Any) -> dict[str, Any]:
    payload = {"project_id": w.project_id, "name": name, "status": "To Do",
               "description": f"{name}: do the thing", **body}
    resp = await client.post(f"{API}/tasks", json=payload, headers=w.arch)
    assert resp.status_code == 201, resp.text
    return dict(resp.json())


async def _delegate(client: Any, w: World, task_id: int) -> dict[str, Any]:
    resp = await client.post(f"{API}/tasks/{task_id}/delegation",
                             json={"delegation": "agent"}, headers=w.arch)
    assert resp.status_code == 200, resp.text
    return dict(resp.json())


async def _intake(client: Any, w: World, state: str = "on") -> dict[str, Any]:
    resp = await client.post(f"{API}/projects/{w.project_id}/agent-intake",
                             json={"state": state}, headers=w.arch)
    assert resp.status_code == 200, resp.text
    return dict(resp.json())


async def _claim(client: Any, headers: dict[str, str], task_id: int | None = None,
                 **body: Any) -> Any:
    payload: dict[str, Any] = {"role": "implementer", **body}
    if task_id is not None:
        payload["task_id"] = task_id
    return await client.post(f"{API}/work/claims", json=payload, headers=headers)


async def _ready_world(client: Any, db: Any, name: str = "Add retries") -> tuple[World, int]:
    w = await _world(client, db)
    task = await _task(client, w, name)
    await _delegate(client, w, task["id"])
    await _intake(client, w)
    return w, int(task["id"])


# --------------------------------------------------------------------------- #
# Delegation, intake, the queue
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_delegation_and_intake_open_the_queue(client: Any, db_session: Any) -> None:
    w = await _world(client, db_session)
    task = await _task(client, w, "Add retries")
    tid = task["id"]

    # Delegating and switching intake are human-only.
    refused = await client.post(f"{API}/tasks/{tid}/delegation", json={"delegation": "agent"},
                                headers=w.agent)
    assert refused.status_code == 403
    delegated = await _delegate(client, w, tid)
    assert delegated["task"]["delegation"] == "agent"
    assert any("spec" in h for h in delegated["hints"])  # advice, not a block

    # Intake off: nothing is offered, whatever is delegated.
    queue = (await client.get(f"{API}/work/queue", headers=w.agent)).json()
    assert queue["ready"] == []
    assert (await client.post(f"{API}/projects/{w.project_id}/agent-intake",
                              json={"state": "on"}, headers=w.agent)).status_code == 403
    assert (await _intake(client, w))["agent_intake"] == "on"

    queue = (await client.get(f"{API}/work/queue", headers=w.agent)).json()
    assert queue["roles"] == ["implementer"]
    assert [(r["task_id"], r["stage"], r["pull"]) for r in queue["ready"]] == [
        (tid, "In Progress", True)
    ]
    # A task nobody delegated is never offered.
    other = await _task(client, w, "Not for agents")
    queue = (await client.get(f"{API}/work/queue", headers=w.agent)).json()
    assert other["id"] not in [r["task_id"] for r in queue["ready"]]

    # Paused: the queue keeps its state but offers nothing.
    await _intake(client, w, "paused")
    paused = (await client.get(f"{API}/work/queue", headers=w.agent)).json()
    assert paused["ready"] == [] and paused["reasons"].get("intake_paused") == 1


# --------------------------------------------------------------------------- #
# The happy path: claim → brief → plan → hand-off
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_claim_plan_and_hand_off(client: Any, db_session: Any) -> None:
    w, tid = await _ready_world(client, db_session)

    resp = await _claim(client, w.agent, agent={"label": "laptop", "runner": "interactive"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    claim = body["claim"]
    assert claim["task_id"] == tid and claim["state"] == "active" and claim["attempt"] == 1
    assert claim["runner"] == "interactive" and claim["agent_label"] == "laptop"
    brief = body["brief"]
    assert brief["task"]["key"] == "PAY-1"
    assert brief["stage"]["column"] == "In Progress" and brief["stage"]["trust"] == "policy"
    assert brief["task"]["description"]["trust"] == "content"
    assert brief["claim"]["id"] == claim["id"]
    assert brief["stage"]["exit_contract"] is not None
    assert brief["conventions"]["branch"].startswith("pay-1-")

    # The claim pulled the card into the stage and made the issuer accountable.
    task = await db_session.get(Task, tid)
    await db_session.refresh(task)
    assert task.status == "In Progress" and task.active_claim_id == claim["id"]
    assert task.assignee_engineer_id == w.arch_engineer_id

    # Nobody else can claim it.
    other_agent = await _mint(client, w.eng, label="eli-impl")
    taken = await _claim(client, other_agent, tid)
    assert taken.status_code == 409 and taken.json()["detail"]["code"] == "already_claimed"

    beat = await client.post(f"{API}/work/claims/{claim['id']}/heartbeat",
                             json={"note": "reading the brief"}, headers=w.agent)
    assert beat.status_code == 200 and beat.json()["directive"] == "continue"

    plan = await client.post(
        f"{API}/work/claims/{claim['id']}/artifacts",
        json={"kind": "plan", "body": "Wrap the client in a retry policy.",
              "data": {"approach": "Wrap the client in a retry policy.",
                       "steps": [{"content": "add backoff"}], "affected_paths": ["app/x.py"]}},
        headers=w.agent,
    )
    assert plan.status_code == 200, plan.text
    assert plan.json()["approval"] == {"required": False, "reasons": [], "gate_id": None}
    assert plan.json()["artifact"]["revision"] == 1

    # An agent token can't move a delegated card: the queue moves it.
    moved = await client.post(f"{API}/tasks/{tid}/move", json={"to_status": "Done"},
                              headers=w.agent)
    assert moved.status_code == 409 and moved.json()["detail"]["code"] == "use_work_claim"

    dry = (await client.get(f"{API}/tasks/{tid}/advance-check", headers=w.agent)).json()
    assert dry["target"] == "In Review" and not dry["allowed"]  # no hand-off yet
    # Counting the hand-off about to be sent, only the PR warning is left.
    dry = (await client.get(f"{API}/tasks/{tid}/advance-check", params={"with_handoff": "true"},
                            headers=w.agent)).json()
    assert dry["allowed"] and [x["check"] for x in dry["warnings"]] == ["pr_linked"]

    submitted = await client.post(
        f"{API}/work/claims/{claim['id']}/submit",
        json={"handoff": {"summary": "Retries with backoff", "verification": [
            {"command": "pytest -q", "result": "42 passed"}]}},
        headers=w.agent,
    )
    assert submitted.status_code == 200, submitted.text
    out = submitted.json()
    assert out["moved_to"] == "In Review" and out["claim"]["outcome"] == "advanced"
    assert out["warnings"] == ["pr_linked"]  # no PR linked: warned, not refused
    assert out["task"]["status"] == "In Review" and out["task"]["active_claim_id"] is None

    # A retried submit replays the result instead of moving again.
    again = await client.post(f"{API}/work/claims/{claim['id']}/submit",
                              json={"handoff": {"summary": "Retries with backoff"}},
                              headers=w.agent)
    assert again.status_code == 200 and again.json()["evaluation"] == {"replayed": True}

    # Status history is attributed to the agent and the claim.
    rows = (await db_session.execute(
        select(TaskStatusHistory).where(TaskStatusHistory.task_id == tid)
        .order_by(col(TaskStatusHistory.id))
    )).scalars().all()
    agent_rows = [r for r in rows if r.actor_kind == "agent"]
    assert [r.to_status for r in agent_rows] == ["In Progress", "In Review"]
    assert {r.work_claim_id for r in agent_rows} == {claim["id"]}

    timeline = (await client.get(f"{API}/tasks/{tid}/execution", headers=w.arch)).json()
    kinds = [e["kind"] for e in timeline["events"]]
    for expected in ("delegated", "claimed", "artifact_added", "checks_evaluated", "advanced",
                     "claim_ended"):
        assert expected in kinds, (expected, kinds)
    assert [a["kind"] for a in timeline["artifacts"]] == ["plan", "handoff"]
    assert timeline["stage"] == "In Review"

    # Nothing is left for the implementer: the task is past its stage.
    queue = (await client.get(f"{API}/work/queue", headers=w.agent)).json()
    assert queue["ready"] == []


@pytest.mark.asyncio
async def test_a_refused_hand_off_keeps_the_claim(client: Any, db_session: Any) -> None:
    w, _tid = await _ready_world(client, db_session)
    claim = (await _claim(client, w.agent)).json()["claim"]
    # A hand-off to a column that doesn't exist, or with both a hand-off and a review, is
    # refused and changes nothing: the claim stays the session's.
    unknown = await client.post(f"{API}/work/claims/{claim['id']}/submit",
                                json={"handoff": {"summary": "x"}, "to_status": "Nowhere"},
                                headers=w.agent)
    assert unknown.status_code == 422
    still = await db_session.get(WorkClaim, claim["id"])
    await db_session.refresh(still)
    assert still.state == "active"
    both = await client.post(f"{API}/work/claims/{claim['id']}/submit",
                             json={"handoff": {"summary": "x"},
                                   "review": {"verdict": "pass"}}, headers=w.agent)
    assert both.status_code == 422


# --------------------------------------------------------------------------- #
# Fencing, expiry and parking
# --------------------------------------------------------------------------- #


async def _lapse(db: Any, claim_id: int) -> None:
    claim = await db.get(WorkClaim, claim_id)
    await db.refresh(claim)
    claim.lease_expires_at = utcnow() - timedelta(minutes=1)
    await db.commit()


@pytest.mark.asyncio
async def test_a_lost_claim_is_fenced_and_the_task_returns(client: Any, db_session: Any) -> None:
    w, tid = await _ready_world(client, db_session)
    first = (await _claim(client, w.agent)).json()["claim"]
    await _lapse(db_session, first["id"])

    assert await work_service.reap_expired(db_session) == 1
    lost = await client.post(
        f"{API}/work/claims/{first['id']}/artifacts",
        json={"kind": "plan", "body": "late", "data": {"approach": "late"}}, headers=w.agent,
    )
    assert lost.status_code == 409 and lost.json()["detail"]["code"] == "claim_lost"
    beat = (await client.post(f"{API}/work/claims/{first['id']}/heartbeat", json={},
                              headers=w.agent)).json()
    assert beat["directive"] == "stop" and beat["reason"] == "expired"

    # The task is back in the queue, in its stage, for attempt 2.
    queue = (await client.get(f"{API}/work/queue", headers=w.agent)).json()
    assert [(r["task_id"], r["pull"]) for r in queue["ready"]] == [(tid, False)]
    second = (await _claim(client, w.agent)).json()["claim"]
    assert second["task_id"] == tid and second["attempt"] == 2
    # The new brief carries the earlier attempt.
    brief = (await client.get(f"{API}/tasks/{tid}/brief", headers=w.agent)).json()
    assert [a["outcome"] for a in brief["history"]["attempts"]] == ["expired"]


@pytest.mark.asyncio
async def test_a_lapsed_claim_is_expired_by_the_next_claim(client: Any, db_session: Any) -> None:
    w, tid = await _ready_world(client, db_session)
    first = (await _claim(client, w.agent)).json()["claim"]
    await _lapse(db_session, first["id"])
    # No reaper ran; a different session's claim expires the lapsed one itself.
    other = await _mint(client, w.arch, label="second")
    second = await _claim(client, other, tid)
    assert second.status_code == 200, second.text
    old = await db_session.get(WorkClaim, first["id"])
    await db_session.refresh(old)
    assert old.state == "expired" and old.outcome == "expired"


@pytest.mark.asyncio
async def test_unfinished_attempts_park_the_task(client: Any, db_session: Any) -> None:
    w, tid = await _ready_world(client, db_session)
    for attempt in range(1, 4):
        claim = (await _claim(client, w.agent)).json()["claim"]
        assert claim["attempt"] == attempt
        released = await client.post(
            f"{API}/work/claims/{claim['id']}/release",
            json={"reason": "out of time", "note": f"attempt {attempt}: tests still red"},
            headers=w.agent,
        )
        assert released.status_code == 200, released.text
        assert released.json()["state"] == "released"

    # Three unfinished attempts: canopy parks it with an escalation for a person.
    gates = (await client.get(f"{API}/gates", params={"task_id": tid}, headers=w.arch)).json()
    assert len(gates) == 1
    park = gates[0]
    assert park["kind"] == "escalation" and park["origin"] == "system"
    assert "attempt 3: tests still red" in park["prompt"]
    queue = (await client.get(f"{API}/work/queue", headers=w.agent)).json()
    assert queue["ready"] == [] and queue["reasons"].get("gate_open") == 1
    board = (await client.get(f"{API}/projects/{w.project_id}/board", headers=w.arch)).json()
    card = next(c for lane in board["lanes"] for c in lane["tasks"] if c["id"] == tid)
    assert card["delegation"] == "agent" and card["parked"] is True
    assert card["gate"]["parked"] is True

    # An agent can't decide; retry without guidance isn't a decision either.
    assert (await client.post(f"{API}/gates/{park['id']}/decide", json={"decision": "retry"},
                              headers=w.agent)).status_code == 403
    no_note = await client.post(f"{API}/gates/{park['id']}/decide",
                                json={"decision": "retry"}, headers=w.arch)
    assert no_note.status_code == 422 and no_note.json()["detail"]["code"] == "note_required"
    retried = await client.post(
        f"{API}/gates/{park['id']}/decide",
        json={"decision": "retry", "note": "Mock the clock; the flake is in the timer"},
        headers=w.arch,
    )
    assert retried.status_code == 200, retried.text
    assert retried.json()["status"] == "answered"

    # Retrying resets the attempt count; the guidance reaches the next brief.
    fresh = (await _claim(client, w.agent)).json()
    assert fresh["claim"]["task_id"] == tid
    decisions = fresh["brief"]["history"]["decisions"]
    assert any("Mock the clock" in (d["note"] or "") for d in decisions)


# --------------------------------------------------------------------------- #
# Asking a person
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_a_question_holds_the_task_until_a_person_answers(
    client: Any, db_session: Any
) -> None:
    w, tid = await _ready_world(client, db_session)
    claim = (await _claim(client, w.agent)).json()["claim"]
    asked = await client.post(
        f"{API}/work/claims/{claim['id']}/gates",
        json={"kind": "question", "title": "Which retry budget?",
              "prompt": "The spec doesn't say how many retries.",
              "options": [{"value": "3"}, {"value": "5"}], "allow_text": False},
        headers=w.agent,
    )
    assert asked.status_code == 200, asked.text
    gate = asked.json()
    assert gate["status"] == "open" and gate["may_decide"] is False  # agents never may
    ended = await db_session.get(WorkClaim, claim["id"])
    await db_session.refresh(ended)
    assert ended.outcome == "gated"

    queue = (await client.get(f"{API}/work/queue", headers=w.agent)).json()
    assert queue["ready"] == [] and queue["reasons"] == {"gate_open": 1}

    # The architect sees it in their inbox and their workspace; the engineer may not decide it.
    mine = (await client.get(f"{API}/gates", params={"mine": "true"}, headers=w.arch)).json()
    assert [g["id"] for g in mine] == [gate["id"]] and mine[0]["may_decide"] is True
    workspace = (await client.get(f"{API}/me/workspace", headers=w.arch)).json()
    assert [g["id"] for g in workspace["gates"]] == [gate["id"]]
    assert (await client.get(f"{API}/me/today", headers=w.arch)).json()["gates"][0]["id"] == (
        gate["id"]
    )
    denied = await client.post(f"{API}/gates/{gate['id']}/decide",
                               json={"decision": "answer", "option": "3"}, headers=w.eng)
    assert denied.status_code == 403 and denied.json()["detail"]["code"] == "not_an_approver"
    bad = await client.post(f"{API}/gates/{gate['id']}/decide",
                            json={"decision": "answer", "option": "7"}, headers=w.arch)
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "bad_option"

    detail = (await client.get(f"{API}/gates/{gate['id']}", headers=w.arch)).json()
    assert detail["task"]["id"] == tid and any(e["kind"] == "gate_opened"
                                               for e in detail["trail"])

    answered = await client.post(f"{API}/gates/{gate['id']}/decide",
                                 json={"decision": "answer", "option": "5",
                                       "note": "five, with jitter"}, headers=w.arch)
    assert answered.status_code == 200 and answered.json()["status"] == "answered"
    again = await client.post(f"{API}/gates/{gate['id']}/decide",
                              json={"decision": "answer", "option": "3"}, headers=w.arch)
    assert again.status_code == 409 and again.json()["detail"]["code"] == "gate_closed"
    waited = (await client.get(f"{API}/gates/{gate['id']}/wait", params={"timeout_s": 0},
                               headers=w.agent)).json()
    assert waited["status"] == "answered"

    # A fresh session resumes with the answer in its brief.
    resumed = (await _claim(client, w.agent)).json()
    assert resumed["claim"]["task_id"] == tid and resumed["claim"]["attempt"] == 2
    decision = resumed["brief"]["history"]["decisions"][0]
    assert decision["option"] == "5" and decision["note"] == "five, with jitter"
    assert decision["question"].startswith("The spec doesn't say")


@pytest.mark.asyncio
async def test_needs_human_release_and_withdrawing_a_question(
    client: Any, db_session: Any
) -> None:
    w, tid = await _ready_world(client, db_session)
    claim = (await _claim(client, w.agent)).json()["claim"]
    released = await client.post(
        f"{API}/work/claims/{claim['id']}/release",
        json={"reason": "conflicts with ADR-0007", "needs_human": True}, headers=w.agent,
    )
    assert released.status_code == 200 and released.json()["state"] == "failed"
    gates = (await client.get(f"{API}/gates", params={"task_id": tid}, headers=w.arch)).json()
    assert [(g["kind"], g["origin"]) for g in gates] == [("escalation", "agent")]
    # Whoever asked may withdraw it — their agent session included.
    withdrawn = await client.post(f"{API}/gates/{gates[0]['id']}/cancel", headers=w.agent)
    assert withdrawn.status_code == 200 and withdrawn.json()["status"] == "cancelled"
    # The engineer neither asked nor plans the project.
    claim = (await _claim(client, w.agent)).json()["claim"]
    asked = (await client.post(f"{API}/work/claims/{claim['id']}/gates",
                               json={"title": "Q", "prompt": "?"}, headers=w.agent)).json()
    assert (await client.post(f"{API}/gates/{asked['id']}/cancel",
                              headers=w.eng)).status_code == 403


# --------------------------------------------------------------------------- #
# People stay in charge
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_a_persons_move_ends_the_claim(client: Any, db_session: Any) -> None:
    w, tid = await _ready_world(client, db_session)
    claim = (await _claim(client, w.agent)).json()["claim"]
    moved = await client.post(f"{API}/tasks/{tid}/move", json={"to_status": "In Review"},
                              headers=w.arch)
    assert moved.status_code == 200, moved.text
    # The default review column checks for a hand-off: a person is warned, not stopped.
    assert any("handoff" in warning.lower() or "hand-off" in warning.lower()
               for warning in moved.json()["warnings"])
    beat = (await client.post(f"{API}/work/claims/{claim['id']}/heartbeat", json={},
                              headers=w.agent)).json()
    assert beat["directive"] == "stop" and beat["reason"] == "moved_by_person"


@pytest.mark.asyncio
async def test_kill_switch_and_take_over(client: Any, db_session: Any) -> None:
    w, tid = await _ready_world(client, db_session)
    claim = (await _claim(client, w.agent)).json()["claim"]
    assert (await _intake(client, w, "off"))["stopped"] == 1
    beat = (await client.post(f"{API}/work/claims/{claim['id']}/heartbeat", json={},
                              headers=w.agent)).json()
    assert beat["directive"] == "stop" and beat["reason"] == "intake_off"

    await _intake(client, w, "on")
    claim = (await _claim(client, w.agent)).json()["claim"]
    assert (await client.post(f"{API}/tasks/{tid}/take-over",
                              headers=w.agent)).status_code == 403
    taken = await client.post(f"{API}/tasks/{tid}/take-over", headers=w.arch)
    assert taken.status_code == 200 and taken.json()["delegation"] is None
    beat = (await client.post(f"{API}/work/claims/{claim['id']}/heartbeat", json={},
                              headers=w.agent)).json()
    assert beat["directive"] == "stop" and beat["reason"] == "taken_over"
    # A person moves an undelegated task freely, with no agent checks.
    moved = await client.post(f"{API}/tasks/{tid}/move", json={"to_status": "Done"},
                              headers=w.arch)
    assert moved.status_code == 200 and moved.json()["warnings"] == []


@pytest.mark.asyncio
async def test_bounded_agency_on_the_work_surface(client: Any, db_session: Any) -> None:
    w, tid = await _ready_world(client, db_session)
    # Plans outside a claim are a person's; a note is guidance anyone contributing may add.
    plan = await client.post(f"{API}/tasks/{tid}/artifacts",
                             json={"kind": "plan", "data": {"approach": "x"}}, headers=w.agent)
    assert plan.status_code == 403
    note = await client.post(f"{API}/tasks/{tid}/artifacts",
                             json={"kind": "note", "body": "Use the sandbox account"},
                             headers=w.arch)
    assert note.status_code == 200 and note.json()["author_kind"] == "human"
    brief = (await _claim(client, w.agent)).json()["brief"]
    assert brief["history"]["notes"][0]["body"] == "Use the sandbox account"
    # An engineer may not delegate someone else's task, nor switch intake.
    assert (await client.post(f"{API}/tasks/{tid}/delegation", json={"delegation": None},
                              headers=w.eng)).status_code == 403
    assert (await client.post(f"{API}/projects/{w.project_id}/agent-intake",
                              json={"state": "off"}, headers=w.eng)).status_code == 403


@pytest.mark.asyncio
async def test_token_scope_narrows_the_queue(client: Any, db_session: Any) -> None:
    w, _tid = await _ready_world(client, db_session)
    reviewer = await _mint(client, w.arch, label="reviewer", roles=["reviewer"])
    refused = await _claim(client, reviewer)
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "role_not_allowed"
    elsewhere = Project(key="OPS", name="Ops")
    db_session.add(elsewhere)
    await db_session.commit()
    scoped = await _mint(client, w.arch, label="ops only", project_ids=[elsewhere.id])
    queue = (await client.get(f"{API}/work/queue", headers=scoped)).json()
    assert queue["ready"] == []
    assert (await _claim(client, scoped)).json()["claim"] is None


@pytest.mark.asyncio
async def test_one_claim_at_a_time_and_idempotent_retries(client: Any, db_session: Any) -> None:
    w, first_id = await _ready_world(client, db_session)
    second = await _task(client, w, "Second task")
    await _delegate(client, w, second["id"])
    key = {"Idempotency-Key": "retry-me-0001", **w.agent}
    one = (await client.post(f"{API}/work/claims", json={"role": "implementer"},
                             headers=key)).json()["claim"]
    same = (await client.post(f"{API}/work/claims", json={"role": "implementer"},
                              headers=key)).json()["claim"]
    assert one["id"] == same["id"]
    # Without the key, a token at its limit gets the claim it already holds back...
    held = (await _claim(client, w.agent)).json()["claim"]
    assert held["id"] == one["id"]
    # ...and asking for a different task is refused until it hands off.
    other = second["id"] if one["task_id"] == first_id else first_id
    limited = await _claim(client, w.agent, other)
    assert limited.status_code == 409 and limited.json()["detail"]["code"] == "claim_limit"
    mine = (await client.get(f"{API}/work/claims", params={"mine": "true", "state": "active"},
                             headers=w.agent)).json()
    assert [c["id"] for c in mine] == [one["id"]]


# --------------------------------------------------------------------------- #
# Evidence from GitHub, alerts, the Agents view
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_a_pr_merged_ahead_moves_the_task_to_done(client: Any, db_session: Any) -> None:
    w, tid = await _ready_world(client, db_session)
    claim = (await _claim(client, w.agent)).json()["claim"]
    await client.post(f"{API}/work/claims/{claim['id']}/submit",
                      json={"handoff": {"summary": "done"}}, headers=w.agent)
    connection = Connection(provider=Provider.github, name="gh",
                            config={"owner": "acme", "repo": "payments"})
    db_session.add(connection)
    await db_session.commit()
    connector = GitHubConnector(connection, db_session)
    await connector.handle_webhook({
        "_github_event": "pull_request",
        "repository": {"full_name": "acme/payments"},
        "pull_request": {"number": 9, "title": "PAY-1 retries", "state": "closed",
                         "merged": True, "merged_by": {"login": "ari-gh"},
                         "head": {"ref": "pay-1-add-retries", "sha": "abc"}},
    })
    task = await db_session.get(Task, tid)
    await db_session.refresh(task)
    assert task.status == "Done"
    events = (await db_session.execute(
        select(WorkEvent.kind).where(WorkEvent.task_id == tid)
    )).scalars().all()
    assert "merged_ahead_of_stage" in events


@pytest.mark.asyncio
async def test_alerts_and_the_agents_view(client: Any, db_session: Any) -> None:
    w, _tid = await _ready_world(client, db_session)
    claim = (await _claim(client, w.agent)).json()["claim"]
    view = (await client.get(f"{API}/projects/{w.project_id}/agents", headers=w.arch)).json()
    assert view["agent_intake"] == "on" and view["can_manage"] is True
    assert [x["claim"]["id"] for x in view["working"]] == [claim["id"]]
    assert view["delegated"] == 1 and view["configured"] is False
    assert [s["worked_by"] for s in view["stages"] if s["worked_by"]] == ["implementer"]

    stale = await db_session.get(WorkClaim, claim["id"])
    await db_session.refresh(stale)
    stale.heartbeat_at = utcnow() - timedelta(minutes=20)
    await db_session.commit()
    asked = (await client.post(f"{API}/work/claims/{claim['id']}/gates",
                               json={"title": "Which?", "prompt": "?"}, headers=w.agent)).json()
    gate = await db_session.get(Gate, asked["id"])
    await db_session.refresh(gate)
    # Six hours ago: past its 4-hour reminder, short of its 24-hour escalation.
    assert gate.remind_at is not None and gate.escalate_at is not None
    six_hours = timedelta(hours=6)
    gate.created_at -= six_hours
    gate.remind_at -= six_hours
    gate.escalate_at -= six_hours
    await db_session.commit()
    kinds = {a["kind"]: a for a in
             (await client.get(f"{API}/projects/{w.project_id}/alerts",
                               headers=w.arch)).json()["alerts"]}
    assert kinds["gate_waiting"]["severity"] == "warning"
    view = (await client.get(f"{API}/projects/{w.project_id}/agents", headers=w.arch)).json()
    assert [g["id"] for g in view["waiting"]] == [asked["id"]] and view["working"] == []


@pytest.mark.asyncio
async def test_components_are_declared_by_planners_or_the_claim_holder(
    client: Any, db_session: Any
) -> None:
    from app.models.architecture import ArchitectureComponent

    w, tid = await _ready_world(client, db_session)
    component = ArchitectureComponent(project_id=w.project_id, name="Payments API")
    db_session.add(component)
    await db_session.commit()
    put = await client.put(f"{API}/tasks/{tid}/components",
                           json={"component_ids": [component.id]}, headers=w.arch)
    assert put.status_code == 200 and put.json()["component_ids"] == [component.id]
    bad = await client.put(f"{API}/tasks/{tid}/components", json={"component_ids": [999]},
                           headers=w.arch)
    assert bad.status_code == 422
    assert (await client.put(f"{API}/tasks/{tid}/components", json={"component_ids": []},
                             headers=w.eng)).status_code == 403
    brief = (await _claim(client, w.agent)).json()["brief"]
    assert [c["name"] for c in brief["components"]] == ["Payments API"]
