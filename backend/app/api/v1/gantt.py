from datetime import date

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.api.deps import CurrentUser, SessionDep
from app.models.base import TaskType
from app.models.project import Dependency, Project, Task, TaskStatusHistory
from app.schemas.entities import (
    BurndownPoint,
    BurndownResponse,
    GanttLink,
    GanttResponse,
    GanttTask,
    ReplanResult,
)
from app.services.burndown import compute_burndown, is_done_status
from app.services.capacity import mondays
from app.services.scheduling import (
    CycleError,
    SchedDep,
    SchedTask,
    assign_dates,
    compute_cpm,
    critical_path,
)

router = APIRouter()


async def _load_project_graph(
    session: AsyncSession, project_id: int
) -> tuple[list[Task], list[Dependency]]:
    tasks = list(
        (await session.execute(select(Task).where(Task.project_id == project_id)))
        .scalars()
        .all()
    )
    task_ids = {t.id for t in tasks}
    all_deps = (await session.execute(select(Dependency))).scalars().all()
    deps = [d for d in all_deps if d.predecessor_id in task_ids and d.successor_id in task_ids]
    return tasks, deps


def _project_start(project: Project, tasks: list[Task]) -> date:
    if project.start_date:
        return project.start_date
    starts = [t.start for t in tasks if t.start]
    return min(starts) if starts else date.today()


@router.get("/projects/{project_id}/gantt", response_model=GanttResponse)
async def get_gantt(session: SessionDep, _: CurrentUser, project_id: int) -> GanttResponse:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    tasks, deps = await _load_project_graph(session, project_id)
    gantt_tasks = [
        GanttTask(
            id=t.id,
            text=t.name,
            start_date=t.start,
            end_date=t.end,
            duration=t.duration,
            progress=round(t.percent_complete / 100.0, 4),
            parent=t.parent_id or 0,
            type=t.type,
            is_critical=t.is_critical,
            total_float=t.total_float,
        )
        for t in tasks
    ]
    links = [
        GanttLink(id=d.id, source=d.predecessor_id, target=d.successor_id, type=d.type, lag=d.lag)
        for d in deps
    ]
    return GanttResponse(project_id=project_id, tasks=gantt_tasks, links=links)


@router.post("/projects/{project_id}/replan", response_model=ReplanResult)
async def replan(session: SessionDep, _: CurrentUser, project_id: int) -> ReplanResult:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    tasks, deps = await _load_project_graph(session, project_id)
    start_ref = _project_start(project, tasks)

    sched_tasks: list[SchedTask] = []
    for t in tasks:
        if t.id is None:
            continue
        sched_tasks.append(
            SchedTask(
                id=t.id,
                duration=0 if t.type == TaskType.milestone else max(t.duration, 0),
                is_summary=t.type == TaskType.summary,
                pinned_start_offset=(t.start - start_ref).days if t.start else None,
            )
        )
    sched_deps = [
        SchedDep(d.predecessor_id, d.successor_id, d.type.value, d.lag) for d in deps
    ]

    try:
        results = compute_cpm(sched_tasks, sched_deps)
    except CycleError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    assign_dates(sched_tasks, results, start_ref)

    by_id = {t.id: t for t in tasks}
    project_end: date | None = None
    for tid, res in results.items():
        task = by_id[tid]
        task.start = res.start
        task.end = res.end
        task.is_critical = res.is_critical
        task.total_float = res.total_float
        if res.end and (project_end is None or res.end > project_end):
            project_end = res.end

    # Roll up summary tasks from their direct children.
    children: dict[int, list[Task]] = {}
    for t in tasks:
        if t.parent_id:
            children.setdefault(t.parent_id, []).append(t)
    for t in tasks:
        if t.type == TaskType.summary and t.id in children:
            child_starts = [c.start for c in children[t.id] if c.start]
            child_ends = [c.end for c in children[t.id] if c.end]
            t.start = min(child_starts) if child_starts else None
            t.end = max(child_ends) if child_ends else None
            if t.start and t.end:
                t.duration = (t.end - t.start).days

    await session.commit()
    return ReplanResult(
        project_id=project_id,
        scheduled_tasks=len(results),
        critical_path=critical_path(results),
        project_end=project_end,
    )


@router.get("/projects/{project_id}/burndown", response_model=BurndownResponse)
async def burndown(session: SessionDep, _: CurrentUser, project_id: int) -> BurndownResponse:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    tasks = list(
        (
            await session.execute(select(Task).where(Task.project_id == project_id))
        ).scalars().all()
    )
    leaves = [t for t in tasks if t.type != TaskType.summary]
    total = len(leaves)
    task_ids = {t.id for t in tasks}

    history = (
        await session.execute(
            select(TaskStatusHistory).where(col(TaskStatusHistory.task_id).in_(task_ids))
        )
    ).scalars().all()
    done_dates = sorted(
        h.changed_at.date() for h in history if is_done_status(h.to_status)
    )

    ends = [t.end for t in tasks if t.end]
    window_start = project.start_date or (done_dates[0] if done_dates else date.today())
    window_end = project.target_date or (max(ends) if ends else window_start)
    if window_end < window_start:
        window_end = window_start
    weeks = mondays(window_start, window_end)
    points = [
        BurndownPoint(week=p.week, total=p.total, completed=p.completed, remaining=p.remaining)
        for p in compute_burndown(total, done_dates, weeks)
    ]
    return BurndownResponse(project_id=project_id, points=points)
