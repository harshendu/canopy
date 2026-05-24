"""Apply a scenario to canopy's live planning layer, inside one transaction.

Walks the scenario rows by provenance (`live_*_id` + `removed`): create / update / delete the
matching live `Task`/`Dependency`/`Milestone`/`Allocation`/`EngineerAvailability`, remapping
scenario task ids to the live ids produced for newly-created tasks, then replans every affected
project. Newly-created rows are stamped with their live id so a re-apply updates (not
duplicates). Writes **only** canopy planning rows — never Jira (Jira stays source of truth).

Staleness: a scenario is frozen at `base_captured_at`; if a cloned live task was deleted, or a
new live task appeared, after that watermark, apply raises a conflict unless `force=True`.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.core.events import publish
from app.models.base import utcnow
from app.models.project import (
    Blocker,
    Dependency,
    Milestone,
    Project,
    Task,
    TaskStatusHistory,
)
from app.models.scenario import (
    Scenario,
    ScenarioAllocation,
    ScenarioAvailability,
    ScenarioDependency,
    ScenarioMilestone,
    ScenarioTask,
)
from app.models.team import Allocation, EngineerAvailability
from app.schemas.scenarios import ScenarioApplyResult, ScenarioConflict
from app.services.planner import reschedule_project


class ScenarioApplyError(Exception):
    """A precondition for applying the scenario failed (missing scenario, already applied)."""


class ScenarioConflictError(Exception):
    """Live data drifted from the scenario's snapshot; pass force=True to override."""

    def __init__(self, conflicts: list[ScenarioConflict]) -> None:
        self.conflicts = conflicts
        super().__init__("Live data changed since the scenario was captured")


async def detect_conflicts(
    session: AsyncSession, scenario: Scenario, scenario_tasks: list[ScenarioTask]
) -> list[ScenarioConflict]:
    """Live drift since the snapshot: cloned tasks deleted upstream, or new live tasks added
    to the initiative after `base_captured_at`."""
    project_ids = {
        p.id
        for p in (
            await session.execute(
                select(Project).where(Project.initiative_id == scenario.initiative_id)
            )
        ).scalars().all()
        if p.id is not None
    }
    conflicts: list[ScenarioConflict] = []
    cloned_live_ids = {t.live_task_id for t in scenario_tasks if t.live_task_id is not None}
    for t in scenario_tasks:
        if t.live_task_id is not None and await session.get(Task, t.live_task_id) is None:
            conflicts.append(
                ScenarioConflict(
                    entity_type="task",
                    entity_id=t.live_task_id,
                    reason=f"'{t.name}' was deleted upstream after the scenario was captured",
                )
            )
    if project_ids:
        for live in (
            await session.execute(select(Task).where(col(Task.project_id).in_(project_ids)))
        ).scalars().all():
            if live.id not in cloned_live_ids and live.created_at > scenario.base_captured_at:
                conflicts.append(
                    ScenarioConflict(
                        entity_type="task",
                        entity_id=live.id,
                        reason=f"'{live.name}' was added upstream after the scenario was captured",
                    )
                )
    return conflicts


def _ordered_by_depth(tasks: list[ScenarioTask]) -> list[ScenarioTask]:
    """Parents before children, so a parent's live id exists before its child links to it."""
    by_id = {t.id: t for t in tasks}

    def depth(task: ScenarioTask) -> int:
        d, seen, cur = 0, set(), task.parent_id
        while cur is not None and cur in by_id and cur not in seen:
            seen.add(cur)
            d += 1
            cur = by_id[cur].parent_id
        return d

    return sorted(tasks, key=lambda t: (depth(t), t.id or 0))


