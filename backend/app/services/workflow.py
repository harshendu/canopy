"""Work tracking: status categories, board workflows, the single status write path, card
placement and native task keys (USER_FLOWS §C9, CLAUDE.md "Source-of-truth boundaries").

**One writer.** `record_transition` is the only code that changes `Task.status`. A canopy move
(`move_task`), a proposal apply, a draft finalise and an inbound sync all end here, so every
change stamps its category, appends a `TaskStatusHistory` row and reconciles
`percent_complete` the same way. `tests/test_status_single_writer.py` enforces it.

**Ownership.** `Task.status_owner` is "canopy" or a tracker's provider key. canopy moves only
canopy-owned tasks; a mirrored task's status changes only when its tracker says so, and canopy
never writes a status back to a tracker.

**Workflows.** A board's columns resolve project override → team → workspace template →
built-in default. Nothing is written on read: a default applies live until someone saves one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.models.base import (
    CANOPY_OWNER,
    StatusCategory,
    StatusSource,
    TaskType,
    TrackingMode,
    WipEnforcement,
    utcnow,
)
from app.models.project import Project, Task, TaskStatusHistory
from app.models.workflow import Workflow, WorkflowStatus
from app.services import flow
from app.services.burndown import DONE_STATUSES
from app.services.org import project_team_id, team_project_ids

DEFAULT_WORKFLOW_NAME = "Default"
DEFAULT_COLUMNS: tuple[tuple[str, StatusCategory], ...] = (
    ("Backlog", StatusCategory.todo),
    ("To Do", StatusCategory.todo),
    ("In Progress", StatusCategory.in_progress),
    ("In Review", StatusCategory.in_progress),
    ("Done", StatusCategory.done),
    ("Cancelled", StatusCategory.cancelled),
)
MAX_STATUS_NAME = 64

# The name heuristic is the last resort of `resolve_category` (a payload that carries no
# category and a status no workflow names). Only unambiguous names are listed; everything
# else counts as started work.
_CANCELLED_NAMES = frozenset(
    {
        "cancelled",
        "canceled",
        "won't do",
        "wont do",
        "won't fix",
        "wontfix",
        "duplicate",
        "rejected",
        "declined",
        "abandoned",
        "dropped",
        "obsolete",
    }
)
_TODO_NAMES = frozenset(
    {
        "to do",
        "todo",
        "backlog",
        "open",
        "new",
        "triage",
        "ready",
        "ready for dev",
        "ready for development",
        "selected for development",
        "planned",
        "not started",
        "icebox",
        "unstarted",
        "reopened",
    }
)


# --------------------------------------------------------------------------- #
# Categories (pure)
# --------------------------------------------------------------------------- #


def heuristic_category(name: str | None) -> str | None:
    if name is None or not name.strip():
        return None
    key = name.strip().casefold()
    if key in DONE_STATUSES:
        return StatusCategory.done.value
    if key in _CANCELLED_NAMES:
        return StatusCategory.cancelled.value
    if key in _TODO_NAMES:
        return StatusCategory.todo.value
    return StatusCategory.in_progress.value


def valid_category(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return StatusCategory(str(value)).value
    except ValueError:
        return None


def resolve_category(
    name: str | None,
    *,
    explicit: str | None = None,
    columns: list[flow.ColumnDef] | None = None,
) -> str | None:
    """The category of a status: what the tracker sent, else what the workflow says, else the
    name heuristic (which keeps MCP/file ingest working when a payload omits the category)."""
    if name is None or not name.strip():
        return None
    sent = valid_category(explicit)
    if sent is not None:
        return sent
    if columns:
        key = name.strip().casefold()
        for column in columns:
            if column.name.casefold() == key:
                return column.category
    return heuristic_category(name)


def category_of_task(task: Task) -> str | None:
    return task.status_category or heuristic_category(task.status)


def category_of_history(row: TaskStatusHistory) -> str | None:
    return row.to_category or heuristic_category(row.to_status)


def history_point(row: TaskStatusHistory) -> flow.HistoryPoint:
    return flow.HistoryPoint(
        to_status=row.to_status, category=category_of_history(row), at=row.changed_at.date()
    )


def parse_remote_time(value: str | None) -> datetime | None:
    """A tracker's ISO timestamp (`2026-05-02T10:00:00.000+0000`, `...Z`, `...+00:00`) as the
    naive UTC datetime canopy stores (see `models/base.py:utcnow`)."""
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    if len(text) > 5 and text[-5] in "+-" and text[-3] != ":":  # +0000 -> +00:00
        text = f"{text[:-2]}:{text[-2:]}"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = datetime.strptime(value[:19], "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


class TrackingError(Exception):
    """A refused tracking operation, mapped to an HTTP status with a machine-readable code."""

    def __init__(self, code: str, message: str, status_code: int, **extra: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.extra = extra

    def detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, **self.extra}


# --------------------------------------------------------------------------- #
# Workflows
# --------------------------------------------------------------------------- #


@dataclass
class WorkflowView:
    """A resolved workflow. `scope` says where its columns are defined (project | team |
    template | default); `inherited` is True when the asked-for scope has none of its own."""

    id: int | None
    scope: str
    team_id: int | None
    project_id: int | None
    name: str
    wip_enforcement: str
    columns: list[flow.ColumnDef] = field(default_factory=list)
    inherited: bool = False

    def column(self, name: str | None) -> flow.ColumnDef | None:
        if name is None:
            return None
        key = name.strip().casefold()
        return next((c for c in self.columns if c.name.casefold() == key), None)

    def first_of(self, category: str) -> flow.ColumnDef | None:
        return next(
            (c for c in sorted(self.columns, key=lambda c: c.position) if c.category == category),
            None,
        )


def default_view() -> WorkflowView:
    return WorkflowView(
        id=None,
        scope="default",
        team_id=None,
        project_id=None,
        name=DEFAULT_WORKFLOW_NAME,
        wip_enforcement=WipEnforcement.warn.value,
        columns=[
            flow.ColumnDef(name=name, category=category.value, position=index)
            for index, (name, category) in enumerate(DEFAULT_COLUMNS)
        ],
    )


async def _find(
    session: AsyncSession, *, team_id: int | None, project_id: int | None
) -> Workflow | None:
    stmt = select(Workflow)
    stmt = stmt.where(
        col(Workflow.team_id).is_(None) if team_id is None else Workflow.team_id == team_id
    )
    stmt = stmt.where(
        col(Workflow.project_id).is_(None)
        if project_id is None
        else Workflow.project_id == project_id
    )
    return (await session.execute(stmt.order_by(col(Workflow.id)))).scalars().first()


async def _view_of(session: AsyncSession, workflow: Workflow, *, inherited: bool) -> WorkflowView:
    statuses = (
        await session.execute(
            select(WorkflowStatus)
            .where(WorkflowStatus.workflow_id == workflow.id)
            .order_by(col(WorkflowStatus.position), col(WorkflowStatus.id))
        )
    ).scalars().all()
    scope = (
        "project"
        if workflow.project_id is not None
        else "team"
        if workflow.team_id is not None
        else "template"
    )
    return WorkflowView(
        id=workflow.id,
        scope=scope,
        team_id=workflow.team_id,
        project_id=workflow.project_id,
        name=workflow.name,
        wip_enforcement=workflow.wip_enforcement,
        columns=[
            flow.ColumnDef(
                name=s.name, category=s.category, position=index, wip_limit=s.wip_limit
            )
            for index, s in enumerate(statuses)
        ],
        inherited=inherited,
    )


async def template_workflow(session: AsyncSession) -> WorkflowView:
    row = await _find(session, team_id=None, project_id=None)
    return await _view_of(session, row, inherited=False) if row is not None else default_view()


async def team_workflow(session: AsyncSession, team_id: int) -> WorkflowView:
    row = await _find(session, team_id=team_id, project_id=None)
    if row is not None:
        return await _view_of(session, row, inherited=False)
    view = await template_workflow(session)
    view.inherited = True
    return view


async def tracker_view(session: AsyncSession, project: Project) -> WorkflowView | None:
    """A mirrored project's columns: the bound tracker's statuses, in the tracker's order and
    categories (refreshed on each full sync). None when the project isn't mirrored or the
    tracker sent no status map yet (its board then uses the normal resolution)."""
    if project.id is None or project.tracking_mode != TrackingMode.mirrored.value:
        return None
    from app.services.tracker_sync import binding_for_project, board_columns_for

    binding = await binding_for_project(session, project.id)
    if binding is None:
        return None
    columns = await board_columns_for(session, binding)
    if not columns:
        return None
    from app.connectors.tracker import tracker_class

    cls = tracker_class(binding.provider)
    label = cls.label if cls is not None and cls.label else binding.provider.value
    return WorkflowView(
        id=None,
        scope="tracker",
        team_id=None,
        project_id=project.id,
        name=f"{label} workflow",
        # The tracker owns this workflow (and its limits); canopy only shows WIP.
        wip_enforcement=WipEnforcement.off.value,
        columns=[
            flow.ColumnDef(name=c.name, category=c.category, position=i)
            for i, c in enumerate(sorted(columns, key=lambda c: c.position))
        ],
        inherited=False,
    )


async def resolve_workflow(
    session: AsyncSession, project: Project, *, ignore_tracker: bool = False
) -> WorkflowView:
    """The workflow a project's board uses: a mirrored project's tracker statuses, else its own
    override, else its team's, else the workspace template, else the built-in default.
    `ignore_tracker` skips the tracker's statuses (what the project would use natively)."""
    mirrored = None if ignore_tracker else await tracker_view(session, project)
    if mirrored is not None:
        return mirrored
    if project.id is not None:
        row = await _find(session, team_id=None, project_id=project.id)
        if row is not None:
            return await _view_of(session, row, inherited=False)
    team_id = await project_team_id(session, project)
    view = (
        await team_workflow(session, team_id)
        if team_id is not None
        else await template_workflow(session)
    )
    view.inherited = True
    return view


