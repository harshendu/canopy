"""Proposal plan preview: the plan as a whole, current vs proposed.

The simulation is pure (`stage_items` / `preview_project`), so most of this runs without a
database. The endpoint tests then pin the property that matters most to a reviewer: what the
preview shows as "proposed" is *exactly* what apply produces, and looking never writes.
"""

from datetime import date

import pytest

from app.core.security import hash_password
from app.models.base import DependencyType, ProposalAction, ProposalEntity, TaskType, UserRole
from app.models.user import User
from app.services.planner import RollupNode, rollup_summaries
from app.services.proposal_preview import (
    SimDep,
    SimItem,
    SimMilestone,
    SimProject,
    SimTask,
    preview_project,
    stage_items,
    wbs_order,
)
from app.services.scheduling import WorkingCalendar

D0 = date(2026, 3, 2)


def _task(task_id: int, name: str, duration: int = 1, **extra) -> SimTask:
    base = {
        "id": task_id,
        "project_id": 1,
        "name": name,
        "type": TaskType.task,
        "parent_id": None,
        "duration": duration,
        "start": None,
        "end": None,
        "constraint_start": None,
        "deadline": None,
        "percent_complete": 0.0,
        "assignee_engineer_id": None,
    }
    return SimTask(**{**base, **extra})


def _project() -> SimProject:
    return SimProject(id=1, key="CHK", name="Checkout", start_date=D0, calendar=WorkingCalendar())


def _item(item_id: int, entity: str, action: str, fields: dict, **extra) -> SimItem:
    return SimItem(
        id=item_id,
        entity_type=ProposalEntity(entity),
        action=ProposalAction(action),
        entity_id=extra.get("entity_id"),
        ref=extra.get("ref"),
        fields=fields,
    )


def _chain() -> tuple[list[SimTask], list[SimDep]]:
    """Design (3d) → Build (2d) → Ship (1d), all in one phase."""
    tasks = [
        _task(1, "Delivery", type=TaskType.summary),
        _task(2, "Design", 3, parent_id=1),
        _task(3, "Build", 2, parent_id=1),
        _task(4, "Ship", 1, parent_id=1),
    ]
    deps = [
        SimDep(1, 2, 3, DependencyType.FS, 0),
        SimDep(2, 3, 4, DependencyType.FS, 0),
    ]
    return tasks, deps


def test_edit_add_and_knock_on_shift_are_told_apart() -> None:
    tasks, deps = _chain()
    items = [
        # Design grows 3d → 5d: Build and Ship get pushed without being touched.
        _item(10, "task", "update", {"duration": 5}, entity_id=2),
        # A new task, hung under the phase and chained after Ship via a ref.
        _item(
            11,
            "task",
            "create",
            {"project_id": 1, "name": "Load test", "duration": 4, "parent_id": 1},
            ref="load",
        ),
        _item(12, "dependency", "create", {"predecessor_id": 4, "successor_ref": "load"}),
    ]
    plan = stage_items(tasks, deps, [], items)
    view = preview_project(_project(), tasks, deps, [], plan, {})

    kinds = {c.name: c.kind for c in view.task_changes}
    assert kinds == {
        "Delivery": "shifted",  # the phase spans further
        "Design": "edited",
        "Build": "shifted",
        "Ship": "shifted",
        "Load test": "added",
    }
    by_name = {c.name: c for c in view.task_changes}
    assert by_name["Build"].end_delta_days == 2
    assert by_name["Design"].item_ids == [10]
    # The staged dependency is linked to the task it moves (its successor).
    assert by_name["Load test"].item_ids == [11, 12]
    assert by_name["Load test"].task_id == -11  # not created yet → synthetic id
    assert by_name["Load test"].start_before is None

    # Current finishes at day 6; proposed = 5 + 2 + 1 + 4 = day 12.
    assert view.end_current == date(2026, 3, 8)
    assert view.end_proposed == date(2026, 3, 14)
    assert view.end_delta_days == 6
    assert view.proposed is not None
    # Both sides are full plans in the same WBS order, so toggling never reshuffles rows.
    assert [t.text for t in view.current.tasks] == ["Delivery", "Design", "Build", "Ship"]
    assert [t.text for t in view.proposed.tasks] == [
        "Delivery",
        "Design",
        "Build",
        "Ship",
        "Load test",
    ]
    assert {link.id for link in view.proposed.links} == {1, 2, -12}
    assert plan.counts.tasks_added == 1 and plan.counts.dependencies_added == 1
    # The live inputs were copied, not mutated.
    assert tasks[1].duration == 3