async def _delete_live_task(session: AsyncSession, task_id: int) -> None:
    """Delete a live task and the rows that FK-reference it (deps, allocations, blockers,
    status history) so the delete is safe under enforced foreign keys."""
    for dep in (
        await session.execute(
            select(Dependency).where(
                (col(Dependency.predecessor_id) == task_id)
                | (col(Dependency.successor_id) == task_id)
            )
        )
    ).scalars().all():
        await session.delete(dep)
    for alloc in (
        await session.execute(select(Allocation).where(Allocation.task_id == task_id))
    ).scalars().all():
        await session.delete(alloc)
    for blocker in (
        await session.execute(
            select(Blocker).where(
                (col(Blocker.task_id) == task_id) | (col(Blocker.blocking_task_id) == task_id)
            )
        )
    ).scalars().all():
        await session.delete(blocker)
    for hist in (
        await session.execute(select(TaskStatusHistory).where(TaskStatusHistory.task_id == task_id))
    ).scalars().all():
        await session.delete(hist)
    live = await session.get(Task, task_id)
    if live is not None:
        await session.delete(live)


async def apply_scenario(
    session: AsyncSession, scenario_id: int, *, force: bool = False
) -> ScenarioApplyResult:
    scenario = await session.get(Scenario, scenario_id)
    if scenario is None:
        raise ScenarioApplyError("Scenario not found")
    if scenario.status == "applied":
        raise ScenarioApplyError("Scenario has already been applied")

    project_ids = {
        p.id
        for p in (
            await session.execute(
                select(Project).where(Project.initiative_id == scenario.initiative_id)
            )
        ).scalars().all()
        if p.id is not None
    }

    s_tasks = list(
        (
            await session.execute(
                select(ScenarioTask).where(ScenarioTask.scenario_id == scenario_id)
            )
        ).scalars().all()
    )
    s_deps = list(
        (
            await session.execute(
                select(ScenarioDependency).where(ScenarioDependency.scenario_id == scenario_id)
            )
        ).scalars().all()
    )
    s_miles = list(
        (
            await session.execute(
                select(ScenarioMilestone).where(ScenarioMilestone.scenario_id == scenario_id)
            )
        ).scalars().all()
    )
    s_allocs = list(
        (
            await session.execute(
                select(ScenarioAllocation).where(ScenarioAllocation.scenario_id == scenario_id)
            )
        ).scalars().all()
    )
    s_avail = list(
        (
            await session.execute(
                select(ScenarioAvailability).where(
                    ScenarioAvailability.scenario_id == scenario_id
                )
            )
        ).scalars().all()
    )

    conflicts = await detect_conflicts(session, scenario, s_tasks)
    if conflicts and not force:
        raise ScenarioConflictError(conflicts)

    created = updated = deleted = 0
    remap: dict[int, int] = {}  # scenario task id -> live task id

    # --- Tasks (parents first) ---
    for st in _ordered_by_depth([t for t in s_tasks if t.id is not None]):
        assert st.id is not None
        parent_live = remap.get(st.parent_id) if st.parent_id is not None else None
        if st.removed:
            if st.live_task_id is not None:
                await _delete_live_task(session, st.live_task_id)
                deleted += 1
            continue
        if st.live_task_id is not None:
            live = await session.get(Task, st.live_task_id)
            if live is None:
                continue
            live.name = st.name
            live.description = st.description
            live.type = st.type
            live.duration = st.duration
            live.deadline = st.deadline
            live.percent_complete = st.percent_complete
            live.assignee_engineer_id = st.assignee_engineer_id
            live.parent_id = parent_live
            remap[st.id] = st.live_task_id
            updated += 1
        else:
            live = Task(
                project_id=st.project_id,
                parent_id=parent_live,
                name=st.name,
                description=st.description,
                type=st.type,
                duration=st.duration,
                deadline=st.deadline,
                percent_complete=st.percent_complete,
                assignee_engineer_id=st.assignee_engineer_id,
            )
            session.add(live)
            await session.flush()
            assert live.id is not None
            remap[st.id] = live.id
            st.live_task_id = live.id
            created += 1

    # --- Dependencies ---
    for sd in s_deps:
        if sd.removed:
            if sd.live_dep_id is not None:
                dep = await session.get(Dependency, sd.live_dep_id)
                if dep is not None:
                    await session.delete(dep)
                    deleted += 1
            continue
        pred = remap.get(sd.predecessor_id)
        succ = remap.get(sd.successor_id)
        if pred is None or succ is None:  # endpoint removed in the scenario
            continue
        if sd.live_dep_id is not None:
            dep = await session.get(Dependency, sd.live_dep_id)
            if dep is not None:
                dep.predecessor_id = pred
                dep.successor_id = succ
                dep.type = sd.type
                dep.lag = sd.lag
                updated += 1
        else:
            dep = Dependency(predecessor_id=pred, successor_id=succ, type=sd.type, lag=sd.lag)
            session.add(dep)
            await session.flush()
            sd.live_dep_id = dep.id
            created += 1

    # --- Milestones ---
    for sm in s_miles:
        if sm.removed:
            if sm.live_milestone_id is not None:
                mile = await session.get(Milestone, sm.live_milestone_id)
                if mile is not None:
                    await session.delete(mile)
                    deleted += 1
            continue
        if sm.live_milestone_id is not None:
            mile = await session.get(Milestone, sm.live_milestone_id)
            if mile is not None:
                mile.name, mile.description = sm.name, sm.description
                mile.target_date, mile.status = sm.target_date, sm.status
                updated += 1
        else:
            mile = Milestone(
                project_id=sm.project_id,
                name=sm.name,
                description=sm.description,
                target_date=sm.target_date,
                status=sm.status,
            )
            session.add(mile)
            await session.flush()
            sm.live_milestone_id = mile.id
            created += 1

    # --- Allocations ---
    for sa in s_allocs:
        if sa.removed:
            if sa.live_allocation_id is not None:
                alloc = await session.get(Allocation, sa.live_allocation_id)
                if alloc is not None:
                    await session.delete(alloc)
                    deleted += 1
            continue
        task_live = remap.get(sa.task_id) if sa.task_id is not None else None
        if sa.live_allocation_id is not None:
            alloc = await session.get(Allocation, sa.live_allocation_id)
            if alloc is not None:
                alloc.engineer_id = sa.engineer_id
                alloc.project_id = sa.project_id
                alloc.task_id = task_live
                alloc.percent_allocation = sa.percent_allocation
                alloc.capacity_hours_per_week = sa.capacity_hours_per_week
                alloc.start_date = sa.start_date
                alloc.end_date = sa.end_date
                updated += 1
        else:
            alloc = Allocation(
                engineer_id=sa.engineer_id,
                project_id=sa.project_id,
                task_id=task_live,
                percent_allocation=sa.percent_allocation,
                capacity_hours_per_week=sa.capacity_hours_per_week,
                start_date=sa.start_date,
                end_date=sa.end_date,
            )
            session.add(alloc)
            await session.flush()
            sa.live_allocation_id = alloc.id
            created += 1

    # --- Availability ---
    for sav in s_avail:
        if sav.removed:
            if sav.live_availability_id is not None:
                av = await session.get(EngineerAvailability, sav.live_availability_id)
                if av is not None:
                    await session.delete(av)
                    deleted += 1
            continue
        if sav.live_availability_id is not None:
            av = await session.get(EngineerAvailability, sav.live_availability_id)
            if av is not None:
                av.engineer_id = sav.engineer_id
                av.start_date = sav.start_date
                av.end_date = sav.end_date
                av.capacity_factor = sav.capacity_factor
                av.note = sav.note
                updated += 1
        else:
            av = EngineerAvailability(
                engineer_id=sav.engineer_id,
                start_date=sav.start_date,
                end_date=sav.end_date,
                capacity_factor=sav.capacity_factor,
                note=sav.note,
            )
            session.add(av)
            await session.flush()
            sav.live_availability_id = av.id
            created += 1

    # --- Replan each affected project (defer the commit to one transaction) ---
    replanned: list[int] = []
    for pid in sorted(project_ids):
        await reschedule_project(session, pid, persist=True, commit=False)
        replanned.append(pid)

    scenario.status = "applied"
    scenario.applied_at = utcnow()
    await session.commit()

    await publish({"type": "scenario_apply", "initiative_id": scenario.initiative_id,
                   "scenario_id": scenario_id})
    for pid in replanned:
        await publish({"type": "replan", "project_id": pid})

    return ScenarioApplyResult(
        scenario_id=scenario_id,
        status=scenario.status,
        created=created,
        updated=updated,
        deleted=deleted,
        replanned_projects=replanned,
        conflicts=conflicts,
    )