async def workflow_scope_project_ids(session: AsyncSession, project: Project) -> list[int]:
    """The projects whose cards share a board order and WIP count with this one: the team's
    projects when it has a team, else just this project."""
    assert project.id is not None
    team_id = await project_team_id(session, project)
    if team_id is None:
        return [project.id]
    ids = await team_project_ids(session, team_id)
    return ids if project.id in ids else sorted({*ids, project.id})


async def wip_scope_project_ids(
    session: AsyncSession, project: Project, view: WorkflowView | None = None
) -> list[int]:
    """The projects whose open cards count against this project's WIP limits: just this one
    when its columns are its own (an override, or its tracker's statuses), else every project
    of its team that shares the team's (or the template's) columns."""
    assert project.id is not None
    view = view or await resolve_workflow(session, project)
    if view.scope in ("project", "tracker"):
        return [project.id]
    team_id = await project_team_id(session, project)
    if team_id is None:
        return [project.id]
    return sorted({project.id, *await shared_column_project_ids(session, team_id)})


async def shared_column_project_ids(session: AsyncSession, team_id: int) -> list[int]:
    """The team's projects on the team's (or the template's) columns — not those with their
    own override or a tracker's statuses. They share one WIP count per column."""
    overridden = {
        w.project_id
        for w in (
            await session.execute(select(Workflow).where(col(Workflow.project_id).is_not(None)))
        ).scalars().all()
    }
    out: list[int] = []
    for pid in await team_project_ids(session, team_id):
        if pid in overridden:
            continue
        project = await session.get(Project, pid)
        if project is None or await tracker_view(session, project) is not None:
            continue
        out.append(pid)
    return out


