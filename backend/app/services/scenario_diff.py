"""Scenario-vs-live diff (pure, unit-testable).

Counts what a scenario changes relative to the rows it was snapshotted from (via the
`live_*_id` provenance + `removed` tombstone) and assembles the schedule deltas the endpoint
precomputes (live ends from the persisted plan, scenario ends from the scenario CPM)."""

from __future__ import annotations

from app.models.project import Milestone, Task
from app.models.scenario import (
    ScenarioAllocation,
    ScenarioAvailability,
    ScenarioDependency,
    ScenarioMilestone,
    ScenarioTask,
)
from app.models.team import Allocation, EngineerAvailability
from app.schemas.scenarios import ScenarioDiffRead, ScenarioProjectDelta


def _task_changed(s: ScenarioTask, live: Task) -> bool:
    return bool(
        s.name != live.name
        or s.description != live.description
        or s.type != live.type
        or s.duration != live.duration
        or s.deadline != live.deadline
        or s.percent_complete != live.percent_complete
        or s.assignee_engineer_id != live.assignee_engineer_id
    )


def _milestone_changed(s: ScenarioMilestone, live: Milestone) -> bool:
    return bool(
        s.name != live.name
        or s.description != live.description
        or s.target_date != live.target_date
        or s.status != live.status
    )


def _allocation_changed(s: ScenarioAllocation, live: Allocation) -> bool:
    return bool(
        s.engineer_id != live.engineer_id
        or s.project_id != live.project_id
        or s.percent_allocation != live.percent_allocation
        or s.capacity_hours_per_week != live.capacity_hours_per_week
        or s.start_date != live.start_date
        or s.end_date != live.end_date
    )


def _availability_changed(s: ScenarioAvailability, live: EngineerAvailability) -> bool:
    return bool(
        s.engineer_id != live.engineer_id
        or s.start_date != live.start_date
        or s.end_date != live.end_date
        or s.capacity_factor != live.capacity_factor
        or s.note != live.note
    )


def compute_scenario_diff(
    *,
    scenario_tasks: list[ScenarioTask],
    scenario_deps: list[ScenarioDependency],
    scenario_milestones: list[ScenarioMilestone],
    scenario_allocations: list[ScenarioAllocation],
    scenario_availability: list[ScenarioAvailability],
    live_tasks: dict[int, Task],
    live_milestones: dict[int, Milestone],
    live_allocations: dict[int, Allocation],
    live_availability: dict[int, EngineerAvailability],
    project_ends: list[ScenarioProjectDelta],
    live_cp_working_days: int,
    scenario_cp_working_days: int,
) -> ScenarioDiffRead:
    tasks_added = sum(1 for t in scenario_tasks if t.live_task_id is None and not t.removed)
    tasks_removed = sum(1 for t in scenario_tasks if t.removed and t.live_task_id is not None)
    tasks_changed = sum(
        1
        for t in scenario_tasks
        if not t.removed
        and t.live_task_id is not None
        and t.live_task_id in live_tasks
        and _task_changed(t, live_tasks[t.live_task_id])
    )

    deps_added = sum(1 for d in scenario_deps if d.live_dep_id is None and not d.removed)
    deps_removed = sum(1 for d in scenario_deps if d.removed and d.live_dep_id is not None)

    milestones_changed = sum(
        1
        for s in scenario_milestones
        if (s.live_milestone_id is None and not s.removed)
        or (s.removed and s.live_milestone_id is not None)
        or (
            not s.removed
            and s.live_milestone_id in live_milestones
            and _milestone_changed(s, live_milestones[s.live_milestone_id])
        )
    )
    allocations_changed = sum(
        1
        for s in scenario_allocations
        if (s.live_allocation_id is None and not s.removed)
        or (s.removed and s.live_allocation_id is not None)
        or (
            not s.removed
            and s.live_allocation_id in live_allocations
            and _allocation_changed(s, live_allocations[s.live_allocation_id])
        )
    )
    availability_changed = sum(
        1
        for s in scenario_availability
        if (s.live_availability_id is None and not s.removed)
        or (s.removed and s.live_availability_id is not None)
        or (
            not s.removed
            and s.live_availability_id in live_availability
            and _availability_changed(s, live_availability[s.live_availability_id])
        )
    )

    live_ends = [p.live_end for p in project_ends if p.live_end]
    scenario_ends = [p.scenario_end for p in project_ends if p.scenario_end]
    live_end = max(live_ends) if live_ends else None
    scenario_end = max(scenario_ends) if scenario_ends else None
    end_delta = (scenario_end - live_end).days if (live_end and scenario_end) else None

    return ScenarioDiffRead(
        tasks_added=tasks_added,
        tasks_removed=tasks_removed,
        tasks_changed=tasks_changed,
        deps_added=deps_added,
        deps_removed=deps_removed,
        milestones_changed=milestones_changed,
        allocations_changed=allocations_changed,
        availability_changed=availability_changed,
        live_project_end=live_end,
        scenario_project_end=scenario_end,
        end_delta_days=end_delta,
        live_cp_working_days=live_cp_working_days,
        scenario_cp_working_days=scenario_cp_working_days,
        cp_delta_days=scenario_cp_working_days - live_cp_working_days,
        per_project=project_ends,
    )
