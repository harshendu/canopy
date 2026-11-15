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

from app.models.base import (
    CANOPY_OWNER,
    ClaimState,
    GateKind,
    GateStatus,
    StatusCategory,
    TaskType,
    utcnow,
)
from app.models.gate import Gate
from app.models.org import Team
from app.models.project import Blocker, Project, Task, TaskStatusHistory
from app.models.sprint import Sprint
from app.models.work import WorkClaim
from app.schemas.entities import (
    BoardClaimRead,
    BoardGateRead,
    BoardLaneRead,
    BoardResponse,
    BoardTaskRead,
    BoardViewer,
)
from app.services import flow, policy_service, work_service
from app.services.links import external_urls
from app.services.org import team_project_ids
from app.services.sprint_service import (
    active_sprints,
    is_closed,
    project_delivery,
    team_delivery,
    team_sprints,
)
from app.services.stage_policy import Pipeline
from app.services.workflow import (
    category_of_task,
    history_point,
    resolve_workflow,
    shared_column_project_ids,
    team_workflow,
    wip_counts,
    wip_scope_project_ids,
)


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
    fold_unknown: bool = False,
    team_id: int | None = None,
    sprint_id: int | None = None,
    delivery_method: str = "kanban",
    scope_counts: dict[str, int] | None = None,
    pipeline: Pipeline | None = None,
) -> BoardResponse:
    """`scope_counts`: open cards per status across the WIP scope (`wip_counts`) — a column's
    limit counts the whole scope, which can be wider than this board (a team's other projects,
    a sprint filter), so `over_limit` follows the same count the move check enforces."""
    today = date.today()
    leaves = leaves_of(tasks)
    ids = [t.id for t in leaves if t.id is not None]
    history = await history_points(session, ids)
    board = flow.build_board(board_inputs(leaves, history, today), columns, fold_unknown)

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
    claims, gates = await agent_badges(session, ids)

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
                    sprint_id=t.sprint_id,
                    story_points=t.story_points,
                    duration=t.duration,
                    delegation=t.delegation,
                    claim=claims.get(bt.id),
                    gate=gates.get(bt.id),
                    parked=bt.id in gates and gates[bt.id].parked,
                    awaiting_move=work_service.awaiting_move(t),
                )
            )
        scope_wip = (
            scope_counts.get(lane.status.casefold(), 0)
            if scope_counts is not None and lane.in_workflow
            else None
        )
        closed = lane.category in (StatusCategory.done.value, StatusCategory.cancelled.value)
        over_limit = (
            lane.wip_limit is not None and not closed and scope_wip > lane.wip_limit
            if scope_wip is not None
            else lane.over_limit
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
                over_limit=over_limit,
                in_workflow=lane.in_workflow,
                scope_wip=scope_wip,
                worked_by=(
                    stage.worked_by
                    if pipeline is not None and (stage := pipeline.stage(lane.status)) is not None
                    else None
                ),
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
        team_id=team_id,
        sprint_id=sprint_id,
        delivery_method=delivery_method,
    )


async def agent_badges(
    session: AsyncSession, task_ids: list[int]
) -> tuple[dict[int, BoardClaimRead], dict[int, BoardGateRead]]:
    """The live claim and the open gate (oldest first) of each card, for the board's badges."""
    if not task_ids:
        return {}, {}
    now = utcnow()
    claims: dict[int, BoardClaimRead] = {}
    for claim in (
        await session.execute(
            select(WorkClaim).where(
                col(WorkClaim.task_id).in_(task_ids),
                col(WorkClaim.state) == ClaimState.active.value,
            )
        )
    ).scalars().all():
        assert claim.id is not None
        claims[claim.task_id] = BoardClaimRead(
            id=claim.id,
            role=claim.role,
            label=claim.agent_label,
            since=claim.claimed_at,
            heartbeat_age_s=max(0, int((now - claim.heartbeat_at).total_seconds())),
        )
    gates: dict[int, BoardGateRead] = {}
    for gate in (
        await session.execute(
            select(Gate)
            .where(col(Gate.task_id).in_(task_ids), col(Gate.status) == GateStatus.open.value)
            .order_by(col(Gate.created_at))
        )
    ).scalars().all():
        if gate.task_id in gates or gate.id is None:
            continue
        gates[gate.task_id] = BoardGateRead(
            id=gate.id,
            kind=gate.kind,
            origin=gate.origin,
            parked=gate.kind == GateKind.escalation.value and gate.origin == "system",
            title=gate.title,
            age_hours=round(max(0.0, (now - gate.created_at).total_seconds()) / 3600, 1),
        )
    return claims, gates