def open_status_counts(tasks: list[Task]) -> dict[str, int]:
    """Open (not done/cancelled) cards per status, keyed case-insensitively — what a column's
    WIP limit counts."""
    counts: dict[str, int] = {}
    for task in tasks:
        if task.type == TaskType.summary or not task.status:
            continue
        if category_of_task(task) in (StatusCategory.done, StatusCategory.cancelled):
            continue
        key = task.status.casefold()
        counts[key] = counts.get(key, 0) + 1
    return counts


async def wip_counts(session: AsyncSession, project_ids: list[int]) -> dict[str, int]:
    return open_status_counts(await _scope_leaves(session, project_ids))


async def _projects_using(
    session: AsyncSession, *, team_id: int | None, project_id: int | None
) -> list[Project]:
    """Projects whose board resolves to the workflow defined at exactly this scope."""
    if project_id is not None:
        project = await session.get(Project, project_id)
        return [project] if project is not None else []
    overridden = {
        w.project_id
        for w in (
            await session.execute(select(Workflow).where(col(Workflow.project_id).is_not(None)))
        ).scalars().all()
    }
    projects = [
        p
        for p in (await session.execute(select(Project))).scalars().all()
        if p.id is not None
        and p.id not in overridden
        # A mirrored project's board shows its tracker's columns, not a team/template's.
        and await tracker_view(session, p) is None
    ]
    if team_id is not None:
        ids = set(await team_project_ids(session, team_id))
        return [p for p in projects if p.id in ids]
    teams_with_own = {
        w.team_id
        for w in (
            await session.execute(select(Workflow).where(col(Workflow.team_id).is_not(None)))
        ).scalars().all()
    }
    out: list[Project] = []
    for project in projects:
        team = await project_team_id(session, project)
        if team is None or team not in teams_with_own:
            out.append(project)
    return out


