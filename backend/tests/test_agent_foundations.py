"""Phase 0 of docs/AGENT_EXECUTION.md: pull-request review/check signals (§11.3), status-history
attribution (§11.2) and agent-token scope (§18.2)."""

from __future__ import annotations

from typing import Any

import pytest
from sqlmodel import select

from app.connectors.github import GitHubConnector
from app.core.security import hash_password
from app.models.agent_token import AgentTokenRecord
from app.models.base import Provider, UserRole
from app.models.integration import Connection, PullRequest
from app.models.project import Project, Task, TaskStatusHistory
from app.models.user import User
from app.services import pr_signals

# --------------------------------------------------------------------------- #
# Pure signal roll-ups
# --------------------------------------------------------------------------- #


def test_checks_roll_up_failing_then_pending_then_passing() -> None:
    norm = pr_signals.normalize_check
    assert norm("completed", "success") == "success"
    assert norm("completed", "timed_out") == "failure"
    assert norm("in_progress", None) == "pending"
    assert norm("completed", "skipped") == "neutral"
    assert norm("error", None) == "failure"  # a commit status carries its outcome in `state`
    roll = pr_signals.roll_up_checks
    assert roll({}) is None
    assert roll({"a": "neutral"}) is None  # neutral is neither a pass nor a failure
    assert roll({"a": "success", "b": "neutral"}) == "passing"
    assert roll({"a": "success", "b": "pending"}) == "pending"
    assert roll({"a": "pending", "b": "failure"}) == "failing"


def test_reviews_keep_the_latest_verdict_and_only_count_approvals_at_head() -> None:
    reviews: list[dict[str, Any]] = []
    reviews = pr_signals.record_review(
        reviews, {"user": {"login": "ana"}, "state": "APPROVED", "commit_id": "old"}
    )
    reviews = pr_signals.record_review(
        reviews, {"user": {"login": "bo"}, "state": "approved", "commit_id": "new"}
    )
    assert pr_signals.approvals_at_head(reviews, "new") == ["bo"]  # ana approved an old commit
    assert pr_signals.review_decision(reviews, "new") == "approved"
    # A comment keeps an earlier verdict; a change request overrides approvals.
    reviews = pr_signals.record_review(reviews, {"login": "bo", "state": "commented"})
    assert pr_signals.approvals_at_head(reviews, "new") == ["bo"]
    reviews = pr_signals.record_review(
        reviews,
        {"login": "cy", "state": "changes_requested", "body": "add a test",
         "submitted_at": "2026-11-01T10:00:00Z"},
    )
    assert pr_signals.review_decision(reviews, "new") == "changes_requested"
    assert (pr_signals.latest_change_request(reviews) or {}).get("body") == "add a test"
    # Dismissing removes that reviewer's verdict.
    reviews = pr_signals.record_review(reviews, {"login": "cy", "state": "dismissed"})
    assert pr_signals.review_decision(reviews, "new") == "approved"
    assert pr_signals.review_decision([], "new") is None


# --------------------------------------------------------------------------- #
# GitHub webhooks
# --------------------------------------------------------------------------- #


async def _github(session: Any) -> GitHubConnector:
    connection = Connection(
        provider=Provider.github, name="gh", config={"owner": "acme", "repo": "platform"}
    )
    session.add(connection)
    await session.flush()
    return GitHubConnector(connection, session)


def _pr_event(number: int, head: str, **pr: Any) -> dict[str, Any]:
    return {
        "_github_event": "pull_request",
        "repository": {"full_name": "acme/platform"},
        "pull_request": {
            "number": number,
            "title": f"PLAT-{number} work",
            "state": "open",
            "html_url": f"https://github.com/acme/platform/pull/{number}",
            "user": {"login": "dev"},
            "head": {"ref": f"plat-{number}-work", "sha": head},
            "draft": False,
            "merged": False,
            "additions": 30,
            "deletions": 4,
            "changed_files": 3,
            **pr,
        },
    }


async def _pr(session: Any, number: int = 7) -> PullRequest:
    return (
        await session.execute(select(PullRequest).where(PullRequest.number == number))
    ).scalar_one()


