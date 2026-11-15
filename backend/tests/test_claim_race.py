"""Many sessions claiming at once (docs/AGENT_EXECUTION.md §6.3, §22): exactly one wins each
task, losers leave nothing behind, and no task ever holds two live claims.

The compare-and-swap must hold on every supported dialect, so this test is written for real
concurrency — separate connections racing — and CI runs it against PostgreSQL, MySQL and
MariaDB (`CANOPY_TEST_DATABASE_URL`, see `conftest.py`). Without that variable it races on a
file-backed SQLite database, where the losers mostly fail on the database lock instead.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlmodel import SQLModel, col, select

import app.models  # noqa: F401 — register every table
from app.models.agent_token import AgentTokenRecord
from app.models.base import UserRole, utcnow
from app.models.project import Project, Task
from app.models.team import Engineer
from app.models.user import User
from app.models.work import WorkClaim
from app.services import work_service
from app.services.workflow import initialise_native_task
from tests.conftest import IS_SQLITE, test_engine

CONTENDERS = 6


@pytest_asyncio.fixture
async def race_engine(tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    """Separate connections per session: the suite's engine on a server database (its schema
    is created per test by conftest), else a SQLite file with a busy timeout."""
    if not IS_SQLITE:
        yield test_engine
        return
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'race.db'}",
                                 connect_args={"timeout": 15})
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield engine
    await engine.dispose()


async def _setup(maker: async_sessionmaker[AsyncSession], tasks: int) -> tuple[
    int, int, list[int], list[int]
]:
    async with maker() as session:
        user = User(email="racer@example.com", hashed_password="x", role=UserRole.architect)
        project = Project(key="RACE", name="Race", agent_intake="on")
        session.add_all([user, project])
        await session.flush()
        assert user.id is not None and project.id is not None
        engineer = Engineer(name="Racer", user_id=user.id)
        session.add(engineer)
        tokens = [
            AgentTokenRecord(user_id=user.id, jti=f"race-{i}", label=f"racer {i}",
                             expires_at=utcnow().replace(year=utcnow().year + 1))
            for i in range(CONTENDERS)
        ]
        session.add_all(tokens)
        task_ids: list[int] = []
        for n in range(tasks):
            task = Task(project_id=project.id, name=f"task {n}", delegation="agent")
            session.add(task)
            await session.flush()
            await initialise_native_task(session, task, status="To Do", native_enabled=True,
                                         author="setup")
            assert task.id is not None
            task_ids.append(task.id)
        await session.flush()
        assert engineer.id is not None
        token_ids = [t.id for t in tokens if t.id is not None]
        await session.commit()
        return user.id, engineer.id, token_ids, task_ids


async def _contend(
    maker: async_sessionmaker[AsyncSession], user_id: int, engineer_id: int, token_id: int,
    start: asyncio.Event, task_id: int | None,
) -> int | None:
    async with maker() as session:
        user = await session.get(User, user_id)
        token = await session.get(AgentTokenRecord, token_id)
        assert user is not None and token is not None
        caller = work_service.Caller(user=user, token=token, is_agent=True,
                                     engineer_id=engineer_id)
        await start.wait()
        try:
            claim = await work_service.claim_work(session, caller, "implementer",
                                                  task_id=task_id)
            await session.commit()
        except work_service.WorkError as exc:
            await session.rollback()
            assert exc.code == "already_claimed", exc.detail()
            return None
        except DBAPIError:
            # Lost at the database (a lock it gave up waiting for): nothing was kept.
            await session.rollback()
            return None
        return claim.id if claim is not None else None


async def _race(maker: async_sessionmaker[AsyncSession], task_id: int | None,
                user_id: int, engineer_id: int, token_ids: list[int]) -> list[int]:
    start = asyncio.Event()
    racers = [
        asyncio.create_task(_contend(maker, user_id, engineer_id, token_id, start, task_id))
        for token_id in token_ids
    ]
    await asyncio.sleep(0.05)
    start.set()
    return [r for r in await asyncio.gather(*racers) if r is not None]


@pytest.mark.asyncio
async def test_concurrent_claims_on_one_task_have_one_winner(race_engine: AsyncEngine) -> None:
    maker = async_sessionmaker(race_engine, class_=AsyncSession, expire_on_commit=False)
    user_id, engineer_id, token_ids, (task_id,) = await _setup(maker, tasks=1)

    winners = await _race(maker, task_id, user_id, engineer_id, token_ids)

    assert len(winners) == 1, winners
    async with maker() as session:
        task = await session.get(Task, task_id)
        assert task is not None and task.active_claim_id == winners[0]
        rows = (await session.execute(
            select(WorkClaim).where(WorkClaim.task_id == task_id)
        )).scalars().all()
        # Losers reserved nothing and inserted nothing.
        assert [(r.id, r.state) for r in rows] == [(winners[0], "active")]
        assert task.status == "In Progress"  # pulled exactly once


@pytest.mark.asyncio
async def test_concurrent_next_ready_claims_never_double_book(
    race_engine: AsyncEngine,
) -> None:
    maker = async_sessionmaker(race_engine, class_=AsyncSession, expire_on_commit=False)
    user_id, engineer_id, token_ids, task_ids = await _setup(maker, tasks=3)

    winners = await _race(maker, None, user_id, engineer_id, token_ids)

    async with maker() as session:
        claims = (await session.execute(
            select(WorkClaim).where(col(WorkClaim.task_id).in_(task_ids))
        )).scalars().all()
        assert sorted(c.id for c in claims if c.id is not None) == sorted(winners)
        claimed = [c.task_id for c in claims]
        assert len(claimed) == len(set(claimed)), "a task was claimed twice"
        for task_id in task_ids:
            task = await session.get(Task, task_id)
            assert task is not None
            mine = [c.id for c in claims if c.task_id == task_id]
            assert task.active_claim_id == (mine[0] if mine else None)
    if not IS_SQLITE:
        # A server database serialises the losers instead of failing them: every task is
        # taken, by a different session.
        assert len(winners) == len(task_ids)
    else:
        assert winners