@dataclass
class ColumnInput:
    name: str
    category: str
    wip_limit: int | None = None
    previous_name: str | None = None  # set to rename an existing column (keeps its tasks)


async def save_workflow(
    session: AsyncSession,
    *,
    team_id: int | None,
    project_id: int | None,
    name: str,
    wip_enforcement: str,
    columns: list[ColumnInput],
    move_tasks_to: dict[str, str] | None = None,
    actor: str | None = None,
) -> WorkflowView:
    """Replace the workflow defined at one scope (project, team, or the template when both
    are None). A renamed column carries its canopy-owned tasks with it; a removed column that
    still holds canopy-owned tasks needs a target in `move_tasks_to` (else 422
    `column_in_use`), and those tasks move with a recorded transition. Does not commit."""
    if team_id is not None and project_id is not None:
        raise TrackingError("bad_scope", "a workflow belongs to a team or a project", 422)
    enforcement = _valid_enforcement(wip_enforcement)
    cleaned = _validate_columns(columns)
    moves = {k.strip().casefold(): v for k, v in (move_tasks_to or {}).items()}

    projects = await _projects_using(session, team_id=team_id, project_id=project_id)
    current = await _current_view(session, team_id=team_id, project_id=project_id)
    new_by_key = {c.name.casefold(): c for c in cleaned}
    renames: dict[str, ColumnInput] = {}
    for column in cleaned:
        if column.previous_name and column.previous_name.casefold() != column.name.casefold():
            renames[column.previous_name.strip().casefold()] = column
    kept = set(new_by_key) | set(renames)
    removed = [c for c in current.columns if c.name.casefold() not in kept]

    project_ids = [p.id for p in projects if p.id is not None]
    tasks = (
        list(
            (
                await session.execute(
                    select(Task).where(
                        col(Task.project_id).in_(project_ids),
                        Task.status_owner == CANOPY_OWNER,
                        Task.type != TaskType.summary,
                    )
                )
            ).scalars().all()
        )
        if project_ids
        else []
    )

    blocked: list[str] = []
    for gone in removed:
        key = gone.name.casefold()
        holders = [t for t in tasks if (t.status or "").casefold() == key]
        if not holders:
            continue
        target_name = moves.get(key)
        if target_name is None or target_name.strip().casefold() not in new_by_key:
            blocked.append(gone.name)
    if blocked:
        raise TrackingError(
            "column_in_use",
            "Removed columns still hold tasks — say where they go in move_tasks_to: "
            + ", ".join(blocked),
            422,
            columns=blocked,
        )

    workflow = await _find(session, team_id=team_id, project_id=project_id)
    if workflow is None:
        workflow = Workflow(team_id=team_id, project_id=project_id, name=name)
        session.add(workflow)
    workflow.name = name.strip() or DEFAULT_WORKFLOW_NAME
    workflow.wip_enforcement = enforcement
    workflow.updated_at = utcnow()
    await session.flush()
    assert workflow.id is not None
    for old in (
        await session.execute(
            select(WorkflowStatus).where(WorkflowStatus.workflow_id == workflow.id)
        )
    ).scalars().all():
        await session.delete(old)
    await session.flush()
    for position, column in enumerate(cleaned):
        session.add(
            WorkflowStatus(
                workflow_id=workflow.id,
                name=column.name,
                category=column.category,
                position=position,
                wip_limit=column.wip_limit,
            )
        )

    for task in tasks:
        key = (task.status or "").casefold()
        if key in renames:
            target = renames[key]
            _set_status(task, target.name, target.category)
        elif key in new_by_key:
            column_in = new_by_key[key]
            if task.status != column_in.name or task.status_category != column_in.category:
                # Same column, new spelling or meaning: no transition happened.
                _set_status(task, column_in.name, column_in.category)
        elif key and key in moves:
            target = new_by_key[moves[key].strip().casefold()]
            record_transition(
                session,
                task,
                target.name,
                category=target.category,
                source=StatusSource.canopy,
                author=actor,
            )
    await session.flush()
    return await _view_of(session, workflow, inherited=False)


