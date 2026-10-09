"""Scenario simulation API: a durable, named, initiative-scoped what-if workspace.

Creating a scenario snapshots the initiative's planning data; the entity-edit endpoints mutate
the snapshot freely; the view endpoints recompute every analysis (reusing the live response
schemas) over the snapshot; `compare` diffs it against live; `apply` writes it back to canopy's
planning layer (never Jira) and replans. All writes are planner-gated; reads are open.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.api.deps import CurrentUser, HumanOnly, PlannerWriter, SessionDep
from app.models.base import TaskType
from app.models.project import Dependency, Initiative, Milestone, Task
from app.models.scenario import (
    Scenario,
    ScenarioAllocation,
    ScenarioAvailability,
    ScenarioDependency,
    ScenarioMilestone,
    ScenarioProject,
    ScenarioTask,
)
from app.models.team import Allocation, EngineerAvailability
from app.schemas.entities import (
    AlertsResponse,
    BoardResponse,
    BurndownResponse,
    CapacityResponse,
    ForecastResponse,
    GanttResponse,
    InitiativeCriticalPath,
)
from app.schemas.scenarios import (
    ScenarioAllocationCreate,
    ScenarioAllocationRead,
    ScenarioAllocationUpdate,
    ScenarioApplyRequest,
    ScenarioApplyResult,
    ScenarioAvailabilityCreate,
    ScenarioAvailabilityRead,
    ScenarioAvailabilityUpdate,
    ScenarioCompareResponse,
    ScenarioCounts,
    ScenarioCreate,
    ScenarioDependencyCreate,
    ScenarioDependencyRead,
    ScenarioDetail,
    ScenarioMilestoneCreate,
    ScenarioMilestoneRead,
    ScenarioMilestoneUpdate,
    ScenarioProjectDelta,
    ScenarioProjectRead,
    ScenarioProjectUpdate,
    ScenarioRead,
    ScenarioTaskCreate,
    ScenarioTaskRead,
    ScenarioTaskUpdate,
    ScenarioUpdate,
)
from app.services.access import ensure_initiative_editable
from app.services.cross_project import CPDep, CPTask, cross_project_critical_path
from app.services.scenario_apply import (
    ScenarioApplyError,
    ScenarioConflictError,
    apply_scenario,
    detect_conflicts,
)
from app.services.scenario_diff import compute_scenario_diff
from app.services.scenario_engine import (
    MaterializedScenario,
    materialize,
    scenario_alerts,
    scenario_board,
    scenario_burndown,
    scenario_capacity,
    scenario_critical_path,
    scenario_forecast,
    scenario_gantt,
    snapshot_live_into_scenario,
)
from app.services.scheduling import CycleError

router = APIRouter()


async def _get_scenario(session: AsyncSession, scenario_id: int) -> Scenario:
    scenario = await session.get(Scenario, scenario_id)
    if scenario is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scenario not found")
    return scenario


async def _editable(session: AsyncSession, scenario_id: int) -> Scenario:
    scenario = await _get_scenario(session, scenario_id)
    if scenario.status in ("applied", "archived"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Scenario is {scenario.status} and can no longer be edited",
        )
    return scenario


# --- Lifecycle ---
@router.get("/initiatives/{initiative_id}/scenarios", response_model=list[ScenarioRead])
async def list_scenarios(
    session: SessionDep, _: CurrentUser, initiative_id: int
) -> list[Scenario]:
    rows = await session.execute(
        select(Scenario)
        .where(Scenario.initiative_id == initiative_id)
        .order_by(col(Scenario.id).desc())
    )
    return list(rows.scalars().all())


@router.post(
    "/initiatives/{initiative_id}/scenarios",
    response_model=ScenarioRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_scenario(
    session: SessionDep, user: PlannerWriter, initiative_id: int, payload: ScenarioCreate
) -> Scenario:
    if await session.get(Initiative, initiative_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Initiative not found")
    await ensure_initiative_editable(session, user, initiative_id)
    scenario = Scenario(
        initiative_id=initiative_id, title=payload.title, description=payload.description
    )
    session.add(scenario)
    await session.flush()
    await snapshot_live_into_scenario(session, scenario)
    await session.commit()
    await session.refresh(scenario)
    return scenario


async def _active_count(session: AsyncSession, model: type, scenario_id: int) -> int:
    rows: list[object] = list(
        (
            await session.execute(
                select(model).where(col(model.scenario_id) == scenario_id)  # type: ignore[attr-defined]
            )
        ).scalars().all()
    )
    return sum(1 for r in rows if not getattr(r, "removed", False))


async def _counts(session: AsyncSession, scenario_id: int) -> ScenarioCounts:
    return ScenarioCounts(
        tasks=await _active_count(session, ScenarioTask, scenario_id),
        dependencies=await _active_count(session, ScenarioDependency, scenario_id),
        milestones=await _active_count(session, ScenarioMilestone, scenario_id),
        allocations=await _active_count(session, ScenarioAllocation, scenario_id),
        availability=await _active_count(session, ScenarioAvailability, scenario_id),
        projects=await _active_count(session, ScenarioProject, scenario_id),
    )


@router.get("/scenarios/{scenario_id}", response_model=ScenarioDetail)
async def get_scenario(session: SessionDep, _: CurrentUser, scenario_id: int) -> ScenarioDetail:
    scenario = await _get_scenario(session, scenario_id)
    counts = await _counts(session, scenario_id)
    return ScenarioDetail(
        **ScenarioRead.model_validate(scenario).model_dump(), counts=counts
    )


@router.patch("/scenarios/{scenario_id}", response_model=ScenarioRead)
async def update_scenario(
    session: SessionDep, user: PlannerWriter, scenario_id: int, payload: ScenarioUpdate
) -> Scenario:
    scenario = await _get_scenario(session, scenario_id)
    await ensure_initiative_editable(session, user, scenario.initiative_id)
    data = payload.model_dump(exclude_unset=True)
    if "status" in data and data["status"] not in ("draft", "ready", "archived"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid status")
    for field, value in data.items():
        setattr(scenario, field, value)
    await session.commit()
    await session.refresh(scenario)
    return scenario


@router.delete("/scenarios/{scenario_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_scenario(session: SessionDep, user: PlannerWriter, scenario_id: int) -> None:
    scenario = await session.get(Scenario, scenario_id)
    if scenario is None:
        return
    await ensure_initiative_editable(session, user, scenario.initiative_id)
    for model in (
        ScenarioTask,
        ScenarioDependency,
        ScenarioMilestone,
        ScenarioAllocation,
        ScenarioAvailability,
        ScenarioProject,
    ):
        rows = await session.execute(
            select(model).where(col(model.scenario_id) == scenario_id)
        )
        for row in rows.scalars().all():
            await session.delete(row)
    await session.delete(scenario)
    await session.commit()


# --- Project knobs ---
@router.patch("/scenarios/{scenario_id}/projects/{project_id}", response_model=ScenarioProjectRead)
async def update_scenario_project(
    session: SessionDep,
    _: PlannerWriter,
    scenario_id: int,
    project_id: int,
    payload: ScenarioProjectUpdate,
) -> ScenarioProject:
    await _editable(session, scenario_id)
    row = (
        await session.execute(
            select(ScenarioProject).where(
                ScenarioProject.scenario_id == scenario_id,
                ScenarioProject.project_id == project_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Scenario project not found"
        )
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    await session.commit()
    await session.refresh(row)
    return row


# --- Tasks ---
@router.post("/scenarios/{scenario_id}/tasks", response_model=ScenarioTaskRead,
             status_code=status.HTTP_201_CREATED)
async def add_scenario_task(
    session: SessionDep, _: PlannerWriter, scenario_id: int, payload: ScenarioTaskCreate
) -> ScenarioTask:
    await _editable(session, scenario_id)
    task = ScenarioTask(scenario_id=scenario_id, **payload.model_dump())
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


@router.patch("/scenario-tasks/{task_id}", response_model=ScenarioTaskRead)
async def update_scenario_task(
    session: SessionDep, _: PlannerWriter, task_id: int, payload: ScenarioTaskUpdate
) -> ScenarioTask:
    task = await session.get(ScenarioTask, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scenario task not found")
    await _editable(session, task.scenario_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(task, field, value)
    await session.commit()
    await session.refresh(task)
    return task


@router.delete("/scenario-tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_scenario_task(session: SessionDep, _: PlannerWriter, task_id: int) -> None:
    task = await session.get(ScenarioTask, task_id)
    if task is None:
        return
    await _editable(session, task.scenario_id)
    if task.live_task_id is not None:
        task.removed = True  # tombstone so apply deletes the live task
    else:
        await session.delete(task)  # added-in-scenario: hard delete
    await session.commit()


# --- Dependencies ---
@router.post("/scenarios/{scenario_id}/dependencies", response_model=ScenarioDependencyRead,
             status_code=status.HTTP_201_CREATED)
async def add_scenario_dependency(
    session: SessionDep, _: PlannerWriter, scenario_id: int, payload: ScenarioDependencyCreate
) -> ScenarioDependency:
    await _editable(session, scenario_id)
    dep = ScenarioDependency(scenario_id=scenario_id, **payload.model_dump())
    session.add(dep)
    await session.commit()
    await session.refresh(dep)
    return dep


@router.delete("/scenario-dependencies/{dep_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_scenario_dependency(session: SessionDep, _: PlannerWriter, dep_id: int) -> None:
    dep = await session.get(ScenarioDependency, dep_id)
    if dep is None:
        return
    await _editable(session, dep.scenario_id)
    if dep.live_dep_id is not None:
        dep.removed = True
    else:
        await session.delete(dep)
    await session.commit()


# --- Milestones ---
@router.post("/scenarios/{scenario_id}/milestones", response_model=ScenarioMilestoneRead,
             status_code=status.HTTP_201_CREATED)
async def add_scenario_milestone(
    session: SessionDep, _: PlannerWriter, scenario_id: int, payload: ScenarioMilestoneCreate
) -> ScenarioMilestone:
    await _editable(session, scenario_id)
    milestone = ScenarioMilestone(scenario_id=scenario_id, **payload.model_dump())
    session.add(milestone)
    await session.commit()
    await session.refresh(milestone)
    return milestone


@router.patch("/scenario-milestones/{milestone_id}", response_model=ScenarioMilestoneRead)
async def update_scenario_milestone(
    session: SessionDep, _: PlannerWriter, milestone_id: int, payload: ScenarioMilestoneUpdate
) -> ScenarioMilestone:
    milestone = await session.get(ScenarioMilestone, milestone_id)
    if milestone is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Milestone not found")
    await _editable(session, milestone.scenario_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(milestone, field, value)
    await session.commit()
    await session.refresh(milestone)
    return milestone


@router.delete("/scenario-milestones/{milestone_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_scenario_milestone(
    session: SessionDep, _: PlannerWriter, milestone_id: int
) -> None:
    milestone = await session.get(ScenarioMilestone, milestone_id)
    if milestone is None:
        return
    await _editable(session, milestone.scenario_id)
    if milestone.live_milestone_id is not None:
        milestone.removed = True
    else:
        await session.delete(milestone)
    await session.commit()


# --- Allocations ---
@router.post("/scenarios/{scenario_id}/allocations", response_model=ScenarioAllocationRead,
             status_code=status.HTTP_201_CREATED)
async def add_scenario_allocation(
    session: SessionDep, _: PlannerWriter, scenario_id: int, payload: ScenarioAllocationCreate
) -> ScenarioAllocation:
    await _editable(session, scenario_id)
    alloc = ScenarioAllocation(scenario_id=scenario_id, **payload.model_dump())
    session.add(alloc)
    await session.commit()
    await session.refresh(alloc)
    return alloc


@router.patch("/scenario-allocations/{allocation_id}", response_model=ScenarioAllocationRead)
async def update_scenario_allocation(
    session: SessionDep, _: PlannerWriter, allocation_id: int, payload: ScenarioAllocationUpdate
) -> ScenarioAllocation:
    alloc = await session.get(ScenarioAllocation, allocation_id)
    if alloc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Allocation not found")
    await _editable(session, alloc.scenario_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(alloc, field, value)
    await session.commit()
    await session.refresh(alloc)
    return alloc


@router.delete("/scenario-allocations/{allocation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_scenario_allocation(
    session: SessionDep, _: PlannerWriter, allocation_id: int
) -> None:
    alloc = await session.get(ScenarioAllocation, allocation_id)
    if alloc is None:
        return
    await _editable(session, alloc.scenario_id)
    if alloc.live_allocation_id is not None:
        alloc.removed = True
    else:
        await session.delete(alloc)
    await session.commit()


# --- Availability ---
@router.post("/scenarios/{scenario_id}/availability", response_model=ScenarioAvailabilityRead,
             status_code=status.HTTP_201_CREATED)
async def add_scenario_availability(
    session: SessionDep, _: PlannerWriter, scenario_id: int, payload: ScenarioAvailabilityCreate
) -> ScenarioAvailability:
    await _editable(session, scenario_id)
    av = ScenarioAvailability(scenario_id=scenario_id, **payload.model_dump())
    session.add(av)
    await session.commit()
    await session.refresh(av)
    return av


@router.patch("/scenario-availability/{availability_id}", response_model=ScenarioAvailabilityRead)
async def update_scenario_availability(
    session: SessionDep, _: PlannerWriter, availability_id: int, payload: ScenarioAvailabilityUpdate
) -> ScenarioAvailability:
    av = await session.get(ScenarioAvailability, availability_id)
    if av is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Availability not found")
    await _editable(session, av.scenario_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(av, field, value)
    await session.commit()
    await session.refresh(av)
    return av


@router.delete("/scenario-availability/{availability_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_scenario_availability(
    session: SessionDep, _: PlannerWriter, availability_id: int
) -> None:
    av = await session.get(ScenarioAvailability, availability_id)
    if av is None:
        return
    await _editable(session, av.scenario_id)
    if av.live_availability_id is not None:
        av.removed = True
    else:
        await session.delete(av)
    await session.commit()


# --- Views (computed, never persisted) ---
async def _materialize_or_404(session: AsyncSession, scenario_id: int) -> MaterializedScenario:
    m = await materialize(session, scenario_id)
    if m is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scenario not found")
    return m


def _cycle_guard(exc: CycleError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get("/scenarios/{scenario_id}/gantt", response_model=GanttResponse)
async def scenario_gantt_view(
    session: SessionDep, _: CurrentUser, scenario_id: int, project_id: int
) -> GanttResponse:
    m = await _materialize_or_404(session, scenario_id)
    try:
        return scenario_gantt(m, project_id)
    except CycleError as exc:
        raise _cycle_guard(exc) from exc


@router.get("/scenarios/{scenario_id}/critical-path", response_model=InitiativeCriticalPath)
async def scenario_critical_path_view(
    session: SessionDep, _: CurrentUser, scenario_id: int
) -> InitiativeCriticalPath:
    m = await _materialize_or_404(session, scenario_id)
    try:
        return scenario_critical_path(m)
    except CycleError as exc:
        raise _cycle_guard(exc) from exc


@router.get("/scenarios/{scenario_id}/capacity", response_model=CapacityResponse)
async def scenario_capacity_view(
    session: SessionDep, _: CurrentUser, scenario_id: int, project_id: int | None = None
) -> CapacityResponse:
    m = await _materialize_or_404(session, scenario_id)
    return scenario_capacity(m, project_id)


@router.get("/scenarios/{scenario_id}/alerts", response_model=AlertsResponse)
async def scenario_alerts_view(
    session: SessionDep, _: CurrentUser, scenario_id: int, project_id: int
) -> AlertsResponse:
    m = await _materialize_or_404(session, scenario_id)
    try:
        return scenario_alerts(m, project_id)
    except CycleError as exc:
        raise _cycle_guard(exc) from exc


@router.get("/scenarios/{scenario_id}/burndown", response_model=BurndownResponse)
async def scenario_burndown_view(
    session: SessionDep, _: CurrentUser, scenario_id: int, project_id: int
) -> BurndownResponse:
    m = await _materialize_or_404(session, scenario_id)
    try:
        return scenario_burndown(m, project_id)
    except CycleError as exc:
        raise _cycle_guard(exc) from exc


@router.get("/scenarios/{scenario_id}/forecast", response_model=ForecastResponse)
async def scenario_forecast_view(
    session: SessionDep, _: CurrentUser, scenario_id: int, project_id: int | None = None
) -> ForecastResponse:
    m = await _materialize_or_404(session, scenario_id)
    return scenario_forecast(m, project_id)


@router.get("/scenarios/{scenario_id}/board", response_model=BoardResponse)
async def scenario_board_view(
    session: SessionDep, _: CurrentUser, scenario_id: int, project_id: int
) -> BoardResponse:
    m = await _materialize_or_404(session, scenario_id)
    return scenario_board(m, project_id)


# --- Compare ---
def _live_cp_days(tasks: list[Task], deps: list[Dependency]) -> int:
    cp = cross_project_critical_path(
        [
            CPTask(id=t.id, project_id=t.project_id, duration=t.duration,
                   is_summary=t.type == TaskType.summary)
            for t in tasks
            if t.id is not None
        ],
        [CPDep(d.predecessor_id, d.successor_id, d.type.value, d.lag) for d in deps],
    )
    return cp.total_working_days


@router.get("/scenarios/{scenario_id}/compare", response_model=ScenarioCompareResponse)
async def compare_scenario(
    session: SessionDep, _: CurrentUser, scenario_id: int
) -> ScenarioCompareResponse:
    scenario = await _get_scenario(session, scenario_id)
    m = await _materialize_or_404(session, scenario_id)

    # Per-project ends: live from the persisted plan, scenario from the scenario CPM.
    per_project: list[ScenarioProjectDelta] = []
    for pid, key in sorted(m.project_keys.items()):
        live_ends = [t.end for t in m.live_tasks.values() if t.project_id == pid and t.end]
        live_end = max(live_ends) if live_ends else None
        try:
            gantt = scenario_gantt(m, pid)
        except CycleError as exc:
            raise _cycle_guard(exc) from exc
        s_ends = [t.end_date for t in gantt.tasks if t.end_date]
        scenario_end = max(s_ends) if s_ends else None
        delta = (scenario_end - live_end).days if (live_end and scenario_end) else None
        per_project.append(
            ScenarioProjectDelta(
                project_id=pid, project_key=key, live_end=live_end,
                scenario_end=scenario_end, end_delta_days=delta,
            )
        )

    # Critical paths (structural working days).
    live_tasks = list(m.live_tasks.values())
    live_task_ids = set(m.live_tasks)
    live_deps = [
        d
        for d in (await session.execute(select(Dependency))).scalars().all()
        if d.predecessor_id in live_task_ids and d.successor_id in live_task_ids
    ]
    try:
        live_cp = _live_cp_days(live_tasks, live_deps)
        scenario_cp = scenario_critical_path(m).total_working_days
    except CycleError as exc:
        raise _cycle_guard(exc) from exc

    # Live row maps for change-detection (loaded all; diff filters by provenance).
    all_s_tasks = list(
        (await session.execute(select(ScenarioTask).where(ScenarioTask.scenario_id == scenario_id)))
        .scalars().all()
    )
    all_s_deps = list(
        (await session.execute(
            select(ScenarioDependency).where(ScenarioDependency.scenario_id == scenario_id)
        )).scalars().all()
    )
    all_s_miles = list(
        (await session.execute(
            select(ScenarioMilestone).where(ScenarioMilestone.scenario_id == scenario_id)
        )).scalars().all()
    )
    all_s_allocs = list(
        (await session.execute(
            select(ScenarioAllocation).where(ScenarioAllocation.scenario_id == scenario_id)
        )).scalars().all()
    )
    all_s_avail = list(
        (await session.execute(
            select(ScenarioAvailability).where(ScenarioAvailability.scenario_id == scenario_id)
        )).scalars().all()
    )
    live_milestones = {
        ml.id: ml
        for ml in (await session.execute(select(Milestone))).scalars().all()
        if ml.id is not None
    }
    live_allocs = {
        a.id: a
        for a in (await session.execute(select(Allocation))).scalars().all()
        if a.id is not None
    }
    live_avail = {
        av.id: av
        for av in (await session.execute(select(EngineerAvailability))).scalars().all()
        if av.id is not None
    }

    diff = compute_scenario_diff(
        scenario_tasks=all_s_tasks,
        scenario_deps=all_s_deps,
        scenario_milestones=all_s_miles,
        scenario_allocations=all_s_allocs,
        scenario_availability=all_s_avail,
        live_tasks=m.live_tasks,
        live_milestones=live_milestones,
        live_allocations=live_allocs,
        live_availability=live_avail,
        project_ends=per_project,
        live_cp_working_days=live_cp,
        scenario_cp_working_days=scenario_cp,
    )
    conflicts = await detect_conflicts(session, scenario, all_s_tasks)
    return ScenarioCompareResponse(scenario_id=scenario_id, diff=diff, conflicts=conflicts)


# --- Apply ---
@router.post("/scenarios/{scenario_id}/apply", response_model=ScenarioApplyResult)
async def apply_scenario_view(
    session: SessionDep, user: PlannerWriter, __: HumanOnly, scenario_id: int,
    payload: ScenarioApplyRequest | None = None,
) -> ScenarioApplyResult:
    scenario = await _get_scenario(session, scenario_id)
    await ensure_initiative_editable(session, user, scenario.initiative_id)
    force = payload.force if payload else False
    try:
        result = await apply_scenario(session, scenario_id, force=force)
    except ScenarioConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"reason": "stale", "conflicts": [c.model_dump() for c in exc.conflicts]},
        ) from exc
    except CycleError as exc:
        raise _cycle_guard(exc) from exc
    except ScenarioApplyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return result