def test_a_staged_cycle_is_reported_not_raised() -> None:
    tasks, deps = _chain()
    items = [_item(10, "dependency", "create", {"predecessor_id": 4, "successor_id": 2})]
    plan = stage_items(tasks, deps, [], items)
    view = preview_project(_project(), tasks, deps, [], plan, {})
    assert view.cycle is True
    assert view.proposed is None  # nothing to show for the future state…
    assert len(view.current.tasks) == 4  # …but the current plan still renders


def test_items_that_cannot_be_placed_are_skipped() -> None:
    tasks, deps = _chain()
    items = [
        _item(10, "task", "update", {"duration": 9}, entity_id=999),  # target is gone
        _item(11, "task", "create", {"project_id": 1, "name": "Orphan", "parent_ref": "nope"}),
        _item(12, "dependency", "create", {"predecessor_ref": "nope", "successor_id": 2}),
    ]
    plan = stage_items(tasks, deps, [], items)
    assert [t.name for t in plan.tasks] == ["Delivery", "Design", "Build", "Ship"]
    assert len(plan.deps) == 2
    view = preview_project(_project(), tasks, deps, [], plan, {})
    assert view.task_changes == []
    assert view.end_delta_days == 0


def test_a_pin_and_a_new_deadline_miss() -> None:
    tasks, deps = _chain()
    tasks[3].deadline = date(2026, 3, 9)  # Ship is due the day after it currently lands
    items = [
        _item(10, "task", "update", {"constraint_start": date(2026, 3, 10)}, entity_id=3),
    ]
    plan = stage_items(tasks, deps, [], items)
    view = preview_project(_project(), tasks, deps, [], plan, {})
    by_name = {c.name: c for c in view.task_changes}
    assert by_name["Build"].start_after == date(2026, 3, 10)
    assert by_name["Ship"].kind == "shifted"
    assert [m.name for m in view.new_deadline_misses] == ["Ship"]


def test_milestones_before_and_after() -> None:
    live = [SimMilestone(5, 1, "Beta", date(2026, 4, 1), "planned")]
    items = [
        _item(10, "milestone", "update", {"target_date": date(2026, 4, 15)}, entity_id=5),
        _item(
            11,
            "milestone",
            "create",
            {"project_id": 1, "name": "GA", "target_date": date(2026, 5, 1), "status": "planned"},
        ),
    ]
    tasks, deps = _chain()
    plan = stage_items(tasks, deps, live, items)
    view = preview_project(_project(), tasks, deps, live, plan, {})
    rows = {m.name: m for m in view.milestones}
    assert rows["Beta"].kind == "edited"
    assert (rows["Beta"].target_before, rows["Beta"].target_after) == (
        date(2026, 4, 1),
        date(2026, 4, 15),
    )
    assert rows["GA"].kind == "added" and rows["GA"].target_before is None
    assert live[0].target_date == date(2026, 4, 1)  # live input untouched


def test_stale_saved_schedule_is_flagged() -> None:
    tasks, deps = _chain()
    view = preview_project(_project(), tasks, deps, [], stage_items(tasks, deps, [], []), {})
    # Nothing was ever saved (start/end are None) → the recomputed "current" differs.
    assert view.live_schedule_stale is True
    for t, row in zip(tasks[1:], view.current.tasks[1:], strict=True):
        t.start, t.end = row.start_date, row.end_date
    fresh = preview_project(_project(), tasks, deps, [], stage_items(tasks, deps, [], []), {})
    assert fresh.live_schedule_stale is False
    assert fresh.task_changes == []


def test_wbs_order_puts_new_tasks_under_their_phase() -> None:
    tasks = [
        _task(1, "Phase A", type=TaskType.summary),
        _task(2, "Phase B", type=TaskType.summary),
        _task(3, "a1", parent_id=1),
        _task(4, "b1", parent_id=2),
        _task(-9, "a-new", parent_id=1),
    ]
    assert [t.name for t in wbs_order(tasks)] == ["Phase A", "a1", "a-new", "Phase B", "b1"]