async def filter_by_sprint(
    session: AsyncSession, tasks: list[Task], team_id: int | None, sprint: str | None
) -> tuple[list[Task], int | None]:
    """Narrow a board to a sprint: `active` (the team's active sprint(s)), `backlog` (open work
    in no live sprint), `all`/None (everything) or a sprint id. Returns the tasks and, when one
    sprint is shown, its id."""
    if sprint in (None, "", "all") or team_id is None:
        return tasks, None
    if sprint == "active":
        active = await active_sprints(session, team_id)
        ids = {s.id for s in active}
        shown = active[0].id if len(active) == 1 else None
        return [t for t in tasks if t.sprint_id in ids], shown
    if sprint == "backlog":
        live = {
            s.id for s in await team_sprints(session, team_id) if s.state != "completed"
        }
        backlog = [
            t
            for t in tasks
            if not is_closed(t) and (t.sprint_id is None or t.sprint_id not in live)
        ]
        return backlog, None
    try:
        wanted = int(sprint)
    except ValueError:
        return tasks, None
    row = await session.get(Sprint, wanted)
    if row is None or row.team_id != team_id:
        return [], wanted
    return [t for t in tasks if t.sprint_id == wanted], wanted


async def project_board(
    session: AsyncSession,
    project: Project,
    viewer: BoardViewer | None,
    sprint: str | None = None,
) -> BoardResponse:
    assert project.id is not None
    tasks = list(
        (await session.execute(select(Task).where(Task.project_id == project.id))).scalars().all()
    )
    delivery = await project_delivery(session, project)
    tasks, sprint_id = await filter_by_sprint(session, tasks, delivery.team_id, sprint)
    workflow = await resolve_workflow(session, project)
    return await build_board_response(
        session,
        project_id=project.id,
        tasks=tasks,
        columns=workflow.columns,
        wip_enforcement=workflow.wip_enforcement,
        mode=project.tracking_mode,
        viewer=viewer,
        sprint_id=sprint_id,
        delivery_method=delivery.effective_method,
        scope_counts=await wip_counts(
            session, await wip_scope_project_ids(session, project, workflow)
        ),
        pipeline=await policy_service.resolve_pipeline(session, project),
    )


async def team_board(
    session: AsyncSession,
    team_id: int,
    viewer: BoardViewer | None,
    *,
    pod_id: int | None = None,
    project_id: int | None = None,
    sprint: str | None = None,
) -> BoardResponse:
    """One board over every project the team runs, on the team's workflow. A card whose
    status the team's columns don't name (a mirrored status, a project override) sits in the
    first column of the same category and keeps its own status."""
    project_ids = await team_project_ids(session, team_id)
    if pod_id is not None:
        project_ids = [
            pid
            for pid in project_ids
            if (p := await session.get(Project, pid)) is not None and p.pod_id == pod_id
        ]
    if project_id is not None:
        project_ids = [pid for pid in project_ids if pid == project_id]
    tasks = (
        list(
            (
                await session.execute(select(Task).where(col(Task.project_id).in_(project_ids)))
            ).scalars().all()
        )
        if project_ids
        else []
    )
    tasks, sprint_id = await filter_by_sprint(session, tasks, team_id, sprint)
    workflow = await team_workflow(session, team_id)
    team = await session.get(Team, team_id)
    delivery = await team_delivery(session, team) if team is not None else None
    modes = {
        p.tracking_mode
        for pid in project_ids
        if (p := await session.get(Project, pid)) is not None
    }
    return await build_board_response(
        session,
        project_id=0,
        tasks=tasks,
        columns=workflow.columns,
        wip_enforcement=workflow.wip_enforcement,
        mode="mirrored" if "mirrored" in modes else "native",
        viewer=viewer,
        fold_unknown=True,
        team_id=team_id,
        sprint_id=sprint_id,
        delivery_method=delivery.effective_method if delivery is not None else "kanban",
        scope_counts=await wip_counts(session, await shared_column_project_ids(session, team_id)),
    )