async def _current_view(
    session: AsyncSession, *, team_id: int | None, project_id: int | None
) -> WorkflowView:
    """What tasks at this scope see right now (own, else inherited)."""
    if project_id is not None:
        project = await session.get(Project, project_id)
        if project is None:
            raise TrackingError("not_found", "Project not found", 404)
        return await resolve_workflow(session, project)
    if team_id is not None:
        return await team_workflow(session, team_id)
    return await template_workflow(session)


def _valid_enforcement(value: str) -> str:
    try:
        return WipEnforcement(value).value
    except ValueError as exc:
        raise TrackingError(
            "bad_wip_enforcement",
            f"wip_enforcement must be one of off|warn|block, not {value!r}",
            422,
        ) from exc


def _validate_columns(columns: list[ColumnInput]) -> list[ColumnInput]:
    if not columns:
        raise TrackingError("no_columns", "A workflow needs at least one column", 422)
    cleaned: list[ColumnInput] = []
    seen: set[str] = set()
    for column in columns:
        name = column.name.strip()
        if not name or len(name) > MAX_STATUS_NAME:
            raise TrackingError(
                "bad_column", f"Column names must be 1-{MAX_STATUS_NAME} characters", 422
            )
        if name.casefold() in seen:
            raise TrackingError("duplicate_column", f"Column {name!r} appears twice", 422)
        seen.add(name.casefold())
        category = valid_category(column.category)
        if category is None:
            raise TrackingError(
                "bad_category",
                f"Column {name!r}: category must be todo|in_progress|done|cancelled",
                422,
            )
        if column.wip_limit is not None and column.wip_limit < 1:
            raise TrackingError("bad_wip_limit", f"Column {name!r}: wip_limit must be >= 1", 422)
        cleaned.append(
            ColumnInput(
                name=name,
                category=category,
                wip_limit=column.wip_limit,
                previous_name=column.previous_name,
            )
        )
    categories = {c.category for c in cleaned}
    for needed in (StatusCategory.todo.value, StatusCategory.done.value):
        if needed not in categories:
            raise TrackingError(
                "missing_category", f"A workflow needs at least one {needed!r} column", 422
            )
    return cleaned


# --------------------------------------------------------------------------- #
# The single status write path
# --------------------------------------------------------------------------- #


def _set_status(task: Task, name: str | None, category: str | None) -> None:
    task.status = name
    task.status_category = category
    _reconcile_progress(task, category)


def _reconcile_progress(task: Task, category: str | None) -> None:
    # Entering done sets 100%; leaving done drops a 100% back to 0; any other manual partial
    # progress is kept (canopy-only signal) — one definition of "done" for every view.
    if category == StatusCategory.done.value:
        task.percent_complete = 100.0
    elif task.percent_complete >= 100.0:
        task.percent_complete = 0.0


def record_transition(
    session: AsyncSession,
    task: Task,
    to_status: str | None,
    *,
    category: str | None,
    source: StatusSource,
    author: str | None = None,
    at: datetime | None = None,
) -> TaskStatusHistory | None:
    """Set a task's status and category, reconcile its progress, and append a history row when
    the status actually changed. Returns the new row (None when nothing changed). The task must
    have an id (flush first). The ONLY writer of `Task.status` — see the module docstring."""
    previous = task.status
    _set_status(task, to_status, category)
    if previous == to_status:
        return None
    assert task.id is not None
    row = TaskStatusHistory(
        task_id=task.id,
        from_status=previous,
        to_status=to_status,
        to_category=category,
        changed_at=at or utcnow(),
        author=author,
        source=source.value,
    )
    session.add(row)
    return row


def stamp_category(task: Task, category: str | None) -> None:
    """Correct the category of the current status without a transition (e.g. the tracker's
    real category arriving after a heuristic guess)."""
    if task.status_category != category:
        _set_status(task, task.status, category)


# --------------------------------------------------------------------------- #
# Native task keys
# --------------------------------------------------------------------------- #


