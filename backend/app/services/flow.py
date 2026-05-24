"""Flow board (Kanban) model (pure, unit-testable).

Groups leaf tasks into status lanes and surfaces the two flow signals that matter day-to-day:
**WIP** per lane (finish before starting) and **aging** — work that has sat in its current
status longer than the team's historical cycle-time P85 (a leading "this is stuck" signal).

Date math (age in status, cycle times) is done by the caller, which has the status history;
this module does the grouping, the P85, and the aging decision so it stays DB-free.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

NO_STATUS = "(no status)"


@dataclass
class BoardTaskInput:
    id: int
    name: str
    status: str | None
    assignee_engineer_id: int | None
    is_done: bool
    age_days: int  # days in the current status
    cycle_days: int | None = None  # for done tasks: created -> done; None otherwise


@dataclass
class BoardTask:
    id: int
    name: str
    status: str
    assignee_engineer_id: int | None
    is_done: bool
    age_days: int
    aging: bool


@dataclass
class BoardLane:
    status: str
    is_done: bool
    wip: int  # count of not-done tasks in the lane
    tasks: list[BoardTask] = field(default_factory=list)


@dataclass
class FlowBoard:
    lanes: list[BoardLane]
    cycle_time_p85_days: int | None
    aging_count: int


def _percentile(values: list[int], pct: float) -> int:
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return ordered[rank - 1]


def build_board(tasks: list[BoardTaskInput]) -> FlowBoard:
    cycle_samples = [t.cycle_days for t in tasks if t.cycle_days is not None]
    p85 = _percentile(cycle_samples, 85) if cycle_samples else None

    lanes: dict[str, BoardLane] = {}
    lane_order: list[str] = []
    aging_count = 0
    for t in tasks:
        label = t.status if t.status else NO_STATUS
        aging = (not t.is_done) and p85 is not None and t.age_days > p85
        if aging:
            aging_count += 1
        if label not in lanes:
            lanes[label] = BoardLane(status=label, is_done=t.is_done, wip=0)
            lane_order.append(label)
        lane = lanes[label]
        # A lane is "done" only if all its tasks are done (mixed statuses keep it active).
        lane.is_done = lane.is_done and t.is_done
        if not t.is_done:
            lane.wip += 1
        lane.tasks.append(
            BoardTask(
                id=t.id,
                name=t.name,
                status=label,
                assignee_engineer_id=t.assignee_engineer_id,
                is_done=t.is_done,
                age_days=t.age_days,
                aging=aging,
            )
        )

    # Active lanes first (in first-seen order), done lanes last.
    ordered = sorted(lane_order, key=lambda s: (lanes[s].is_done, lane_order.index(s)))
    return FlowBoard(
        lanes=[lanes[s] for s in ordered],
        cycle_time_p85_days=p85,
        aging_count=aging_count,
    )
