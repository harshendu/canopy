"""FK-safe delete regression tests (BUG-01).

Postgres/MySQL enforce foreign keys; a bare ``session.delete()`` on a non-empty project/task
500s there while silently orphaning on default SQLite. These tests run the cascade helpers under
a SQLite engine with ``PRAGMA foreign_keys=ON`` — which reproduces the production behaviour — over
the *fully-populated* demo dataset, so a referencing table missed by the cascade fails loudly with
an IntegrityError instead of passing on lax SQLite.
"""

import pytest
import pytest_asyncio
from sqlalchemy import event, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, col, select

import app.models  # noqa: F401 — register every table on SQLModel.metadata
from app.models.project import Dependency, Project, Task, TaskStatusHistory
from app.models.scenario import ScenarioProject, ScenarioTask
from app.services import seed
from app.services.cascade import delete_project_cascade, delete_task_cascade


@pytest_asyncio.fixture
async def fk_session() -> AsyncSession:
    """A SQLite session with foreign-key enforcement ON (mirrors Postgres/MySQL)."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _enforce_fks(dbapi_conn, _record) -> None:
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


async def _count(session: AsyncSession, model: type, *where) -> int:
    stmt = select(func.count()).select_from(model)
    for clause in where:
        stmt = stmt.where(clause)
    return (await session.execute(stmt)).scalar_one()


@pytest.mark.asyncio
async def test_delete_project_cascade_is_fk_safe(fk_session: AsyncSession) -> None:
    await seed.load_seed_data(fk_session, set())
    # Pick the richest project (most tasks) — one inside an initiative that has a scenario, so the
    # scenario-references-live-project FKs are exercised too.
    rows = (
        await fk_session.execute(
            select(Task.project_id, func.count()).group_by(col(Task.project_id))
        )
    ).all()
    pid = max(rows, key=lambda r: r[1])[0]
    assert await _count(fk_session, Task, col(Task.project_id) == pid) > 0
    # Sanity: this project is snapshotted by at least one scenario.
    assert await _count(fk_session, ScenarioTask, col(ScenarioTask.project_id) == pid) > 0

    # Under FK enforcement an omitted referencing table raises IntegrityError here.
    await delete_project_cascade(fk_session, pid)
    await fk_session.commit()

    assert await fk_session.get(Project, pid) is None
    assert await _count(fk_session, Task, col(Task.project_id) == pid) == 0
    assert await _count(fk_session, ScenarioTask, col(ScenarioTask.project_id) == pid) == 0
    assert await _count(fk_session, ScenarioProject, col(ScenarioProject.project_id) == pid) == 0
    # Other projects survive untouched.
    assert await _count(fk_session, Project) > 0


@pytest.mark.asyncio
async def test_delete_task_cascade_promotes_children_and_clears_refs(
    fk_session: AsyncSession,
) -> None:
    await seed.load_seed_data(fk_session, set())
    # A summary task with children (WBS parent) — deleting it must not dangle the children.
    parent = (
        await fk_session.execute(
            select(Task).where(col(Task.parent_id).is_(None), col(Task.type) == "summary")
        )
    ).scalars().first()
    assert parent is not None and parent.id is not None
    grandparent = parent.parent_id  # None (top-level phase)
    child_ids = [
        t.id
        for t in (
            await fk_session.execute(select(Task).where(col(Task.parent_id) == parent.id))
        ).scalars().all()
    ]

    await delete_task_cascade(fk_session, parent.id)
    await fk_session.commit()

    assert await fk_session.get(Task, parent.id) is None
    # Children survived and were promoted to the deleted task's parent.
    for cid in child_ids:
        child = await fk_session.get(Task, cid)
        assert child is not None
        assert child.parent_id == grandparent
    # No dependency or status-history row still references the deleted task.
    assert (
        await _count(
            fk_session,
            Dependency,
            (col(Dependency.predecessor_id) == parent.id)
            | (col(Dependency.successor_id) == parent.id),
        )
        == 0
    )
    assert (
        await _count(fk_session, TaskStatusHistory, col(TaskStatusHistory.task_id) == parent.id)
        == 0
    )
