"""Flow board (Kanban) model (pure, unit-testable).

Groups leaf tasks into status lanes and surfaces the two flow signals that matter day-to-day:
**WIP** per lane (finish before starting) and **aging** — work that has sat in its current
status longer than the team's historical cycle-time P85 (a leading "this is stuck" signal).

With `columns` (a workflow: ordered statuses, each with a category and an optional WIP limit)
the board shows every column in order, empty ones included, and appends any status found on a
task that the workflow does not name after the last column of the same category. Without
`columns` it falls back to lanes-from-statuses (first-seen order, done lanes last).

Also here: card ordering (`effective_rank` / `rank_between`) and the per-task flow facts
(age in status, cycle time, lead time) that the board, burndown, forecast and delivery metrics
share. Date math needs the status history, which the caller gathers; this module stays DB-free.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

NO_STATUS = "(no status)"

# Category values (mirrors `app.models.base.StatusCategory`; kept as strings so this stays pure).
TODO = "todo"
IN_PROGRESS = "in_progress"
DONE = "done"
CANCELLED = "cancelled"
_CLOSED = frozenset({DONE, CANCELLED})

# Board ranks: an unranked task (rank 0) sorts by id at this spacing, and a drop between two
# cards takes the midpoint of their ranks — when no gap is left, the caller renumbers.
RANK_GAP = 1024


@dataclass
class ColumnDef:
    name: str
    category: str
    position: int
    wip_limit: int | None = None


@dataclass
class BoardTaskInput:
    id: int
    name: str
    status: str | None
    assignee_engineer_id: int | None
    is_done: bool
    age_days: int  # days in the current status
    cycle_days: int | None = None  # for done tasks: started -> done; None otherwise
    category: str | None = None  # the resolved status category (None = derive from is_done)
    rank: int = 0  # effective rank (see `effective_rank`)


@dataclass
class BoardTask:
    id: int
    name: str
    status: str
    assignee_engineer_id: int | None
    is_done: bool
    age_days: int
    aging: bool
    category: str | None = None
    rank: int = 0


@dataclass
class BoardLane:
    status: str
    is_done: bool
    wip: int  # count of cards that are not done or cancelled
    tasks: list[BoardTask] = field(default_factory=list)
    category: str | None = None
    position: int = 0
    wip_limit: int | None = None
    in_workflow: bool = True  # False = a status found on a task that the workflow doesn't name

    @property
    def over_limit(self) -> bool:
        return self.wip_limit is not None and self.wip > self.wip_limit


@dataclass
class FlowBoard:
    lanes: list[BoardLane]
    cycle_time_p85_days: int | None
    aging_count: int


def _percentile(values: list[int], pct: float) -> int:
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return ordered[rank - 1]


def _is_open(t: BoardTaskInput) -> bool:
    """Counts as work in progress on its lane (not done, not cancelled)."""
    if t.category is not None:
        return t.category not in _CLOSED
    return not t.is_done


def _lanes_from_statuses(tasks: list[BoardTaskInput]) -> list[BoardLane]:
    lanes: dict[str, BoardLane] = {}
    order: list[str] = []
    for t in tasks:
        label = t.status if t.status else NO_STATUS
        if label not in lanes:
            lanes[label] = BoardLane(status=label, is_done=t.is_done, wip=0, category=t.category)
            order.append(label)
        lane = lanes[label]
        # A lane is "done" only if all its tasks are done (mixed statuses keep it active).
        lane.is_done = lane.is_done and t.is_done
    # Active lanes first (in first-seen order), done lanes last.
    ordered = sorted(order, key=lambda s: (lanes[s].is_done, order.index(s)))
    for position, label in enumerate(ordered):
        lanes[label].position = position
    return [lanes[s] for s in ordered]


def _lanes_from_columns(
    tasks: list[BoardTaskInput], columns: list[ColumnDef]
) -> list[BoardLane]:
    ordered_columns = sorted(columns, key=lambda c: c.position)
    lanes: list[BoardLane] = [
        BoardLane(
            status=c.name,
            is_done=c.category == DONE,
            wip=0,
            category=c.category,
            wip_limit=c.wip_limit,
        )
        for c in ordered_columns
    ]
    known = {lane.status.casefold() for lane in lanes}
    for t in tasks:
        label = t.status if t.status else NO_STATUS
        if label.casefold() in known:
            continue
        known.add(label.casefold())
        category = t.category if t.status else None
        extra = BoardLane(
            status=label,
            is_done=category == DONE,
            wip=0,
            category=category,
            in_workflow=False,
        )
        if label == NO_STATUS:
            lanes.insert(0, extra)  # the unsorted inbox goes first
            continue
        # After the last lane of the same category, else at the end.
        same = [i for i, lane in enumerate(lanes) if lane.category == category]
        lanes.insert(same[-1] + 1 if same else len(lanes), extra)
    for position, lane in enumerate(lanes):
        lane.position = position
    return lanes


def build_board(
    tasks: list[BoardTaskInput], columns: list[ColumnDef] | None = None
) -> FlowBoard:
    cycle_samples = [t.cycle_days for t in tasks if t.cycle_days is not None]
    p85 = _percentile(cycle_samples, 85) if cycle_samples else None

    lanes = _lanes_from_columns(tasks, columns) if columns else _lanes_from_statuses(tasks)
    by_label = {lane.status.casefold(): lane for lane in lanes}

    aging_count = 0
    for t in sorted(tasks, key=lambda x: (x.rank, x.id)):
        label = t.status if t.status else NO_STATUS
        lane = by_label[label.casefold()]
        is_open = _is_open(t)
        aging = is_open and p85 is not None and t.age_days > p85
        if aging:
            aging_count += 1
        if is_open:
            lane.wip += 1
        lane.tasks.append(
            BoardTask(
                id=t.id,
                name=t.name,
                status=lane.status,
                assignee_engineer_id=t.assignee_engineer_id,
                is_done=t.is_done,
                age_days=t.age_days,
                aging=aging,
                category=t.category,
                rank=t.rank,
            )
        )
    return FlowBoard(lanes=lanes, cycle_time_p85_days=p85, aging_count=aging_count)


# --------------------------------------------------------------------------- #
# Card order
# --------------------------------------------------------------------------- #


def effective_rank(board_rank: int, task_id: int) -> int:
    """A task that was never placed (rank 0) sorts by creation order."""
    return board_rank if board_rank != 0 else task_id * RANK_GAP


def rank_between(lo: int | None, hi: int | None) -> int | None:
    """A rank strictly between `lo` and `hi` (None = open end), or None when the two are
    adjacent and the column must be renumbered first. Never returns 0 (= unranked)."""
    if lo is None and hi is None:
        return RANK_GAP
    if lo is None:
        assert hi is not None
        candidate = hi - RANK_GAP
        return candidate if candidate != 0 else candidate - 1
    if hi is None:
        candidate = lo + RANK_GAP
        return candidate if candidate != 0 else candidate + 1
    if hi - lo < 2:
        return None
    mid = (lo + hi) // 2
    if mid != 0:
        return mid
    for candidate in (mid + 1, mid - 1):
        if lo < candidate < hi and candidate != 0:
            return candidate
    return None


def renumbered(ids_in_order: list[int]) -> dict[int, int]:
    """Fresh, evenly spaced ranks for cards in their current order."""
    return {task_id: (index + 1) * RANK_GAP for index, task_id in enumerate(ids_in_order)}


# --------------------------------------------------------------------------- #
# Per-task flow facts (shared by board, burndown, forecast, delivery metrics)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class HistoryPoint:
    to_status: str | None
    category: str | None  # the category stamped on the row (or derived for legacy rows)
    at: date


@dataclass(frozen=True)
class FlowFacts:
    age_days: int  # days in the current status
    done_on: date | None  # the last transition into a done status
    cycle_days: int | None  # first start (in_progress) -> last done; created when never started
    lead_days: int | None  # created -> last done


def flow_facts(
    status: str | None,
    created: date,
    updated: date,
    history: list[HistoryPoint],
    today: date,
) -> FlowFacts:
    # When did it enter its current status? The latest matching transition; else the task's last
    # update, not created_at — a months-old task freshly moved but synced without its history
    # would otherwise read as aging-for-months, a false "stuck" signal.
    entered = max((h.at for h in history if h.to_status == status), default=updated)
    done_dates = [h.at for h in history if h.category == DONE]
    done_on = max(done_dates) if done_dates else None
    started = min((h.at for h in history if h.category == IN_PROGRESS), default=created)
    if done_on is not None and started > done_on:
        started = created
    return FlowFacts(
        age_days=max(0, (today - entered).days),
        done_on=done_on,
        cycle_days=max(0, (done_on - started).days) if done_on is not None else None,
        lead_days=max(0, (done_on - created).days) if done_on is not None else None,
    )


def completion_dates(rows: list[tuple[int, HistoryPoint]]) -> list[date]:
    """One completion date per task — its LAST transition into done — sorted ascending. A task
    that bounced Done→Reopened→Done counts once, not once per transition."""
    latest: dict[int, date] = {}
    for task_id, point in rows:
        if point.category == DONE and (task_id not in latest or point.at > latest[task_id]):
            latest[task_id] = point.at
    return sorted(latest.values())
