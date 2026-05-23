from datetime import UTC, date, datetime, timedelta

import pytest

from app.core.security import hash_password
from app.models.base import ADRCommentKind, ADRStatus, DecisionRule, UserRole
from app.models.user import User
from app.services.decisions import (
    DecisionQueueInput,
    build_decision_queue,
    review_summary,
    valid_transition,
)

# --- Pure service: lifecycle -------------------------------------------------


def test_valid_transition_allows_lifecycle_steps():
    assert valid_transition(ADRStatus.proposed, ADRStatus.under_discussion)
    assert valid_transition(ADRStatus.under_discussion, ADRStatus.accepted)
    assert valid_transition(ADRStatus.accepted, ADRStatus.superseded)
    assert valid_transition(ADRStatus.proposed, ADRStatus.deferred)
    assert valid_transition(ADRStatus.proposed, ADRStatus.proposed)  # no-op


def test_valid_transition_rejects_nonsense():
    assert not valid_transition(ADRStatus.deprecated, ADRStatus.proposed)
    assert not valid_transition(ADRStatus.accepted, ADRStatus.proposed)
    assert not valid_transition(ADRStatus.superseded, ADRStatus.accepted)


# --- Pure service: reviews ---------------------------------------------------


def test_review_summary_consensus_requires_all_approvals():
    latest = {1: ADRCommentKind.approve, 2: ADRCommentKind.approve}
    s = review_summary([1, 2], latest, DecisionRule.consensus)
    assert s.approved == 2 and s.pending == 0 and s.can_accept

    partial = review_summary([1, 2, 3], latest, DecisionRule.consensus)
    assert partial.pending == 1 and not partial.can_accept


def test_review_summary_lazy_consensus_blocks_on_changes_requested():
    latest = {1: ADRCommentKind.approve, 2: ADRCommentKind.request_changes}
    s = review_summary([1, 2], latest, DecisionRule.lazy_consensus)
    assert s.changes_requested == 1 and not s.can_accept

    clean = review_summary([1, 2], {1: ADRCommentKind.approve}, DecisionRule.lazy_consensus)
    assert clean.pending == 1 and clean.can_accept  # silence is consent


def test_review_summary_owner_decides_is_always_acceptable():
    s = review_summary([1, 2], {1: ADRCommentKind.reject}, DecisionRule.owner_decides)
    assert s.rejected == 1 and s.can_accept


# --- Pure service: decision queue --------------------------------------------


_NOW = datetime(2026, 5, 23, 12, 0, tzinfo=UTC)


def _item(
    adr_id: int,
    status: ADRStatus,
    *,
    age: timedelta = timedelta(hours=1),
    decide_by: date | None = None,
) -> DecisionQueueInput:
    return DecisionQueueInput(
        id=adr_id,
        project_id=10,
        number=adr_id,
        title=f"ADR {adr_id}",
        status=status,
        created_at=_NOW - age,
        decide_by=decide_by,
        sla_hours=72,
    )


def test_decision_queue_buckets_and_overdue():
    soon = _NOW.date() + timedelta(days=5)
    far = _NOW.date() + timedelta(days=90)
    items = [
        _item(1, ADRStatus.proposed, age=timedelta(hours=2)),
        _item(2, ADRStatus.proposed, age=timedelta(hours=100)),
        _item(3, ADRStatus.under_discussion, age=timedelta(days=20)),
        _item(4, ADRStatus.deferred, decide_by=soon),
        _item(5, ADRStatus.deferred, decide_by=far),
        _item(6, ADRStatus.accepted),
    ]
    queue = build_decision_queue(items, _NOW)
    by_id = {q.id: q for q in queue}

    assert 5 not in by_id  # deferred far beyond the window is omitted
    assert 6 not in by_id  # accepted ADRs aren't in the queue
    assert by_id[1].bucket == "needs_triage" and not by_id[1].overdue
    assert by_id[2].bucket == "needs_triage" and by_id[2].overdue
    assert by_id[3].bucket == "stuck" and by_id[3].overdue
    assert by_id[4].bucket == "deferred_soon" and not by_id[4].overdue
    # Overdue items sort to the front.
    assert queue[0].overdue


# --- API: decision-centric ADR flow -----------------------------------------


async def _seed_admin(session) -> None:
    session.add(
        User(
            email="architect@example.com",
            hashed_password=hash_password("secret123"),
            role=UserRole.admin,
        )
    )
    await session.commit()


