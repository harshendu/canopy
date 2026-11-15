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


async def _agent_work(session: AsyncSession) -> tuple[int, int, int]:
    """A project with intake on and two delegated tasks carrying every kind of agent-work row:
    a claim, plan and note artifacts, a question gate, work events and component links."""
    from app.models.architecture import ArchitectureComponent
    from app.models.base import ArtifactKind, GateKind, UserRole
    from app.models.team import Engineer
    from app.models.user import User
    from app.services import work_service
    from app.services.workflow import initialise_native_task

    user = User(email="worker@example.com", hashed_password="x", role=UserRole.architect)
    project = Project(key="AGW", name="Agent work", agent_intake="on")
    session.add_all([user, project])
    await session.flush()
    assert project.id is not None
    engineer = Engineer(name="Worker", user_id=user.id)
    component = ArchitectureComponent(project_id=project.id, name="API")
    session.add_all([engineer, component])
    await session.flush()
    assert component.id is not None
    caller = work_service.Caller(user=user, engineer_id=engineer.id)
    task_ids: list[int] = []
    for name in ("first", "second"):
        task = Task(project_id=project.id, name=name, delegation="agent")
        session.add(task)
        await session.flush()
        await initialise_native_task(session, task, status="To Do", native_enabled=True,
                                     author="test")
        await work_service.set_components(session, task, [component.id], caller)
        claim = await work_service.claim_work(session, caller, "implementer", task_id=task.id)
        assert claim is not None
        await work_service.submit_plan(session, claim, caller, body="plan",
                                       data={"approach": "plan", "affected_paths": []})
        await work_service.add_artifact(session, task, ArtifactKind.note, body="note",
                                        caller=caller)
        await work_service.ask_human(session, claim, caller, kind=GateKind.question,
                                     title="Q?", prompt="Which one?")
        assert task.id is not None
        task_ids.append(task.id)
    await work_service.set_intake(session, project, caller, "paused")  # a project-level event
    await session.commit()
    return project.id, task_ids[0], task_ids[1]


@pytest.mark.asyncio
async def test_cascades_clear_agent_work(fk_session: AsyncSession) -> None:
    from app.models.architecture import TaskComponentLink
    from app.models.gate import Gate
    from app.models.work import TaskArtifact, WorkClaim, WorkEvent

    pid, first, second = await _agent_work(fk_session)
    assert await _count(fk_session, Gate, col(Gate.task_id) == first) == 1

    # One task: its claims, artifacts, gates, events and component links go with it.
    await delete_task_cascade(fk_session, first)
    await fk_session.commit()
    for model, column in ((WorkClaim, WorkClaim.task_id), (TaskArtifact, TaskArtifact.task_id),
                          (Gate, Gate.task_id), (WorkEvent, WorkEvent.task_id),
                          (TaskComponentLink, TaskComponentLink.task_id)):
        assert await _count(fk_session, model, col(column) == first) == 0, model
    assert await _count(fk_session, WorkClaim, col(WorkClaim.task_id) == second) == 1

    # The project: everything, including project-level events (intake changes).
    await delete_project_cascade(fk_session, pid)
    await fk_session.commit()
    assert await fk_session.get(Project, pid) is None
    assert await _count(fk_session, WorkEvent, col(WorkEvent.project_id) == pid) == 0
    assert await _count(fk_session, Gate, col(Gate.project_id) == pid) == 0
    assert await _count(fk_session, WorkClaim) == 0 and await _count(fk_session, TaskArtifact) == 0
