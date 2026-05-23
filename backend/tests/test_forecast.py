from datetime import date, datetime, timedelta

import pytest

from app.core.security import hash_password
from app.models.base import UserRole
from app.models.project import TaskStatusHistory
from app.models.user import User
from app.services.forecast import monte_carlo_forecast, weekly_throughput

# --- Pure service ------------------------------------------------------------


def test_weekly_throughput_includes_zero_weeks():
    # Two completions in the week of Jan 5, one in the week of Jan 19; Jan 12 week is empty.
    done = [date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 20)]
    assert weekly_throughput(done, today=date(2026, 1, 21)) == [2, 0, 1]


def test_forecast_insufficient_without_history():
    r = monte_carlo_forecast(remaining_items=5, throughput=[], today=date(2026, 1, 1))
    assert r.sufficient is False
    assert r.reason is not None
    assert r.p50_date is None


def test_forecast_already_done_is_today():
    r = monte_carlo_forecast(remaining_items=0, throughput=[1, 2, 3], today=date(2026, 1, 1))
    assert r.sufficient is True
    assert r.p50_weeks == 0
    assert r.p50_date == date(2026, 1, 1)


def test_forecast_steady_throughput_has_no_variance():
    # 10 items at a steady 5/week -> exactly 2 weeks every trial; P50 == P85.
    r = monte_carlo_forecast(
        remaining_items=10, throughput=[5, 5, 5, 5], today=date(2026, 1, 1), seed=1
    )
    assert r.sufficient is True
    assert r.p50_weeks == 2
    assert r.p85_weeks == 2
    assert r.p50_date == date(2026, 1, 15)


def test_forecast_variance_widens_the_p85_band():
    # Variable (incl. zero) weeks -> P85 must be no sooner than P50, both positive.
    r = monte_carlo_forecast(
        remaining_items=20, throughput=[0, 1, 2, 10], today=date(2026, 1, 1), seed=7
    )
    assert r.sufficient is True
    assert r.p85_weeks >= r.p50_weeks > 0
    assert r.p85_date is not None and r.p50_date is not None
    assert r.p85_date >= r.p50_date


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
async def test_project_forecast_endpoint(client, db_session):
    await _seed_admin(db_session)
    headers = {"Authorization": f"Bearer {await _token(client)}"}
    project_id = (
        await client.post(
            "/api/v1/projects", json={"key": "PLAT", "name": "Platform"}, headers=headers
        )
    ).json()["id"]

    ids = []
    for i in range(4):
        tid = (
            await client.post(
                "/api/v1/tasks",
                json={"project_id": project_id, "name": f"T{i}", "duration": 2},
                headers=headers,
            )
        ).json()["id"]
        ids.append(tid)
    # Two are complete; two remain.
    for tid in ids[:2]:
        await client.patch(
            f"/api/v1/tasks/{tid}", json={"percent_complete": 100}, headers=headers
        )

    # No status history yet -> can't forecast, but the backlog is known.
    f0 = (await client.get(f"/api/v1/projects/{project_id}/forecast", headers=headers)).json()
    assert f0["sufficient"] is False
    assert f0["remaining_items"] == 2
    assert f0["p50_date"] is None

    # Seed a completion in each of the last 4 weeks so a throughput trend exists.
    today = date.today()
    for i in range(4):
        day = today - timedelta(weeks=i + 1)
        db_session.add(
            TaskStatusHistory(
                task_id=ids[0],
                to_status="done",
                changed_at=datetime.combine(day, datetime.min.time()),
            )
        )
    await db_session.commit()

    f1 = (await client.get(f"/api/v1/projects/{project_id}/forecast", headers=headers)).json()
    assert f1["scope"] == "project"
    assert f1["sufficient"] is True
    assert f1["remaining_items"] == 2
    assert f1["p50_weeks"] is not None
    assert f1["p85_weeks"] >= f1["p50_weeks"]
    assert f1["p50_date"] is not None
