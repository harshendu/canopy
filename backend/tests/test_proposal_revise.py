"""Co-review: the author revises an open proposal in place while a human reviews it.

Revise is still *staging* — reversible, open to agent tokens — so the conversational loop
("push that task a week, drop the risk") never needs withdraw-and-restage. Covers the merge
semantics, the don't-make-it-worse validation rule, who may revise, and the reviewer-side
helpers that ride along (bulk include/exclude, name lookups, the schedule pin).
"""

import pytest

from app.core.security import hash_password
from app.models.base import UserRole
from app.models.user import User


async def _user(session, email: str, role: UserRole) -> None:
    session.add(User(email=email, hashed_password=hash_password("secret123"), role=role))
    await session.commit()


async def _login(client, email: str = "a@e.com") -> dict:
    resp = await client.post(
        "/api/v1/auth/login", data={"username": email, "password": "secret123"}
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _agent(client, full: dict) -> dict:
    resp = await client.post("/api/v1/auth/agent-token", json={}, headers=full)
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _setup(client, session) -> tuple[dict, int]:
    await _user(session, "a@e.com", UserRole.admin)
    full = await _login(client)
    project_id = (
        await client.post("/api/v1/projects", json={"key": "CHK", "name": "Checkout"}, headers=full)
    ).json()["id"]
    return full, project_id


async def _task(client, headers, project_id: int, name: str, duration: int = 3) -> int:
    resp = await client.post(
        "/api/v1/tasks",
        json={"project_id": project_id, "name": name, "duration": duration},
        headers=headers,
    )
    return int(resp.json()["id"])


async def _stage(client, headers, project_id: int, items: list[dict]) -> dict:
    resp = await client.post(
        "/api/v1/proposals",
        json={
            "scope_level": "project",
            "scope_id": project_id,
            "title": "Standup follow-ups",
            "items": items,
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_agent_revises_in_place_while_the_human_reviews(client, db_session) -> None:
    full, project_id = await _setup(client, db_session)
    agent = await _agent(client, full)
    build = await _task(client, full, project_id, "Build ingest")
    staged = await _stage(
        client,
        agent,
        project_id,
        [
            {
                "entity_type": "task",
                "action": "update",
                "entity_id": build,
                "payload": {"duration": 8},
                "reason": "Parser is gnarlier than scoped",
            },
            {
                "entity_type": "risk",
                "action": "create",
                "payload": {"title": "Vendor API instability", "probability": "high"},
            },
        ],
    )
    pid = staged["id"]
    update_item, risk_item = (i["id"] for i in staged["items"])
    assert staged["revision"] == 1 and staged["revision_note"] is None

    # "Make it 6 days and give it a deadline, drop the risk, and add a load test after it."
    revised = await client.post(
        f"/api/v1/proposals/{pid}/revise",
        json={
            "note": "6d not 8d + deadline; dropped the vendor risk; added a load test",
            "update_items": [
                {
                    "item_id": update_item,
                    "payload": {"duration": 6, "deadline": "2026-09-30"},
                    "reason": "Agreed 6d in review",
                }
            ],
            "remove_item_ids": [risk_item],
            "add_items": [
                {
                    "entity_type": "task",
                    "action": "create",
                    "ref": "load",
                    "payload": {"name": "Load test", "duration": 2},
                },
                {
                    "entity_type": "dependency",
                    "action": "create",
                    "payload": {"predecessor_id": build, "successor_ref": "load"},
                },
            ],
        },
        headers=agent,
    )
    assert revised.status_code == 200, revised.text
    detail = revised.json()
    assert detail["revision"] == 2
    assert detail["revision_note"].startswith("6d not 8d")
    assert detail["revised_at"] is not None
    assert detail["item_count"] == 3

    items = {i["id"]: i for i in detail["items"]}
    # (Match on content, not id: SQLite hands a deleted row's id to the next insert.)
    assert [i["entity_type"] for i in detail["items"]] == ["task", "task", "dependency"]
    rewritten = items[update_item]
    # `payload` merges: duration replaced, deadline added; the before-snapshot follows suit.
    assert rewritten["payload"] == {"duration": 6, "deadline": "2026-09-30"}
    assert rewritten["before"]["duration"] == 3 and "deadline" in rewritten["before"]
    assert rewritten["reason"] == "Agreed 6d in review"
    # Every item this revision touched is stamped, so the UI can mark what's new.
    assert all(i["revision"] == 2 for i in detail["items"])

    # Revising is staging, not committing: the live task is untouched, and the agent still
    # cannot apply its own work.
    assert (await client.get(f"/api/v1/tasks/{build}", headers=full)).json()["duration"] == 3
    assert (await client.post(f"/api/v1/proposals/{pid}/apply", headers=agent)).status_code == 403

    applied = await client.post(f"/api/v1/proposals/{pid}/apply", headers=full)
    assert applied.status_code == 200, applied.text
    assert applied.json()["applied"] == 3
    assert (await client.get(f"/api/v1/tasks/{build}", headers=full)).json()["duration"] == 6
    # Once applied the proposal is history — no more revisions.
    assert (
        await client.post(f"/api/v1/proposals/{pid}/revise", json={"title": "late"}, headers=agent)
    ).status_code == 409


@pytest.mark.asyncio
async def test_revision_supersedes_only_the_override_it_rewrites(client, db_session) -> None:
    full, project_id = await _setup(client, db_session)
    build = await _task(client, full, project_id, "Build")
    staged = await _stage(
        client,
        full,
        project_id,
        [
            {
                "entity_type": "task",
                "action": "update",
                "entity_id": build,
                "payload": {"duration": 8, "name": "Build ingest"},
            },
            {"entity_type": "task", "action": "create", "payload": {"name": "Docs", "duration": 1}},
        ],
    )
    pid = staged["id"]
    update_item, docs_item = (i["id"] for i in staged["items"])
    # The reviewer hand-edits two values and vetoes the docs task.
    await client.patch(
        f"/api/v1/proposals/{pid}/items/{update_item}",
        json={"overrides": {"duration": 7, "name": "Build the ingest"}},
        headers=full,
    )
    await client.patch(
        f"/api/v1/proposals/{pid}/items/{docs_item}", json={"excluded": True}, headers=full
    )

    # Then asks Claude for "5 days": the newest instruction wins on `duration`, while the
    # reviewer's rename and the veto on the untouched item both survive.
    revised = await client.post(
        f"/api/v1/proposals/{pid}/revise",
        json={"update_items": [{"item_id": update_item, "payload": {"duration": 5}}]},
        headers=full,
    )
    assert revised.status_code == 200, revised.text
    items = {i["id"]: i for i in revised.json()["items"]}
    assert items[update_item]["payload"]["duration"] == 5
    assert items[update_item]["overrides"] == {"name": "Build the ingest"}
    assert items[update_item]["revision"] == 2
    assert items[docs_item]["excluded"] is True
    assert items[docs_item]["revision"] == 1  # untouched → not marked as changed


@pytest.mark.asyncio
async def test_revision_may_not_make_the_proposal_worse(client, db_session) -> None:
    full, project_id = await _setup(client, db_session)
    doomed = await _task(client, full, project_id, "Doomed")
    kept = await _task(client, full, project_id, "Kept")
    staged = await _stage(
        client,
        full,
        project_id,
        [
            {
                "entity_type": "task",
                "action": "create",
                "ref": "phase",
                "payload": {"name": "Hardening", "type": "summary"},
            },
            {
                "entity_type": "task",
                "action": "create",
                "payload": {"name": "Pentest", "parent_ref": "phase"},
            },
            {
                "entity_type": "task",
                "action": "update",
                "entity_id": doomed,
                "payload": {"duration": 9},
            },
            {
                "entity_type": "task",
                "action": "update",
                "entity_id": kept,
                "payload": {"duration": 4},
            },
        ],
    )
    pid = staged["id"]
    phase, pentest, doomed_item, kept_item = (i["id"] for i in staged["items"])

    async def revise(body: dict) -> object:
        return await client.post(f"/api/v1/proposals/{pid}/revise", json=body, headers=full)

    # A bad new item, a bad rewrite, and a removal that strands a ref are each refused…
    bad_add = await revise(
        {"add_items": [{"entity_type": "task", "action": "create", "payload": {"name": ""}}]}
    )
    assert bad_add.status_code == 400
    assert bad_add.json()["detail"]["code"] == "invalid_items"
    assert bad_add.json()["detail"]["errors"][0]["add_index"] == 0
    bad_update = await revise(
        {"update_items": [{"item_id": kept_item, "payload": {"status": "Done"}}]}
    )
    assert bad_update.json()["detail"]["errors"][0]["item_id"] == kept_item
    stranded = await revise({"remove_item_ids": [phase]})
    assert stranded.status_code == 400
    assert stranded.json()["detail"]["errors"][0]["item_id"] == pentest
    # …and malformed requests never get that far.
    assert (await revise({})).status_code == 400
    assert (await revise({"remove_item_ids": [99999]})).status_code == 400
    assert (
        await revise(
            {
                "remove_item_ids": [kept_item],
                "update_items": [{"item_id": kept_item, "payload": {"duration": 2}}],
            }
        )
    ).status_code == 400
    # Nothing above changed the proposal.
    untouched = (await client.get(f"/api/v1/proposals/{pid}", headers=full)).json()
    assert untouched["revision"] == 1 and untouched["item_count"] == 4
    assert {i["id"]: i for i in untouched["items"]}[kept_item]["payload"] == {"duration": 4}

    # A problem that was already there (its target was deleted after staging) does not
    # block an unrelated fix — and the author can clear it by removing that item.
    assert (await client.delete(f"/api/v1/tasks/{doomed}", headers=full)).status_code == 204
    ok = await revise({"update_items": [{"item_id": kept_item, "payload": {"duration": 5}}]})
    assert ok.status_code == 200, ok.text
    cleaned = await revise({"remove_item_ids": [doomed_item], "note": "dropped the stale edit"})
    assert cleaned.status_code == 200
    assert cleaned.json()["revision"] == 3
    preview = (await client.get(f"/api/v1/proposals/{pid}/preview", headers=full)).json()
    assert preview["can_apply"] is True and preview["revision"] == 3


@pytest.mark.asyncio
async def test_revision_reorders_so_a_late_ref_still_resolves(client, db_session) -> None:
    full, project_id = await _setup(client, db_session)
    staged = await _stage(
        client,
        full,
        project_id,
        [
            {
                "entity_type": "task",
                "action": "create",
                "payload": {"name": "Pentest", "duration": 5},
            }
        ],
    )
    pid = staged["id"]
    pentest = staged["items"][0]["id"]

    # Add a phase *after* the task exists in the batch, then hang the task under it.
    revised = await client.post(
        f"/api/v1/proposals/{pid}/revise",
        json={
            "add_items": [
                {
                    "entity_type": "task",
                    "action": "create",
                    "ref": "phase",
                    "payload": {"name": "Hardening", "type": "summary"},
                }
            ],
            "update_items": [{"item_id": pentest, "payload": {"parent_ref": "phase"}}],
        },
        headers=full,
    )
    assert revised.status_code == 200, revised.text
    assert [i["payload"]["name"] for i in revised.json()["items"]] == ["Hardening", "Pentest"]

    applied = await client.post(f"/api/v1/proposals/{pid}/apply", headers=full)
    assert applied.status_code == 200, applied.text
    tasks = {
        t["name"]: t
        for t in (await client.get(f"/api/v1/tasks?project_id={project_id}", headers=full)).json()
    }
    assert tasks["Pentest"]["parent_id"] == tasks["Hardening"]["id"]


@pytest.mark.asyncio
async def test_only_the_author_or_a_planner_may_revise(client, db_session) -> None:
    full, project_id = await _setup(client, db_session)
    await _user(db_session, "eng@e.com", UserRole.engineer)
    await _user(db_session, "other@e.com", UserRole.engineer)
    await _user(db_session, "viewer@e.com", UserRole.viewer)
    author = await _login(client, "eng@e.com")
    staged = await _stage(
        client,
        author,
        project_id,
        [{"entity_type": "task", "action": "create", "payload": {"name": "Spike"}}],
    )
    pid = staged["id"]
    body = {"title": "Renamed"}

    async def revise(headers: dict) -> int:
        resp = await client.post(f"/api/v1/proposals/{pid}/revise", json=body, headers=headers)
        return int(resp.status_code)

    assert await revise(await _login(client, "other@e.com")) == 403  # someone else's proposal
    assert await revise(await _login(client, "viewer@e.com")) == 403  # read-only role
    assert await revise(author) == 200  # the author (an engineer)
    assert await revise(full) == 200  # a planner
    detail = (await client.get(f"/api/v1/proposals/{pid}", headers=full)).json()
    assert detail["title"] == "Renamed" and detail["revision"] == 3
    assert detail["created_by"] == "eng@e.com"


@pytest.mark.asyncio
async def test_bulk_include_exclude_is_a_human_review_action(client, db_session) -> None:
    full, project_id = await _setup(client, db_session)
    agent = await _agent(client, full)
    staged = await _stage(
        client,
        full,
        project_id,
        [
            {"entity_type": "task", "action": "create", "payload": {"name": "A"}},
            {"entity_type": "risk", "action": "create", "payload": {"title": "R1"}},
            {"entity_type": "risk", "action": "create", "payload": {"title": "R2"}},
        ],
    )
    pid = staged["id"]
    risks = [i["id"] for i in staged["items"] if i["entity_type"] == "risk"]

    url = f"/api/v1/proposals/{pid}/items"
    assert (await client.patch(url, json={"excluded": True}, headers=agent)).status_code == 403
    skipped = await client.patch(url, json={"excluded": True, "item_ids": risks}, headers=full)
    assert skipped.status_code == 200
    assert skipped.json()["excluded_count"] == 2
    assert (
        await client.patch(url, json={"excluded": True, "item_ids": [424242]}, headers=full)
    ).status_code == 404
    everything = await client.patch(url, json={"excluded": False}, headers=full)
    assert everything.json()["excluded_count"] == 0


@pytest.mark.asyncio
async def test_names_resolve_and_unknown_people_are_refused(client, db_session) -> None:
    full, project_id = await _setup(client, db_session)
    build = await _task(client, full, project_id, "Build")
    dana = (
        await client.post("/api/v1/team/engineers", json={"name": "Dana Lee"}, headers=full)
    ).json()["id"]

    ghost = await client.post(
        "/api/v1/proposals",
        json={
            "scope_level": "project",
            "scope_id": project_id,
            "title": "Assign",
            "items": [
                {
                    "entity_type": "task",
                    "action": "update",
                    "entity_id": build,
                    "payload": {"assignee_engineer_id": 9999},
                }
            ],
        },
        headers=full,
    )
    assert ghost.status_code == 400
    assert "not a known engineer" in ghost.json()["detail"]["errors"][0]["error"]

    staged = await _stage(
        client,
        full,
        project_id,
        [
            {
                "entity_type": "task",
                "action": "update",
                "entity_id": build,
                "payload": {"assignee_engineer_id": dana},
            },
            {
                "entity_type": "blocker",
                "action": "create",
                "payload": {"task_id": build, "reason": "Waiting on SOW"},
            },
            {"entity_type": "milestone", "action": "create", "payload": {"name": "Beta"}},
        ],
    )
    # The reader sees names, not ids.
    assert staged["lookups"]["engineer"] == {str(dana): "Dana Lee"}
    assert staged["lookups"]["task"] == {str(build): "Build"}
    assert staged["lookups"]["project"][str(project_id)].startswith("CHK")
    # Staged items advertise what a reviewer could still add inline.
    assert "deadline" in staged["items"][0]["addable_fields"]
    assert "assignee_engineer_id" not in staged["items"][0]["addable_fields"]


@pytest.mark.asyncio
async def test_a_staged_pin_actually_moves_the_schedule(client, db_session) -> None:
    """`constraint_start` (start no earlier than) is the stageable schedule pin — unlike
    `start`, which is computed output the replan overwrites."""
    await _user(db_session, "a@e.com", UserRole.admin)
    full = await _login(client)
    project_id = (
        await client.post(
            "/api/v1/projects",
            json={"key": "PIN", "name": "Pin", "start_date": "2026-03-02"},
            headers=full,
        )
    ).json()["id"]
    task = await _task(client, full, project_id, "Vendor integration")
    staged = await _stage(
        client,
        full,
        project_id,
        [
            {
                "entity_type": "task",
                "action": "update",
                "entity_id": task,
                "payload": {"constraint_start": "2026-03-16"},
                "reason": "Vendor sandbox opens on the 16th",
            }
        ],
    )
    preview = (await client.get(f"/api/v1/proposals/{staged['id']}/preview", headers=full)).json()
    assert preview["projects"][0]["task_changes"][0]["start_after"] == "2026-03-16"
    await client.post(f"/api/v1/proposals/{staged['id']}/apply", headers=full)
    assert (await client.get(f"/api/v1/tasks/{task}", headers=full)).json()["start"] == "2026-03-16"
