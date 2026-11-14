"""Assembles the Kanban board and the status-history facts every flow view shares.

The pure parts (lanes, WIP, aging, ranks, cycle/lead time) live in `app/services/flow.py`; this
module gathers the rows: leaf tasks, their status history, the workflow's columns, open
blockers, tracker links and what the caller may do. Shared by the project board, the team
board (§C9) and the burndown / forecast / delivery endpoints, so "done", "started" and "in
progress" mean the same thing everywhere.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.models.base import CANOPY_OWNER, StatusCategory, TaskType
from app.models.project import Blocker, Project, Task, TaskStatusHistory
from app.schemas.entities import BoardLaneRead, BoardResponse, BoardTaskRead, BoardViewer
from app.services import flow
from app.services.links import external_urls
from app.services.workflow import category_of_task, history_point, resolve_workflow


async def history_points(
    session: AsyncSession, task_ids: list[int]
) -> dict[int, list[flow.HistoryPoint]]:
    """Each task's status transitions as pure history points (category stamped or derived)."""
    out: dict[int, list[flow.HistoryPoint]] = {}
    if not task_ids:
        return out
    rows = (
        await session.execute(
            select(TaskStatusHistory)
            .where(col(TaskStatusHistory.task_id).in_(task_ids))
            .order_by(col(TaskStatusHistory.changed_at), col(TaskStatusHistory.id))
        )
    ).scalars().all()
    for row in rows:
        out.setdefault(row.task_id, []).append(history_point(row))
    return out


def completion_dates(history: dict[int, list[flow.HistoryPoint]]) -> list[date]:
    """One completion date per task (its last transition into done), sorted."""
    return flow.completion_dates(
        [(task_id, point) for task_id, points in history.items() for point in points]
    )


def leaves_of(tasks: list[Task]) -> list[Task]:
    return [t for t in tasks if t.type != TaskType.summary and t.id is not None]


def task_flow_facts(
    task: Task, history: dict[int, list[flow.HistoryPoint]], today: date
) -> flow.FlowFacts:
    assert task.id is not None
    return flow.flow_facts(
        task.status,
        task.created_at.date(),
        task.updated_at.date(),
        history.get(task.id, []),
        today,
    )


def board_inputs(
    tasks: list[Task], history: dict[int, list[flow.HistoryPoint]], today: date
) -> list[flow.BoardTaskInput]:
    inputs: list[flow.BoardTaskInput] = []
    for t in leaves_of(tasks):
        assert t.id is not None
        facts = task_flow_facts(t, history, today)
        category = category_of_task(t)
        inputs.append(
            flow.BoardTaskInput(
                id=t.id,
                name=t.name,
                status=t.status,
                assignee_engineer_id=t.assignee_engineer_id,
                is_done=category == StatusCategory.done,
                age_days=facts.age_days,
                cycle_days=facts.cycle_days,
                category=category,
                rank=flow.effective_rank(t.board_rank, t.id),
            )
        )
    return inputs


async def build_board_response(
    session: AsyncSession,
    *,
    project_id: int,
    tasks: list[Task],
    columns: list[flow.ColumnDef] | None,
    wip_enforcement: str,
    mode: str,
    viewer: BoardViewer | None,
) -> BoardResponse:
    today = date.today()
    leaves = leaves_of(tasks)
    ids = [t.id for t in leaves if t.id is not None]
    history = await history_points(session, ids)
    board = flow.build_board(board_inputs(leaves, history, today), columns)

    blocked = (
        {
            b.task_id
            for b in (
                await session.execute(
                    select(Blocker).where(
                        col(Blocker.task_id).in_(ids), col(Blocker.resolved_at).is_(None)
                    )
                )
            ).scalars().all()
        }
        if ids
        else set()
    )
    mirrored_ids = [t.id for t in leaves if t.id is not None and t.status_owner != CANOPY_OWNER]
    urls = await external_urls(session, mirrored_ids)
    by_id = {t.id: t for t in leaves}

    lanes: list[BoardLaneRead] = []
    for lane in board.lanes:
        cards: list[BoardTaskRead] = []
        for bt in lane.tasks:
            t = by_id[bt.id]
            cards.append(
                BoardTaskRead(
                    id=bt.id,
                    name=bt.name,
                    status=bt.status,
                    assignee_engineer_id=bt.assignee_engineer_id,
                    is_done=bt.is_done,
                    age_days=bt.age_days,
                    aging=bt.aging,
                    project_id=t.project_id,
                    key=t.key,
                    status_category=bt.category,
                    status_owner=t.status_owner,
                    movable=t.status_owner == CANOPY_OWNER,
                    external_url=urls.get(bt.id),
                    rank=bt.rank,
                    parent_id=t.parent_id,
                    blocked=bt.id in blocked,
                    is_critical=t.is_critical,
                    deadline=t.deadline,
                    tags=list(t.tags or []),
                )
            )
        lanes.append(
            BoardLaneRead(
                status=lane.status,
                is_done=lane.is_done,
                wip=lane.wip,
                tasks=cards,
                category=lane.category,
                position=lane.position,
                wip_limit=lane.wip_limit,
                over_limit=lane.over_limit,
                in_workflow=lane.in_workflow,
            )
        )
    return BoardResponse(
        project_id=project_id,
        lanes=lanes,
        cycle_time_p85_days=board.cycle_time_p85_days,
        aging_count=board.aging_count,
        mode=mode,
        wip_enforcement=wip_enforcement,
        viewer=viewer,
    )


async def project_board(
    session: AsyncSession, project: Project, viewer: BoardViewer | None
) -> BoardResponse:
    assert project.id is not None
    tasks = list(
        (await session.execute(select(Task).where(Task.project_id == project.id))).scalars().all()
    )
    workflow = await resolve_workflow(session, project)
    return await build_board_response(
        session,
        project_id=project.id,
        tasks=tasks,
        columns=workflow.columns,
        wip_enforcement=workflow.wip_enforcement,
        mode=project.tracking_mode,
        viewer=viewer,
    )