async def _token(client) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "architect@example.com", "password": "secret123"},
    )
    return resp.json()["access_token"]


@pytest.mark.asyncio
async def test_adr_lifecycle_reviews_and_queue(client, db_session):
    await _seed_admin(db_session)
    headers = {"Authorization": f"Bearer {await _token(client)}"}

    project_id = (
        await client.post(
            "/api/v1/projects",
            json={"key": "PLAT", "name": "Platform", "decision_rule": "consensus"},
            headers=headers,
        )
    ).json()["id"]
    async def add_engineer(name: str) -> int:
        resp = await client.post(
            "/api/v1/team/engineers", json={"name": name}, headers=headers
        )
        return resp.json()["id"]

    e1 = await add_engineer("Ada")
    e2 = await add_engineer("Lin")

    # Engineer-proposed ADR with the new decision fields + stakeholders.
    created = await client.post(
        "/api/v1/architecture/adrs",
        json={
            "project_id": project_id,
            "title": "Adopt event sourcing",
            "context": "We need an audit trail.",
            "decision": "Use an append-only event store.",
            "consequences": "More storage, replayability.",
            "alternatives": ["CRUD + audit table", "CDC from the DB"],
            "reversibility": "one_way",
            "proposed_by_id": e1,
            "decision_owner_id": e2,
            "stakeholder_ids": [e1, e2],
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    adr = created.json()
    adr_id = adr["id"]
    assert adr["reversibility"] == "one_way"
    assert sorted(adr["stakeholder_ids"]) == sorted([e1, e2])
    assert adr["alternatives"] == ["CRUD + audit table", "CDC from the DB"]

    # It shows up in the decision queue needing triage.
    queue = (
        await client.get(f"/api/v1/decisions/queue?project_id={project_id}", headers=headers)
    ).json()["items"]
    assert any(q["id"] == adr_id and q["bucket"] == "needs_triage" for q in queue)

    # Move it into discussion, then have both stakeholders approve.
    assert (
        await client.patch(
            f"/api/v1/architecture/adrs/{adr_id}",
            json={"status": "under_discussion"},
            headers=headers,
        )
    ).status_code == 200
    for e in (e1, e2):
        r = await client.post(
            f"/api/v1/architecture/adrs/{adr_id}/comments",
            json={"body": "LGTM", "kind": "approve", "engineer_id": e},
            headers=headers,
        )
        assert r.status_code == 201, r.text

    detail = (
        await client.get(f"/api/v1/architecture/adrs/{adr_id}", headers=headers)
    ).json()
    assert detail["review"]["approved"] == 2
    assert detail["review"]["can_accept"] is True  # consensus reached
    assert len(detail["comments"]) == 2


@pytest.mark.asyncio
async def test_deferred_requires_decide_by_and_bad_transition_409(client, db_session):
    await _seed_admin(db_session)
    headers = {"Authorization": f"Bearer {await _token(client)}"}
    project_id = (
        await client.post(
            "/api/v1/projects", json={"key": "PLAT", "name": "Platform"}, headers=headers
        )
    ).json()["id"]

    # Deferred without a decide_by is rejected.
    bad = await client.post(
        "/api/v1/architecture/adrs",
        json={"project_id": project_id, "title": "Punt on caching", "status": "deferred"},
        headers=headers,
    )
    assert bad.status_code == 400

    adr_id = (
        await client.post(
            "/api/v1/architecture/adrs",
            json={"project_id": project_id, "title": "Pick a queue"},
            headers=headers,
        )
    ).json()["id"]
    # proposed -> deprecated is not a legal transition.
    bad_move = await client.patch(
        f"/api/v1/architecture/adrs/{adr_id}",
        json={"status": "deprecated"},
        headers=headers,
    )
    assert bad_move.status_code == 409

    # Deferring with a date is fine and lands in the queue's deferred bucket.
    decide_by = (date.today() + timedelta(days=5)).isoformat()
    ok = await client.patch(
        f"/api/v1/architecture/adrs/{adr_id}",
        json={"status": "deferred", "decide_by": decide_by},
        headers=headers,
    )
    assert ok.status_code == 200, ok.text
    queue = (await client.get("/api/v1/decisions/queue", headers=headers)).json()["items"]
    assert any(q["id"] == adr_id and q["bucket"] == "deferred_soon" for q in queue)
