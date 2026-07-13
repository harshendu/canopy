from datetime import date, datetime, timedelta

import pytest

from app.core.security import hash_password
from app.models.base import UserRole
from app.models.project import Task, TaskStatusHistory
from app.models.user import User
from app.services.flow import NO_STATUS, BoardTaskInput, build_board

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

    # `status` is Jira-mirrored (read-only via the API) — set it directly, as a sync would.
    for tid, st in ((t1, "In Progress"), (t2, "Done")):
        task = await db_session.get(Task, tid)
        assert task is not None
        task.status = st
    # Make A look like it entered "In Progress" well in the past.
    db_session.add(
        TaskStatusHistory(
            task_id=t1,
            to_status="In Progress",
            changed_at=datetime.combine(date.today() - timedelta(days=10), datetime.min.time()),
        )
    )
    await db_session.commit()

    board = (await client.get(f"/api/v1/projects/{project_id}/board", headers=headers)).json()
    labels = [lane["status"] for lane in board["lanes"]]
    assert "In Progress" in labels and "Done" in labels
    assert labels[-1] == "Done"  # done lane last
    in_progress = next(lane for lane in board["lanes"] if lane["status"] == "In Progress")
    assert in_progress["wip"] == 1
    a_task = in_progress["tasks"][0]
    assert a_task["age_days"] >= 10