async def assign_native_key(session: AsyncSession, task: Task) -> str | None:
    """Give a canopy-owned task its `<prefix>-<n>` key (prefix = the project's
    `task_key_prefix`, else its key). Numbers come from `Project.next_task_number`, bumped with
    an UPDATE that row-locks the project until commit, and skip any key already in use."""
    if task.key:
        return task.key
    project = await session.get(Project, task.project_id)
    if project is None or project.id is None:
        return None
    prefix = (project.task_key_prefix or project.key).strip()
    in_use = {
        k
        for k in (
            await session.execute(select(Task.key).where(Task.project_id == project.id))
        )
        .scalars()
        .all()
        if k
    }
    for _ in range(10_000):
        await session.execute(
            update(Project)
            .where(col(Project.id) == project.id)
            .values(next_task_number=col(Project.next_task_number) + 1)
            .execution_options(synchronize_session=False)
        )
        bumped = (
            await session.execute(
                select(Project.next_task_number).where(col(Project.id) == project.id)
            )
        ).scalar_one()
        candidate = f"{prefix}-{int(bumped) - 1}"
        if candidate not in in_use:
            task.key = candidate
            return candidate
    return None


def default_column(workflow: WorkflowView, task: Task) -> flow.ColumnDef | None:
    """Where a new task with no status asked for starts: work already marked 100% lands in
    the first done column, partly done work in the first in-progress one, else the first todo
    column (each falling back to the first todo column)."""
    if task.percent_complete >= 100:
        wanted = StatusCategory.done.value
    elif task.percent_complete > 0:
        wanted = StatusCategory.in_progress.value
    else:
        wanted = StatusCategory.todo.value
    return workflow.first_of(wanted) or workflow.first_of(StatusCategory.todo.value)


async def initialise_native_task(
    session: AsyncSession,
    task: Task,
    *,
    status: str | None,
    native_enabled: bool,
    author: str | None,
) -> None:
    """Finish creating a canopy-owned task: its key, and its first status — the one asked for
    (must be a column of the project's workflow) or `default_column`. Summary tasks
    (phases) carry no status. With `tracking.native` off, canopy may not own a status at all.
    The task must be flushed. Raises TrackingError on an unknown status."""
    task.status_owner = CANOPY_OWNER
    await assign_native_key(session, task)
    if task.type == TaskType.summary:
        if status is not None:
            raise TrackingError("summary_has_no_status", "Summary tasks carry no status", 422)
        return
    if not native_enabled:
        if status is not None:
            raise TrackingError(
                "native_tracking_disabled",
                "canopy-owned status is disabled (feature tracking.native)",
                403,
            )
        return
    project = await session.get(Project, task.project_id)
    if project is None:
        return
    workflow = await resolve_workflow(session, project)
    column = workflow.column(status) if status is not None else default_column(workflow, task)
    if status is not None and column is None:
        raise TrackingError(
            "unknown_status",
            f"{status!r} is not a column of this project's workflow",
            422,
            columns=[c.name for c in workflow.columns],
        )
    if column is not None:
        record_transition(
            session,
            task,
            column.name,
            category=column.category,
            source=StatusSource.canopy,
            author=author,
        )


# --------------------------------------------------------------------------- #
# Moving cards
# --------------------------------------------------------------------------- #


@dataclass
class MoveOutcome:
    task: Task
    changed: bool
    warnings: list[str] = field(default_factory=list)


async def _scope_leaves(session: AsyncSession, project_ids: list[int]) -> list[Task]:
    if not project_ids:
        return []
    return list(
        (
            await session.execute(
                select(Task).where(
                    col(Task.project_id).in_(project_ids), Task.type != TaskType.summary
                )
            )
        ).scalars().all()
    )


def _rank(task: Task) -> int:
    assert task.id is not None
    return flow.effective_rank(task.board_rank, task.id)