def test_summary_rollup_is_bottom_up() -> None:
    """A nested phase must be rolled up before its parent reads it, whatever the row order."""
    nodes = [
        RollupNode(1, None, True, date(2026, 1, 1), date(2026, 1, 2)),  # stale outer span
        RollupNode(2, 1, True, date(2026, 1, 1), date(2026, 1, 2)),  # stale inner span
        RollupNode(3, 2, False, date(2026, 2, 1), date(2026, 2, 10)),
    ]
    rolled = rollup_summaries(nodes)
    assert rolled[2] == (date(2026, 2, 1), date(2026, 2, 10))
    assert rolled[1] == (date(2026, 2, 1), date(2026, 2, 10))


# --- endpoint: the preview is faithful to apply, and read-only ---


async def _admin_headers(client, session) -> dict:
    session.add(
        User(email="a@e.com", hashed_password=hash_password("secret123"), role=UserRole.admin)
    )
    await session.commit()
    resp = await client.post(
        "/api/v1/auth/login", data={"username": "a@e.com", "password": "secret123"}
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _seed_plan(client, headers) -> tuple[int, dict[str, int]]:
    project_id = (
        await client.post(
            "/api/v1/projects",
            json={"key": "CHK", "name": "Checkout", "start_date": "2026-03-02"},
            headers=headers,
        )
    ).json()["id"]
    ids: dict[str, int] = {}
    for name, duration in (("Design", 3), ("Build", 2), ("Ship", 1)):
        ids[name] = (
            await client.post(
                "/api/v1/tasks",
                json={"project_id": project_id, "name": name, "duration": duration},
                headers=headers,
            )
        ).json()["id"]
    for pred, succ in (("Design", "Build"), ("Build", "Ship")):
        await client.post(
            "/api/v1/dependencies",
            json={"predecessor_id": ids[pred], "successor_id": ids[succ]},
            headers=headers,
        )
    await client.post(f"/api/v1/projects/{project_id}/replan", headers=headers)
    return project_id, ids


async def _gantt_dates(client, headers, project_id: int) -> dict[str, tuple[str, str]]:
    gantt = (await client.get(f"/api/v1/projects/{project_id}/gantt", headers=headers)).json()
    return {t["text"]: (t["start_date"], t["end_date"]) for t in gantt["tasks"]}


@pytest.mark.asyncio
async def test_preview_matches_what_apply_produces(client, db_session) -> None:
    headers = await _admin_headers(client, db_session)
    project_id, ids = await _seed_plan(client, headers)
    before = await _gantt_dates(client, headers, project_id)

    staged = await client.post(
        "/api/v1/proposals",
        json={
            "scope_level": "project",
            "scope_id": project_id,
            "title": "Design is bigger than scoped",
            "items": [
                {
                    "entity_type": "task",
                    "action": "update",
                    "entity_id": ids["Design"],
                    "payload": {"duration": 6},
                },
                {
                    "entity_type": "task",
                    "action": "create",
                    "ref": "load",
                    "payload": {"name": "Load test", "duration": 4},
                },
                {
                    "entity_type": "dependency",
                    "action": "create",
                    "payload": {"predecessor_id": ids["Ship"], "successor_ref": "load"},
                },
                {
                    "entity_type": "risk",
                    "action": "create",
                    "payload": {"title": "Vendor slips", "probability": "high"},
                },
            ],
        },
        headers=headers,
    )
    assert staged.status_code == 201, staged.text
    pid = staged.json()["id"]

    resp = await client.get(f"/api/v1/proposals/{pid}/preview", headers=headers)
    assert resp.status_code == 200, resp.text
    preview = resp.json()
    assert preview["can_apply"] is True and preview["issues"] == []
    assert preview["included"] == 4
    assert preview["counts"]["tasks_added"] == 1
    assert preview["counts"]["tasks_edited"] == 1
    assert preview["counts"]["tasks_shifted"] == 2  # Build + Ship
    assert preview["counts"]["risks_added"] == 1
    plan = preview["projects"][0]
    assert plan["live_schedule_stale"] is False
    assert plan["end_delta_days"] == 7  # +3 on Design, +4 for the new tail task
    # "Current" is the live plan, untouched.
    assert {t["text"]: (t["start_date"], t["end_date"]) for t in plan["current"]["tasks"]} == before
    # Looking is read-only: the live schedule did not move.
    assert await _gantt_dates(client, headers, project_id) == before

    predicted = {t["text"]: (t["start_date"], t["end_date"]) for t in plan["proposed"]["tasks"]}
    applied = await client.post(f"/api/v1/proposals/{pid}/apply", headers=headers)
    assert applied.status_code == 200, applied.text
    assert await _gantt_dates(client, headers, project_id) == predicted

    # A closed proposal has no future state to preview.
    assert (
        await client.get(f"/api/v1/proposals/{pid}/preview", headers=headers)
    ).status_code == 409


@pytest.mark.asyncio
async def test_preview_follows_the_reviewers_edits_and_warns_before_apply(
    client, db_session
) -> None:
    headers = await _admin_headers(client, db_session)
    project_id, ids = await _seed_plan(client, headers)
    staged = await client.post(
        "/api/v1/proposals",
        json={
            "scope_level": "project",
            "scope_id": project_id,
            "title": "Hardening",
            "items": [
                {
                    "entity_type": "task",
                    "action": "create",
                    "ref": "phase",
                    "payload": {"name": "Hardening", "type": "summary"},
                },
                {
                    "entity_type": "task",
                    "action": "create",
                    "payload": {"name": "Pentest", "duration": 5, "parent_ref": "phase"},
                },
                {
                    "entity_type": "task",
                    "action": "update",
                    "entity_id": ids["Build"],
                    "payload": {"duration": 4},
                },
            ],
        },
        headers=headers,
    )
    pid = staged.json()["id"]
    phase, pentest, build = (i["id"] for i in staged.json()["items"])

    async def preview() -> dict:
        return (await client.get(f"/api/v1/proposals/{pid}/preview", headers=headers)).json()

    assert (await preview())["projects"][0]["end_delta_days"] == 2

    # An inline override changes the future state the reviewer is looking at…
    await client.patch(
        f"/api/v1/proposals/{pid}/items/{build}",
        json={"overrides": {"duration": 9}},
        headers=headers,
    )
    assert (await preview())["projects"][0]["end_delta_days"] == 7
    # …and excluding the change takes it back out.
    await client.patch(
        f"/api/v1/proposals/{pid}/items/{build}", json={"excluded": True}, headers=headers
    )
    after_exclude = await preview()
    assert after_exclude["projects"][0]["end_delta_days"] == 0
    assert after_exclude["excluded"] == 1 and after_exclude["can_apply"] is True

    # Excluding the phase strands the task that hangs under it — known *before* Apply.
    await client.patch(
        f"/api/v1/proposals/{pid}/items/{phase}", json={"excluded": True}, headers=headers
    )
    blocked = await preview()
    assert blocked["can_apply"] is False
    assert [i["item_id"] for i in blocked["issues"]] == [pentest]
    assert "parent_ref" in blocked["issues"][0]["error"]
    # The coherent remainder still previews (nothing staged survives here).
    assert blocked["projects"][0]["task_changes"] == []


@pytest.mark.asyncio
async def test_preview_reports_a_dependency_cycle(client, db_session) -> None:
    headers = await _admin_headers(client, db_session)
    project_id, ids = await _seed_plan(client, headers)
    staged = await client.post(
        "/api/v1/proposals",
        json={
            "scope_level": "project",
            "scope_id": project_id,
            "title": "Loop",
            "items": [
                {
                    "entity_type": "dependency",
                    "action": "create",
                    "payload": {"predecessor_id": ids["Ship"], "successor_id": ids["Design"]},
                }
            ],
        },
        headers=headers,
    )
    preview = (
        await client.get(f"/api/v1/proposals/{staged.json()['id']}/preview", headers=headers)
    ).json()
    assert preview["can_apply"] is False
    assert preview["projects"][0]["cycle"] is True
    assert preview["projects"][0]["proposed"] is None
    assert "cycle" in preview["issues"][0]["error"]
