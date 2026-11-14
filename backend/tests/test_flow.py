from datetime import date, datetime, timedelta

import pytest
from sqlmodel import select

from app.core.security import hash_password
from app.models.base import UserRole
from app.models.project import TaskStatusHistory
from app.models.user import User
from app.services.flow import (
    NO_STATUS,
    BoardTaskInput,
    ColumnDef,
    HistoryPoint,
    build_board,
    completion_dates,
    effective_rank,
    flow_facts,
    rank_between,
    renumbered,
)

# --- Pure service ------------------------------------------------------------


def test_board_groups_lanes_wip_and_orders_done_last():
    board = build_board(
        [
            BoardTaskInput(1, "A", "In Progress", None, is_done=False, age_days=1),
            BoardTaskInput(2, "B", "In Progress", None, is_done=False, age_days=2),
            BoardTaskInput(3, "C", "Done", None, is_done=True, age_days=0, cycle_days=4),
            BoardTaskInput(4, "D", None, None, is_done=False, age_days=1),
        ]
    )
    labels = [lane.status for lane in board.lanes]
    assert labels[-1] == "Done"  # done lane sorts last
    assert NO_STATUS in labels
    in_progress = next(lane for lane in board.lanes if lane.status == "In Progress")
    assert in_progress.wip == 2  # two not-done tasks


def test_board_flags_aging_beyond_cycle_time_p85():
    # Two done tasks with cycle 2 and 4 days -> P85 == 4. An in-progress task aged 6 days is aging.
    board = build_board(
        [
            BoardTaskInput(1, "old done", "Done", None, is_done=True, age_days=0, cycle_days=2),
            BoardTaskInput(2, "old done2", "Done", None, is_done=True, age_days=0, cycle_days=4),
            BoardTaskInput(3, "stuck", "In Progress", None, is_done=False, age_days=6),
            BoardTaskInput(4, "fresh", "In Progress", None, is_done=False, age_days=1),
        ]
    )
    assert board.cycle_time_p85_days == 4
    by_id = {t.id: t for lane in board.lanes for t in lane.tasks}
    assert by_id[3].aging is True
    assert by_id[4].aging is False
    assert board.aging_count == 1


def test_board_no_cycle_history_means_no_aging():
    board = build_board(
        [BoardTaskInput(1, "x", "In Progress", None, is_done=False, age_days=99)]
    )
    assert board.cycle_time_p85_days is None
    assert board.aging_count == 0


def _columns() -> list[ColumnDef]:
    return [
        ColumnDef("To Do", "todo", 0),
        ColumnDef("In Progress", "in_progress", 1, wip_limit=1),
        ColumnDef("Done", "done", 2),
        ColumnDef("Cancelled", "cancelled", 3),
    ]


def test_board_with_columns_shows_empty_columns_limits_and_unknown_statuses():
    board = build_board(
        [
            BoardTaskInput(1, "A", "In Progress", None, False, 1, category="in_progress"),
            BoardTaskInput(2, "B", "In Progress", None, False, 1, category="in_progress"),
            BoardTaskInput(3, "C", "QA", None, False, 1, category="in_progress"),
            BoardTaskInput(4, "D", None, None, False, 1),
            BoardTaskInput(5, "E", "Cancelled", None, False, 1, category="cancelled"),
        ],
        _columns(),
    )
    labels = [lane.status for lane in board.lanes]
    # The inbox first; an unknown status lands after the last column of its category.
    assert labels == [NO_STATUS, "To Do", "In Progress", "QA", "Done", "Cancelled"]
    lanes = {lane.status: lane for lane in board.lanes}
    assert lanes["To Do"].tasks == []  # empty columns are shown
    assert lanes["In Progress"].wip == 2 and lanes["In Progress"].over_limit is True
    assert lanes["QA"].in_workflow is False
    assert lanes["Cancelled"].wip == 0  # cancelled work is not WIP
    assert lanes["Done"].is_done is True


def test_board_orders_cards_by_rank_then_id():
    board = build_board(
        [
            BoardTaskInput(1, "A", "To Do", None, False, 0, category="todo", rank=3000),
            BoardTaskInput(2, "B", "To Do", None, False, 0, category="todo", rank=1000),
            BoardTaskInput(3, "C", "To Do", None, False, 0, category="todo", rank=2000),
        ],
        _columns(),
    )
    lane = next(lane for lane in board.lanes if lane.status == "To Do")
    assert [t.id for t in lane.tasks] == [2, 3, 1]


