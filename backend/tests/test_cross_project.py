import pytest

from app.services.cross_project import CPDep, CPTask, cross_project_critical_path
from app.services.scheduling import CycleError


def test_cross_project_critical_path_spans_projects():
    # Chain: A1(3) -> A2(2) -> [hand-off] -> B1(5) -> B2(1) = 11 working days.
    # B0 in project 2 is parallel and short, so it carries float and is not critical.
    tasks = [
        CPTask(id=1, project_id=1, duration=3),
        CPTask(id=2, project_id=1, duration=2),
        CPTask(id=3, project_id=2, duration=5),
        CPTask(id=4, project_id=2, duration=1),
        CPTask(id=5, project_id=2, duration=1),
    ]
    deps = [
        CPDep(1, 2, "FS"),
        CPDep(2, 3, "FS"),  # the cross-project hand-off
        CPDep(3, 4, "FS"),
    ]
    cp = cross_project_critical_path(tasks, deps)

    assert cp.total_working_days == 11
    assert [n.task_id for n in cp.nodes] == [1, 2, 3, 4]  # earliest-first; #5 not critical
    assert cp.spans_projects is True
    assert len(cp.handoffs) == 1
    h = cp.handoffs[0]
    assert (h.predecessor_id, h.successor_id) == (2, 3)
    assert (h.from_project_id, h.to_project_id) == (1, 2)


def test_single_project_critical_path_does_not_span():
    tasks = [CPTask(id=1, project_id=7, duration=2), CPTask(id=2, project_id=7, duration=2)]
    cp = cross_project_critical_path(tasks, [CPDep(1, 2, "FS")])
    assert cp.spans_projects is False
    assert cp.handoffs == []
    assert cp.total_working_days == 4


def test_cross_project_cycle_raises():
    tasks = [CPTask(id=1, project_id=1, duration=1), CPTask(id=2, project_id=2, duration=1)]
    deps = [CPDep(1, 2, "FS"), CPDep(2, 1, "FS")]
    with pytest.raises(CycleError):
        cross_project_critical_path(tasks, deps)