@pytest.mark.asyncio
async def test_pull_request_event_records_head_size_and_merge(db_session: Any) -> None:
    gh = await _github(db_session)
    await gh.handle_webhook(_pr_event(7, "sha1"))
    pr = await _pr(db_session)
    assert (pr.head_sha, pr.head_branch, pr.additions, pr.changed_files) == (
        "sha1", "plat-7-work", 30, 3,
    )
    assert pr.merged is False
    await gh.handle_webhook(
        _pr_event(7, "sha1", state="closed", merged=True,
                  merged_at="2026-11-02T09:00:00Z", merged_by={"login": "lead"})
    )
    await db_session.refresh(pr)
    assert pr.merged is True and pr.merged_by == "lead" and pr.merged_at is not None


@pytest.mark.asyncio
async def test_reviews_and_checks_follow_the_current_head(db_session: Any) -> None:
    gh = await _github(db_session)
    await gh.handle_webhook(_pr_event(7, "sha1"))
    review = _pr_event(7, "sha1")
    review["_github_event"] = "pull_request_review"
    review["review"] = {"user": {"login": "ana"}, "state": "approved", "commit_id": "sha1"}
    await gh.handle_webhook(review)
    suite = {
        "_github_event": "check_suite",
        "repository": {"full_name": "acme/platform"},
        "check_suite": {
            "head_sha": "sha1", "status": "completed", "conclusion": "success",
            "app": {"slug": "github-actions"}, "pull_requests": [{"number": 7}],
        },
    }
    await gh.handle_webhook(suite)
    status = {
        "_github_event": "status",
        "repository": {"full_name": "acme/platform"},
        "sha": "sha1", "state": "pending", "context": "ci/legacy",
    }
    await gh.handle_webhook(status)
    pr = await _pr(db_session)
    assert pr.approved_by == ["ana"] and pr.review_decision == "approved"
    assert pr.checks_state == "pending"
    status["state"] = "success"
    await gh.handle_webhook(status)
    await db_session.refresh(pr)
    assert pr.checks_state == "passing"

    # A check on an older commit changes nothing; a push resets checks and makes the approval stale.
    stale = {**suite, "check_suite": {**suite["check_suite"], "head_sha": "old",
                                      "conclusion": "failure"}}
    await gh.handle_webhook(stale)
    await db_session.refresh(pr)
    assert pr.checks_state == "passing"
    await gh.handle_webhook(_pr_event(7, "sha2"))
    await db_session.refresh(pr)
    assert pr.head_sha == "sha2"
    assert pr.checks_state is None and pr.checks == {}
    assert pr.approved_by == [] and pr.review_decision == "review_required"


@pytest.mark.asyncio
async def test_receiver_carries_the_event_name(
    client: Any, db_session: Any, monkeypatch: Any
) -> None:
    import hashlib
    import hmac
    import json

    from app.core.config import settings
    from app.webhooks import github as receiver
    from tests.conftest import TestSession

    db_session.add(Connection(provider=Provider.github, name="gh",
                              config={"owner": "acme", "repo": "platform"}))
    await db_session.commit()
    seen: list[dict[str, Any]] = []

    async def fake_enqueue(_name: str, _connection_id: int, payload: dict[str, Any]) -> None:
        seen.append(payload)

    monkeypatch.setattr(settings, "GITHUB_WEBHOOK_SECRET", "s3cret")
    monkeypatch.setattr(receiver, "enqueue", fake_enqueue)
    monkeypatch.setattr(receiver, "async_session_factory", TestSession)
    body = json.dumps({"repository": {"full_name": "acme/platform"},
                       "check_suite": {"head_sha": "x"}}).encode()
    signature = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    resp = await client.post(
        "/webhooks/github",
        content=body,
        headers={"X-Hub-Signature-256": signature, "X-GitHub-Event": "check_suite",
                 "Content-Type": "application/json"},
    )
    assert resp.status_code == 202, resp.text
    assert [p["_github_event"] for p in seen] == ["check_suite"]


