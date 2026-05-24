from datetime import date

from app.models.base import TaskType
from app.models.project import Task
from app.models.scenario import ScenarioDependency, ScenarioTask
from app.schemas.scenarios import ScenarioProjectDelta
from app.services.scenario_diff import compute_scenario_diff


def test_compute_scenario_diff_counts_by_provenance():
    live_tasks = {
        1: Task(id=1, project_id=1, name="A", duration=3),
        2: Task(id=2, project_id=1, name="B", duration=2),
        3: Task(id=3, project_id=1, name="C", duration=5),
    }
    scenario_tasks = [
        ScenarioTask(scenario_id=1, project_id=1, live_task_id=1, name="A", duration=3),  # same
        ScenarioTask(scenario_id=1, project_id=1, live_task_id=2, name="B", duration=8),  # changed
        ScenarioTask(scenario_id=1, project_id=1, live_task_id=3, name="C", duration=5,
                     removed=True),  # removed
        ScenarioTask(scenario_id=1, project_id=1, live_task_id=None, name="New", duration=1),  # add
    ]
    scenario_deps = [
        ScenarioDependency(scenario_id=1, predecessor_id=10, successor_id=11),  # added
        ScenarioDependency(scenario_id=1, predecessor_id=12, successor_id=13, live_dep_id=99,
                           removed=True),  # removed
    ]
    project_ends = [
        ScenarioProjectDelta(
            project_id=1, project_key="P1",
            live_end=date(2026, 1, 10), scenario_end=date(2026, 1, 17), end_delta_days=7,
        )
    ]

    diff = compute_scenario_diff(
        scenario_tasks=scenario_tasks,
        scenario_deps=scenario_deps,
        scenario_milestones=[],
        scenario_allocations=[],
        scenario_availability=[],
        live_tasks=live_tasks,
        live_milestones={},
        live_allocations={},
        live_availability={},
        project_ends=project_ends,
        live_cp_working_days=10,
        scenario_cp_working_days=17,
    )

    assert diff.tasks_added == 1
    assert diff.tasks_removed == 1
    assert diff.tasks_changed == 1
    assert diff.deps_added == 1
    assert diff.deps_removed == 1
    assert diff.live_project_end == date(2026, 1, 10)
    assert diff.scenario_project_end == date(2026, 1, 17)
    assert diff.end_delta_days == 7
    assert diff.cp_delta_days == 7
    assert diff.per_project[0].project_key == "P1"


def test_compute_scenario_diff_no_changes_is_zero():
    live_tasks = {1: Task(id=1, project_id=1, name="A", duration=3, type=TaskType.task)}
    scenario_tasks = [
        ScenarioTask(scenario_id=1, project_id=1, live_task_id=1, name="A", duration=3,
                     type=TaskType.task)
    ]
    diff = compute_scenario_diff(
        scenario_tasks=scenario_tasks,
        scenario_deps=[],
        scenario_milestones=[],
        scenario_allocations=[],
        scenario_availability=[],
        live_tasks=live_tasks,
        live_milestones={},
        live_allocations={},
        live_availability={},
        project_ends=[],
        live_cp_working_days=0,
        scenario_cp_working_days=0,
    )
    assert (diff.tasks_added, diff.tasks_removed, diff.tasks_changed) == (0, 0, 0)
    assert diff.end_delta_days is None
    assert diff.cp_delta_days == 0
