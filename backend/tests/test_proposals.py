"""Change proposals: agents stage canopy writes with provenance; a human reviews and
commits them from the UI. Apply/reject are human-only (agent tokens 403); apply is
all-or-nothing, resolves intra-proposal refs, and replans affected projects."""

import pytest

from app.core.security import hash_password
from app.models.base import UserRole
from app.models.user import User


async def _seed_admin(session) -> None:
    session.add(
        User(email="a@e.com", hashed_password=hash_password("secret123"), role=UserRole.admin)
    )
    await session.commit()


async def _login(client) -> dict:
    resp = await client.post(
        "/api/v1/auth/login", data={"username": "a@e.com", "password": "secret123"}
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _agent_headers(client, full_headers) -> dict:
    resp = await client.post("/api/v1/auth/agent-token", json={}, headers=full_headers)
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _project(client, headers, key: str = "PLAT") -> int:
    return (
        await client.post(
            "/api/v1/projects", json={"key": key, "name": key.title()}, headers=headers
        )
    ).json()["id"]


def _plan_items() -> list[dict]:
    """A realistic staged batch: a phase, a task under it (via ref), a dependency onto an
    existing-task-free chain, a milestone, and a blocker on the new task."""
    return [
        {
            "entity_type": "task",
            "action": "create",
            "ref": "phase",
            "payload": {"name": "Hardening phase", "type": "summary"},
            "reason": "Agreed in the launch-readiness meeting",
            "source_kind": "meeting",
            "source_label": "Launch readiness — 2026-07-10",
        },
        {
            "entity_type": "task",
            "action": "create",
            "ref": "pentest",
            "payload": {"name": "External pentest", "duration": 5, "parent_ref": "phase"},
        },
        {
            "entity_type": "task",
            "action": "create",
            "ref": "fixes",
            "payload": {"name": "Pentest fixes", "duration": 3, "parent_ref": "phase"},
        },
        {
            "entity_type": "dependency",
            "action": "create",
            "payload": {"predecessor_ref": "pentest", "successor_ref": "fixes"},
        },
        {
            "entity_type": "milestone",
            "action": "create",
            "payload": {"name": "Security sign-off", "target_date": "2026-09-01"},
        },
        {
            "entity_type": "blocker",
            "action": "create",
            "payload": {
                "task_ref": "pentest",
                "reason": "Vendor SOW not signed",
                "category": "external",
                "severity": "high",
            },
            "source_kind": "email",
            "source_label": "Procurement thread",
        },
    ]


@pytest.mark.asyncio
async def test_stage_review_apply_with_refs_and_replan(client, db_session) -> None:
    await _seed_admin(db_session)
    full = await _login(client)
    project_id = await _project(client, full)

    created = await client.post(
        "/api/v1/proposals",
        json={
            "scope_level": "project",
            "scope_id": project_id,
            "title": "Add security hardening to the plan",
            "summary": "From the launch-readiness meeting + procurement email.",
            "origin": "claude-session (architect persona)",
            "items": _plan_items(),
        },
        headers=full,
    )
    assert created.status_code == 201, created.text
    proposal = created.json()
    assert proposal["status"] == "open"
    assert proposal["item_count"] == 6
    assert proposal["scope_label"].startswith("PLAT")

    # The review payload carries provenance for the human.
    detail = (
        await client.get(f"/api/v1/proposals/{proposal['id']}", headers=full)
    ).json()
    assert detail["items"][0]["source_kind"] == "meeting"

    applied = await client.post(
        f"/api/v1/proposals/{proposal['id']}/apply", headers=full
    )
    assert applied.status_code == 200, applied.text
    result = applied.json()
    assert result["applied"] == 6
    assert result["replanned_projects"] == [project_id]
    assert result["proposal"]["status"] == "applied"

    # The staged plan is now live: 3 tasks (phase + 2 leaves), scheduled, with the
    # dependency honored (fixes starts after pentest ends) and the blocker open.
    tasks = (
        await client.get(f"/api/v1/tasks?project_id={project_id}", headers=full)
    ).json()
    by_name = {t["name"]: t for t in tasks}
    assert by_name["External pentest"]["parent_id"] == by_name["Hardening phase"]["id"]
    assert by_name["Pentest fixes"]["start"] > by_name["External pentest"]["start"]
    blockers = (
        await client.get(f"/api/v1/blockers?project_id={project_id}", headers=full)
    ).json()
    assert blockers and blockers[0]["reason"] == "Vendor SOW not signed"

    # Applying twice is refused (the proposal is no longer open).
    again = await client.post(f"/api/v1/proposals/{proposal['id']}/apply", headers=full)
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_agent_can_stage_and_withdraw_but_not_apply_or_reject(client, db_session) -> None:
    await _seed_admin(db_session)
    full = await _login(client)
    agent = await _agent_headers(client, full)
    project_id = await _project(client, full)

    staged = await client.post(
        "/api/v1/proposals",
        json={
            "scope_level": "project",
            "scope_id": project_id,
            "title": "Agent-staged tweak",
            "items": [
                {
                    "entity_type": "task",
                    "action": "create",
                    "payload": {"name": "Spike: rate limiter", "duration": 2},
                }
            ],
        },
        headers=agent,
    )
    assert staged.status_code == 201, staged.text
    pid = staged.json()["id"]

    # The commit lane is human-only: the agent that staged it cannot land it.
    assert (
        await client.post(f"/api/v1/proposals/{pid}/apply", headers=agent)
    ).status_code == 403
    assert (
        await client.post(f"/api/v1/proposals/{pid}/reject", json={}, headers=agent)
    ).status_code == 403
    item_id = (
        await client.get(f"/api/v1/proposals/{pid}", headers=agent)
    ).json()["items"][0]["id"]
    assert (
        await client.patch(
            f"/api/v1/proposals/{pid}/items/{item_id}",
            json={"excluded": True},
            headers=agent,
        )
    ).status_code == 403

    # …but withdrawing its own staged proposal is reversible and allowed.
    withdrawn = await client.post(f"/api/v1/proposals/{pid}/withdraw", headers=agent)
    assert withdrawn.status_code == 200
    assert withdrawn.json()["status"] == "withdrawn"


@pytest.mark.asyncio
async def test_stage_time_validation_rejects_bad_items(client, db_session) -> None:
    await _seed_admin(db_session)
    full = await _login(client)
    project_id = await _project(client, full)
    other_project = await _project(client, full, key="OTHER")

    async def stage(items: list[dict]) -> object:
        return await client.post(
            "/api/v1/proposals",
            json={
                "scope_level": "project",
                "scope_id": project_id,
                "title": "Bad",
                "items": items,
            },
            headers=full,
        )

    # Jira-owned status is not a stageable field at all.
    resp = await stage(
        [{"entity_type": "task", "action": "create", "payload": {"name": "T", "status": "Done"}}]
    )
    assert resp.status_code == 400
    assert "status" in str(resp.json()["detail"]["errors"][0]["error"])

    # An update must point at a live entity.
    resp = await stage(
        [
            {
                "entity_type": "task",
                "action": "update",
                "entity_id": 99999,
                "payload": {"duration": 9},
            }
        ]
    )
    assert resp.status_code == 400

    # Scope containment: a project-scoped proposal cannot touch another project.
    resp = await stage(
        [
            {
                "entity_type": "task",
                "action": "create",
                "payload": {"name": "Escape", "project_id": other_project},
            }
        ]
    )
    assert resp.status_code == 400
    assert "scope" in str(resp.json()["detail"]["errors"][0]["error"])

    # Unresolvable ref handles are caught at the door.
    resp = await stage(
        [
            {
                "entity_type": "dependency",
                "action": "create",
                "payload": {"predecessor_ref": "ghost", "successor_ref": "ghost2"},
            }
        ]
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_update_diff_exclusion_and_reject_flow(client, db_session) -> None:
    await _seed_admin(db_session)
    full = await _login(client)
    project_id = await _project(client, full)
    task = (
        await client.post(
            "/api/v1/tasks",
            json={"project_id": project_id, "name": "Build ingest", "duration": 4},
            headers=full,
        )
    ).json()

    staged = await client.post(
        "/api/v1/proposals",
        json={
            "scope_level": "project",
            "scope_id": project_id,
            "title": "Re-estimate + risk from standup",
            "items": [
                {
                    "entity_type": "task",
                    "action": "update",
                    "entity_id": task["id"],
                    "payload": {"duration": 8},
                    "reason": "Slack standup: parser is gnarlier than scoped",
                    "source_kind": "slack",
                    "source_url": "https://example.slack.com/archives/C1/p1",
                },
                {
                    "entity_type": "risk",
                    "action": "create",
                    "payload": {"title": "Vendor API instability", "probability": "high"},
                },
            ],
        },
        headers=full,
    )
    assert staged.status_code == 201, staged.text
    detail = staged.json()
    update_item = detail["items"][0]
    # The stage-time snapshot captured the current value for the reviewer's diff.
    assert update_item["before"]["duration"] == 4
    assert update_item["payload"]["duration"] == 8

    # Reviewer excludes the risk, applies the rest.
    risk_item = detail["items"][1]
    patched = await client.patch(
        f"/api/v1/proposals/{detail['id']}/items/{risk_item['id']}",
        json={"excluded": True},
        headers=full,
    )
    assert patched.status_code == 200 and patched.json()["excluded"] is True

    applied = await client.post(f"/api/v1/proposals/{detail['id']}/apply", headers=full)
    assert applied.status_code == 200, applied.text
    assert applied.json()["applied"] == 1
    assert applied.json()["skipped"] == 1

    assert (
        await client.get(f"/api/v1/tasks/{task['id']}", headers=full)
    ).json()["duration"] == 8
    risks = (await client.get("/api/v1/risks", headers=full)).json()
    assert risks == []  # the excluded risk never landed

    # Reject flow: a fresh proposal turned down with a note the agent can read back.
    second = await client.post(
        "/api/v1/proposals",
        json={
            "scope_level": "project",
            "scope_id": project_id,
            "title": "Another",
            "items": [
                {"entity_type": "task", "action": "create", "payload": {"name": "X"}}
            ],
        },
        headers=full,
    )
    rejected = await client.post(
        f"/api/v1/proposals/{second.json()['id']}/reject",
        json={"note": "Not this sprint — restage after the freeze."},
        headers=full,
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert "restage" in rejected.json()["review_note"]


@pytest.mark.asyncio
async def test_initiative_scoped_proposal_spans_projects(client, db_session) -> None:
    await _seed_admin(db_session)
    full = await _login(client)
    initiative = (
        await client.post(
            "/api/v1/initiatives", json={"key": "Q3", "name": "Q3 program"}, headers=full
        )
    ).json()
    p1 = await _project(client, full, key="API")
    p2 = await _project(client, full, key="WEB")
    for pid in (p1, p2):
        await client.patch(
            f"/api/v1/projects/{pid}", json={"initiative_id": initiative["id"]}, headers=full
        )

    staged = await client.post(
        "/api/v1/proposals",
        json={
            "scope_level": "initiative",
            "scope_id": initiative["id"],
            "title": "Cross-team hand-off from planning review",
            "items": [
                {
                    "entity_type": "task",
                    "action": "create",
                    "ref": "api-contract",
                    "payload": {"name": "Freeze API contract", "project_id": p1, "duration": 2},
                },
                {
                    "entity_type": "task",
                    "action": "create",
                    "ref": "web-consume",
                    "payload": {"name": "Consume new API", "project_id": p2, "duration": 3},
                },
                {
                    "entity_type": "dependency",
                    "action": "create",
                    "payload": {
                        "predecessor_ref": "api-contract",
                        "successor_ref": "web-consume",
                    },
                },
                {
                    "entity_type": "outcome",
                    "action": "create",
                    "payload": {"statement": "Checkout latency p95 < 300ms"},
                },
            ],
        },
        headers=full,
    )
    assert staged.status_code == 201, staged.text

    applied = await client.post(
        f"/api/v1/proposals/{staged.json()['id']}/apply", headers=full
    )
    assert applied.status_code == 200, applied.text
    assert sorted(applied.json()["replanned_projects"]) == sorted([p1, p2])

    outcomes = (
        await client.get(
            f"/api/v1/outcomes?scope_level=initiative&scope_id={initiative['id']}",
            headers=full,
        )
    ).json()
    assert outcomes and outcomes[0]["statement"].startswith("Checkout latency")


@pytest.mark.asyncio
async def test_audit_preserving_field_override(client, db_session) -> None:
    """T17: a reviewer can edit one proposed field inline instead of rejecting the whole
    proposal. The override is layered over the agent's payload at apply time; the payload
    itself is preserved as the audit record, and the override is stamped who/when."""
    await _seed_admin(db_session)
    full = await _login(client)
    project_id = await _project(client, full)

    staged = await client.post(
        "/api/v1/proposals",
        json={
            "scope_level": "project",
            "scope_id": project_id,
            "title": "Add a task",
            "items": [
                {
                    "entity_type": "task",
                    "action": "create",
                    "payload": {"name": "Load test", "duration": 5},
                }
            ],
        },
        headers=full,
    )
    pid = staged.json()["id"]
    item_id = staged.json()["items"][0]["id"]

    # Override the duration inline (agent proposed 5 → reviewer wants 12).
    patched = await client.patch(
        f"/api/v1/proposals/{pid}/items/{item_id}",
        json={"overrides": {"duration": 12}},
        headers=full,
    )
    assert patched.status_code == 200, patched.text

    detail = (await client.get(f"/api/v1/proposals/{pid}", headers=full)).json()
    item = detail["items"][0]
    assert item["payload"]["duration"] == 5  # agent's original preserved (audit)
    assert item["overrides"]["duration"] == 12  # reviewer's edit kept separate
    assert item["overridden_by"]  # stamped with a resolved name
    assert item["overridden_at"]

    # Apply: the OVERRIDDEN value wins over the agent's proposal.
    applied = await client.post(f"/api/v1/proposals/{pid}/apply", headers=full)
    assert applied.status_code == 200, applied.text
    tasks = (
        await client.get(f"/api/v1/tasks?project_id={project_id}", headers=full)
    ).json()
    load_test = next(t for t in tasks if t["name"] == "Load test")
    assert load_test["duration"] == 12


@pytest.mark.asyncio
async def test_override_rejects_bad_fields_and_can_be_cleared(client, db_session) -> None:
    await _seed_admin(db_session)
    full = await _login(client)
    project_id = await _project(client, full)
    staged = await client.post(
        "/api/v1/proposals",
        json={
            "scope_level": "project",
            "scope_id": project_id,
            "title": "Add a task",
            "items": [
                {
                    "entity_type": "task",
                    "action": "create",
                    "payload": {"name": "Load test", "duration": 5},
                }
            ],
        },
        headers=full,
    )
    pid = staged.json()["id"]
    item_id = staged.json()["items"][0]["id"]

    async def override(body: dict) -> object:
        return await client.patch(
            f"/api/v1/proposals/{pid}/items/{item_id}", json={"overrides": body}, headers=full
        )

    # A field the proposal doesn't set can't be introduced via override.
    assert (await override({"assignee_engineer_id": 1})).status_code == 400
    # A bad value for a real field is rejected at edit time (not deferred to apply).
    bad = await override({"duration": "lots"})
    assert bad.status_code == 400
    assert bad.json()["detail"]["code"] == "invalid_override"

    # Set then clear reverts to the agent's value + wipes the audit stamps.
    assert (await override({"duration": 9})).status_code == 200
    cleared = await client.patch(
        f"/api/v1/proposals/{pid}/items/{item_id}", json={"overrides": {}}, headers=full
    )
    assert cleared.status_code == 200
    item = (await client.get(f"/api/v1/proposals/{pid}", headers=full)).json()["items"][0]
    assert item["overrides"] is None
    assert item["overridden_by"] is None

    # Excluding still works alongside the override field (both optional in the patch).
    assert (
        await client.patch(
            f"/api/v1/proposals/{pid}/items/{item_id}", json={"excluded": True}, headers=full
        )
    ).status_code == 200
    item = (await client.get(f"/api/v1/proposals/{pid}", headers=full)).json()["items"][0]
    assert item["excluded"] is True