async def place_card(
    session: AsyncSession,
    task: Task,
    scope: list[Task],
    *,
    after_task_id: int | None,
    before_task_id: int | None,
    position: str,
) -> None:
    """Give `task` a rank between its new neighbours in its (new) column. Neighbours the
    caller did not name are looked up in the column; with none named, `position` says top or
    bottom. When two neighbours are adjacent, the whole scope is renumbered once (relative
    order everywhere is kept)."""
    key = (task.status or "").casefold()
    column = sorted(
        (t for t in scope if t.id != task.id and (t.status or "").casefold() == key),
        key=lambda t: (_rank(t), t.id or 0),
    )
    by_id = {t.id: t for t in scope}

    def bounds() -> tuple[int | None, int | None]:
        after = by_id.get(after_task_id) if after_task_id is not None else None
        before = by_id.get(before_task_id) if before_task_id is not None else None
        lo = _rank(after) if after is not None and after.id != task.id else None
        hi = _rank(before) if before is not None and before.id != task.id else None
        if lo is not None and hi is None and before_task_id is None:
            hi = next((_rank(t) for t in column if _rank(t) > lo), None)
        elif hi is not None and lo is None and after_task_id is None:
            lo = next((_rank(t) for t in reversed(column) if _rank(t) < hi), None)
        elif lo is None and hi is None:
            if position == "top":
                hi = _rank(column[0]) if column else None
            else:
                lo = _rank(column[-1]) if column else None
        return lo, hi

    lo, hi = bounds()
    rank = flow.rank_between(lo, hi)
    if rank is None:
        ordered = sorted((t for t in scope if t.id != task.id), key=lambda t: (_rank(t), t.id or 0))
        fresh = flow.renumbered([t.id for t in ordered if t.id is not None])
        for t in ordered:
            assert t.id is not None
            t.board_rank = fresh[t.id]
        lo, hi = bounds()
        rank = flow.rank_between(lo, hi) or flow.RANK_GAP
    task.board_rank = rank


async def move_task(
    session: AsyncSession,
    task: Task,
    *,
    to_status: str | None,
    after_task_id: int | None = None,
    before_task_id: int | None = None,
    position: str = "bottom",
    expected_status: str | None = None,
    author: str | None = None,
    native_enabled: bool = True,
) -> MoveOutcome:
    """Move a card: change its status (canopy-owned tasks only) and/or its place in the
    column. Raises TrackingError (stale | status_externally_owned | native_tracking_disabled |
    unknown_status | wip_limit_reached). Does not commit."""
    # The board labels a status-less card "(no status)"; a client may echo either form.
    expected = "" if expected_status == flow.NO_STATUS else expected_status
    if expected is not None and (task.status or "") != expected:
        raise TrackingError(
            "stale",
            "The card was moved by someone else — refresh the board",
            409,
            current_status=task.status,
        )
    project = await session.get(Project, task.project_id)
    if project is None:
        raise TrackingError("not_found", "Project not found", 404)
    scope_ids = await workflow_scope_project_ids(session, project)
    scope = await _scope_leaves(session, scope_ids)
    warnings: list[str] = []

    changing = to_status is not None and to_status.strip().casefold() != (
        task.status or ""
    ).casefold()
    if changing:
        assert to_status is not None
        if task.status_owner != CANOPY_OWNER:
            raise TrackingError(
                "status_externally_owned",
                f"This task's status is owned by {task.status_owner}; change it there",
                409,
                provider=task.status_owner,
            )
        if not native_enabled:
            raise TrackingError(
                "native_tracking_disabled",
                "canopy-owned status is disabled (feature tracking.native)",
                403,
            )
        workflow = await resolve_workflow(session, project)
        column = workflow.column(to_status)
        if column is None:
            raise TrackingError(
                "unknown_status",
                f"{to_status!r} is not a column of this project's workflow",
                422,
                columns=[c.name for c in workflow.columns],
            )
        if column.wip_limit is not None and workflow.wip_enforcement != WipEnforcement.off:
            key = column.name.casefold()
            wip_ids = await wip_scope_project_ids(session, project, workflow)
            counted = (
                scope
                if set(wip_ids) == set(scope_ids)
                else await _scope_leaves(session, wip_ids)
            )
            in_column = sum(
                1
                for t in counted
                if t.id != task.id
                and (t.status or "").casefold() == key
                and category_of_task(t) not in (StatusCategory.done, StatusCategory.cancelled)
            )
            closed = column.category in (StatusCategory.done, StatusCategory.cancelled)
            if not closed and in_column + 1 > column.wip_limit:
                if workflow.wip_enforcement == WipEnforcement.block:
                    raise TrackingError(
                        "wip_limit_reached",
                        f"{column.name!r} is at its WIP limit of {column.wip_limit}",
                        409,
                        column=column.name,
                        wip_limit=column.wip_limit,
                    )
                warnings.append("wip_limit_exceeded")
        record_transition(
            session,
            task,
            column.name,
            category=column.category,
            source=StatusSource.canopy,
            author=author,
        )

    if changing or after_task_id is not None or before_task_id is not None or to_status is None:
        await place_card(
            session,
            task,
            scope,
            after_task_id=after_task_id,
            before_task_id=before_task_id,
            position=position,
        )
    task.updated_at = utcnow()
    return MoveOutcome(task=task, changed=changing, warnings=warnings)