def test_rank_between_and_renumbering():
    assert rank_between(None, None) == 1024
    assert rank_between(1024, 2048) == 1536
    assert rank_between(None, 2048) == 1024
    assert rank_between(2048, None) == 3072
    assert rank_between(5, 6) is None  # no gap left -> renumber
    assert rank_between(-1, 1) is None  # 0 is reserved for "unranked"
    assert rank_between(-2, 2) in (1, -1)
    assert effective_rank(0, 7) == 7 * 1024
    assert effective_rank(55, 7) == 55
    assert renumbered([9, 4, 6]) == {9: 1024, 4: 2048, 6: 3072}


def test_flow_facts_separate_cycle_time_from_lead_time():
    d = date(2026, 5, 1)
    history = [
        HistoryPoint("To Do", "todo", d),
        HistoryPoint("In Progress", "in_progress", d + timedelta(days=10)),
        HistoryPoint("Done", "done", d + timedelta(days=14)),
    ]
    facts = flow_facts("Done", d, d + timedelta(days=14), history, d + timedelta(days=20))
    assert facts.lead_days == 14  # created -> done
    assert facts.cycle_days == 4  # started -> done
    assert facts.done_on == d + timedelta(days=14)
    assert facts.age_days == 6
    never_started = flow_facts("Done", d, d, [HistoryPoint("Done", "done", d)], d)
    assert never_started.cycle_days == 0


def test_completion_counts_each_task_once_at_its_last_done():
    d = date(2026, 5, 1)
    rows = [
        (1, HistoryPoint("Done", "done", d)),
        (1, HistoryPoint("To Do", "todo", d + timedelta(days=1))),
        (1, HistoryPoint("Done", "done", d + timedelta(days=3))),
        (2, HistoryPoint("Shipped", "done", d + timedelta(days=2))),
        (3, HistoryPoint("Cancelled", "cancelled", d)),
    ]
    assert completion_dates(rows) == [d + timedelta(days=2), d + timedelta(days=3)]


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


async def _token(client) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "architect@example.com", "password": "secret123"},
    )
    return resp.json()["access_token"]


@pytest.mark.asyncio
async def test_board_endpoint(client, db_session):
    await _seed_admin(db_session)
    headers = {"Authorization": f"Bearer {await _token(client)}"}
    project_id = (
        await client.post(
            "/api/v1/projects", json={"key": "PLAT", "name": "Platform"}, headers=headers
        )
    ).json()["id"]
    t1 = (
        await client.post(
            "/api/v1/tasks",
            json={"project_id": project_id, "name": "A", "duration": 2},
            headers=headers,
        )
    ).json()["id"]
    t2 = (
        await client.post(
            "/api/v1/tasks",
            json={"project_id": project_id, "name": "B", "duration": 2},
            headers=headers,
        )
    ).json()["id"]

    # Native project: statuses change through the move endpoint (recorded as transitions).
    for tid, st in ((t1, "In Progress"), (t2, "Done")):
        resp = await client.post(
            f"/api/v1/tasks/{tid}/move", json={"to_status": st}, headers=headers
        )
        assert resp.status_code == 200, resp.text
    # Make A look like it entered "In Progress" well in the past.
    row = (
        await db_session.execute(
            select(TaskStatusHistory).where(
                TaskStatusHistory.task_id == t1, TaskStatusHistory.to_status == "In Progress"
            )
        )
    ).scalars().one()
    row.changed_at = datetime.combine(date.today() - timedelta(days=10), datetime.min.time())
    await db_session.commit()

    board = (await client.get(f"/api/v1/projects/{project_id}/board", headers=headers)).json()
    labels = [lane["status"] for lane in board["lanes"]]
    # Every workflow column, in order — empty ones included.
    assert labels == ["Backlog", "To Do", "In Progress", "In Review", "Done", "Cancelled"]
    done = next(lane for lane in board["lanes"] if lane["status"] == "Done")
    assert done["is_done"] is True and done["category"] == "done"
    in_progress = next(lane for lane in board["lanes"] if lane["status"] == "In Progress")
    assert in_progress["wip"] == 1
    a_task = in_progress["tasks"][0]
    assert a_task["age_days"] >= 10
    assert a_task["key"] == "PLAT-1" and a_task["movable"] is True
    assert board["mode"] == "native"
    assert board["viewer"]["can_plan"] is True
