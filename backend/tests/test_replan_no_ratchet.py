"""BUG-05 regression: a replan must not reuse last run's computed start as this run's pin.

Before the fix, `reschedule_project` pinned every task at its previously-computed `start`, so the
schedule could only ever slip *later* — removing a dependency (or cutting a duration in what-if)
could never pull a successor earlier. Now the pin comes only from an explicit `constraint_start`.
"""

from datetime import date

import pytest

from app.models.project import Dependency, Project, Task
from app.services.planner import reschedule_project


@pytest.mark.asyncio
async def test_removing_a_dependency_pulls_the_successor_earlier(db_session) -> None:
    project = Project(key="RATCHET", name="R", start_date=date(2026, 1, 1), skip_weekends=False)
    db_session.add(project)
    await db_session.flush()
    a = Task(project_id=project.id, name="A", duration=3)
    b = Task(project_id=project.id, name="B", duration=3)
    db_session.add_all([a, b])
    await db_session.flush()
    dep = Dependency(predecessor_id=a.id, successor_id=b.id)
    db_session.add(dep)
    await db_session.commit()

    # First replan: B follows A (A finishes 2026-01-04, B starts there under FS).
    await reschedule_project(db_session, project.id)
    await db_session.refresh(b)
    b_start_linked = b.start
    assert b_start_linked is not None and b_start_linked > project.start_date

    # Remove the dependency and replan again. B is now free and MUST pull back to the project start
    # — under the old ratchet it would have stayed pinned at b_start_linked.
    await db_session.delete(dep)
    await db_session.commit()
    await reschedule_project(db_session, project.id)
    await db_session.refresh(b)
    assert b.start == project.start_date


@pytest.mark.asyncio
async def test_constraint_start_still_pins_a_task(db_session) -> None:
    project = Project(key="SNET", name="S", start_date=date(2026, 1, 1), skip_weekends=False)
    db_session.add(project)
    await db_session.flush()
    # An explicit "start no earlier than" constraint is honored (this is the legit pin).
    t = Task(project_id=project.id, name="T", duration=2, constraint_start=date(2026, 1, 10))
    db_session.add(t)
    await db_session.commit()

    await reschedule_project(db_session, project.id)
    await db_session.refresh(t)
    assert t.start == date(2026, 1, 10)  # pinned by the constraint, not the project start