@pytest.mark.asyncio
async def test_ingest_accepts_signals(client: Any, db_session: Any) -> None:
    db_session.add(User(email="a@e.com", hashed_password=hash_password("secret123"),
                        role=UserRole.admin))
    connection = Connection(provider=Provider.github, name="gh",
                            config={"owner": "acme", "repo": "platform"})
    db_session.add(connection)
    await db_session.commit()
    token = (await client.post("/api/v1/auth/login",
                               data={"username": "a@e.com", "password": "secret123"})).json()
    headers = {"Authorization": f"Bearer {token['access_token']}"}
    resp = await client.post(
        f"/api/v1/connectors/connections/{connection.id}/ingest/pull-requests",
        json={"pull_requests": [{
            "number": 9, "title": "PLAT-9", "state": "open", "head_sha": "abc",
            "checks_state": "passing", "review_decision": "approved", "approved_by": ["ana"],
            "merged": False,
        }]},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    pr = await _pr(db_session, 9)
    assert (pr.head_sha, pr.checks_state, pr.review_decision, pr.approved_by) == (
        "abc", "passing", "approved", ["ana"],
    )


# --------------------------------------------------------------------------- #
# Agent-token scope + status attribution
# --------------------------------------------------------------------------- #


async def _login(client: Any, email: str) -> dict[str, str]:
    resp = await client.post("/api/v1/auth/login",
                             data={"username": email, "password": "secret123"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.mark.asyncio
async def test_agent_tokens_carry_role_and_project_scope(client: Any, db_session: Any) -> None:
    db_session.add(User(email="arch@e.com", hashed_password=hash_password("secret123"),
                        role=UserRole.architect))
    project = Project(key="PLAT", name="Platform")
    db_session.add(project)
    await db_session.commit()
    headers = await _login(client, "arch@e.com")

    bad_role = await client.post("/api/v1/auth/agent-token",
                                 json={"roles": ["Not A Role!"]}, headers=headers)
    assert bad_role.status_code == 400
    unknown = await client.post("/api/v1/auth/agent-token",
                                json={"project_ids": [9999]}, headers=headers)
    assert unknown.status_code == 400

    minted = await client.post(
        "/api/v1/auth/agent-token",
        json={"label": "reviewer bot", "roles": ["reviewer", "Reviewer"],
              "project_ids": [project.id], "max_active_claims": 50},
        headers=headers,
    )
    assert minted.status_code == 200, minted.text
    body = minted.json()
    assert body["roles"] == ["reviewer"] and body["project_ids"] == [project.id]
    assert body["max_active_claims"] == 10  # clamped

    agent = {"Authorization": f"Bearer {body['access_token']}"}
    session_info = (await client.get("/api/v1/auth/session", headers=agent)).json()
    assert session_info["scope"] == "agent"
    assert session_info["agent_token"]["roles"] == ["reviewer"]
    human_info = (await client.get("/api/v1/auth/session", headers=headers)).json()
    assert human_info["agent_token"] is None

    record = (await db_session.execute(select(AgentTokenRecord))).scalar_one()
    await db_session.refresh(record)
    assert record.last_used_at is not None  # touched by the request above
    listed = (await client.get("/api/v1/auth/agent-tokens", headers=headers)).json()
    assert listed[0]["last_used_at"] is not None and listed[0]["roles"] == ["reviewer"]


@pytest.mark.asyncio
async def test_status_history_says_whether_a_person_or_an_agent_moved_it(
    client: Any, db_session: Any
) -> None:
    db_session.add(User(email="arch@e.com", hashed_password=hash_password("secret123"),
                        role=UserRole.architect))
    project = Project(key="PLAT", name="Platform")
    db_session.add(project)
    await db_session.commit()
    headers = await _login(client, "arch@e.com")
    created = await client.post("/api/v1/tasks", json={"project_id": project.id, "name": "Work"},
                                headers=headers)
    task_id = created.json()["id"]
    await client.post(f"/api/v1/tasks/{task_id}/move", json={"to_status": "In Progress"},
                      headers=headers)
    token = (await client.post("/api/v1/auth/agent-token", json={}, headers=headers)).json()
    agent = {"Authorization": f"Bearer {token['access_token']}"}
    moved = await client.post(f"/api/v1/tasks/{task_id}/move", json={"to_status": "In Review"},
                              headers=agent)
    assert moved.status_code == 200, moved.text

    rows = (
        await db_session.execute(
            select(TaskStatusHistory)
            .where(TaskStatusHistory.task_id == task_id)
            .order_by(TaskStatusHistory.id)  # type: ignore[arg-type]
        )
    ).scalars().all()
    assert [(r.to_status, r.actor_kind) for r in rows] == [
        ("Backlog", None),  # the creation (initialise_native_task) — not attributed
        ("In Progress", "human"),
        ("In Review", "agent"),
    ]
    history = (await client.get(f"/api/v1/tasks/{task_id}/history", headers=headers)).json()
    assert history[-1]["actor_kind"] == "agent"
    task = await db_session.get(Task, task_id)
    assert task is not None and task.status == "In Review"
