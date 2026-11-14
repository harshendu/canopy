"""Sprint metrics (pure, unit-testable): sprint burndown, velocity, commitment reliability,
scope change, carry-over and the per-sprint completion forecast (USER_FLOWS §C11).

The caller turns ORM rows into `SprintItem`s — each task's estimate (in the team's unit),
when it joined and left the sprint (from `TaskSprintHistory`) and when it entered a done
category (from `TaskStatusHistory`). Team-level only, never per engineer (the same Goodhart
rule as the delivery metrics, §X).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import date, timedelta

MIN_SPRINTS = 3  # completed sprints needed before velocity / the forecast are meaningful
VELOCITY_WINDOW = 6  # velocity mean/range is taken over the last N completed sprints
DEFAULT_TRIALS = 5_000
_MAX_SPRINTS = 500


def estimate_of(unit: str, story_points: float | None, duration: int) -> float:
    """A task's size in the team's estimate unit (an unestimated task counts 0 points)."""
    if unit == "days":
        return float(max(duration, 0))
    if unit == "points":
        return float(story_points or 0.0)
    return 1.0


def effective_unit(unit: str, story_points: list[float | None]) -> str:
    """Points fall back to a count for a sprint in which no task carries points — velocity
    stays meaningful before anyone estimates."""
    if unit == "points" and not any(p for p in story_points if p):
        return "count"
    return unit


@dataclass(frozen=True)
class SprintItem:
    task_id: int
    estimate: float
    done_on: date | None = None  # last transition into a done category (None = not done)
    added_on: date | None = None  # joined the sprint (None = in it since before the start)
    removed_on: date | None = None  # left the sprint (None = still in it)


def _in_sprint(item: SprintItem, day: date) -> bool:
    joined = item.added_on is None or item.added_on <= day
    left = item.removed_on is not None and item.removed_on <= day
    return joined and not left


def _done_by(item: SprintItem, day: date) -> bool:
    return item.done_on is not None and item.done_on <= day


@dataclass
class BurndownDay:
    day: date
    remaining: float
    ideal: float
    scope_added: float  # estimate that joined after the start, cumulative to this day


def sprint_burndown(
    start: date,
    end: date,
    items: list[SprintItem],
    today: date,
    committed: float | None = None,
) -> list[BurndownDay]:
    """Remaining estimate per day of the sprint against a straight ideal line from the
    commitment (the one captured at start, when given) to zero; work added after the start is
    shown separately as scope."""
    if end < start:
        return []
    if committed is None:
        committed = sum(i.estimate for i in items if _in_sprint(i, start))
    span = max((end - start).days, 1)
    last = min(end, max(today, start))
    out: list[BurndownDay] = []
    day = start
    while day <= last:
        remaining = sum(i.estimate for i in items if _in_sprint(i, day) and not _done_by(i, day))
        added = sum(
            i.estimate
            for i in items
            if i.added_on is not None and start < i.added_on <= day
        )
        ideal = max(committed * (1 - (day - start).days / span), 0.0)
        out.append(
            BurndownDay(day=day, remaining=round(remaining, 2), ideal=round(ideal, 2),
                        scope_added=round(added, 2))
        )
        day += timedelta(days=1)
    return out


@dataclass
class SprintTotals:
    committed: float  # in the sprint when it started
    completed: float  # in the sprint at its end and done by then
    scope_added: float  # joined after the start
    scope_removed: float  # left after the start
    carried_over: float  # in the sprint at its end and not done


def sprint_totals(start: date, end: date, items: list[SprintItem]) -> SprintTotals:
    at_end = [i for i in items if _in_sprint(i, end)]
    return SprintTotals(
        committed=round(sum(i.estimate for i in items if _in_sprint(i, start)), 2),
        completed=round(sum(i.estimate for i in at_end if _done_by(i, end)), 2),
        scope_added=round(
            sum(i.estimate for i in items if i.added_on is not None and i.added_on > start), 2
        ),
        scope_removed=round(
            sum(
                i.estimate
                for i in items
                if i.removed_on is not None and start < i.removed_on <= end
            ),
            2,
        ),
        carried_over=round(sum(i.estimate for i in at_end if not _done_by(i, end)), 2),
    )


@dataclass(frozen=True)
class VelocityPoint:
    sprint_id: int
    name: str
    end_date: date | None
    committed: float
    completed: float

    @property
    def reliability(self) -> float | None:
        """Completed ÷ committed (None when nothing was committed)."""
        return round(self.completed / self.committed, 2) if self.committed > 0 else None


@dataclass
class Velocity:
    points: list[VelocityPoint]
    mean: float | None
    low: float | None
    high: float | None
    mean_reliability: float | None
    sufficient: bool
    reason: str | None = None


def velocity(points: list[VelocityPoint]) -> Velocity:
    """Completed estimate per completed sprint; mean and range over the last six."""
    ordered = sorted(points, key=lambda p: (p.end_date or date.min, p.sprint_id))
    window = ordered[-VELOCITY_WINDOW:]
    done = [p.completed for p in window]
    reliabilities = [r for p in window if (r := p.reliability) is not None]
    sufficient = len(ordered) >= MIN_SPRINTS
    return Velocity(
        points=ordered,
        mean=round(sum(done) / len(done), 2) if done else None,
        low=min(done) if done else None,
        high=max(done) if done else None,
        mean_reliability=(
            round(sum(reliabilities) / len(reliabilities), 2) if reliabilities else None
        ),
        sufficient=sufficient,
        reason=None
        if sufficient
        else f"Velocity needs at least {MIN_SPRINTS} completed sprints ({len(ordered)} so far).",
    )


@dataclass
class SprintForecast:
    sufficient: bool
    remaining: float
    history_sprints: int
    p50_sprints: int | None = None
    p85_sprints: int | None = None
    p50_date: date | None = None
    p85_date: date | None = None
    reason: str | None = None
    trials: int = DEFAULT_TRIALS
    samples: list[float] = field(default_factory=list)


def _percentile(values: list[int], pct: float) -> int:
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return ordered[rank - 1]


def sprint_forecast(
    remaining: float,
    completed_per_sprint: list[float],
    sprint_length_days: int,
    sprint_end: date,
    trials: int = DEFAULT_TRIALS,
    seed: int = 12345,
) -> SprintForecast:
    """How many more sprints to finish `remaining`, sampling (with replacement) from the
    completed estimate of past sprints — the Monte-Carlo forecast run per sprint instead of per
    week. Dates count whole sprints after `sprint_end` (the end of the current/last sprint)."""
    history = len(completed_per_sprint)
    if remaining <= 0:
        return SprintForecast(
            sufficient=True, remaining=0.0, history_sprints=history, p50_sprints=0,
            p85_sprints=0, p50_date=sprint_end, p85_date=sprint_end, trials=trials,
        )
    if history < MIN_SPRINTS or sum(completed_per_sprint) <= 0:
        return SprintForecast(
            sufficient=False,
            remaining=round(remaining, 2),
            history_sprints=history,
            trials=trials,
            reason=(
                f"Not enough sprint history to forecast — needs at least {MIN_SPRINTS} "
                "completed sprints with some work done."
            ),
        )
    rng = random.Random(seed)
    needed: list[int] = []
    for _ in range(trials):
        done = 0.0
        count = 0
        while done < remaining and count < _MAX_SPRINTS:
            done += rng.choice(completed_per_sprint)
            count += 1
        needed.append(count)
    p50 = _percentile(needed, 50)
    p85 = _percentile(needed, 85)
    length = timedelta(days=max(sprint_length_days, 1))
    return SprintForecast(
        sufficient=True,
        remaining=round(remaining, 2),
        history_sprints=history,
        p50_sprints=p50,
        p85_sprints=p85,
        p50_date=sprint_end + length * p50,
        p85_date=sprint_end + length * p85,
        trials=trials,
    )


@dataclass(frozen=True)
class CapacitySpan:
    engineer_id: int
    percent: float  # allocation percent (0-100)
    start: date | None
    end: date | None


@dataclass(frozen=True)
class AvailabilityWindow:
    engineer_id: int
    factor: float  # 0..1 of normal capacity
    start: date | None
    end: date | None


def capacity_person_days(
    start: date,
    end: date,
    allocations: list[CapacitySpan],
    availability: list[AvailabilityWindow],
) -> dict[int, float]:
    """Person-days each engineer can give the sprint: per weekday, their allocation percent
    scaled by the lowest availability factor covering that day (PTO, ramp-up)."""
    out: dict[int, float] = {}
    day = start
    while day <= end:
        if day.weekday() < 5:
            for span in allocations:
                started = span.start is None or span.start <= day
                if started and (span.end is None or day <= span.end):
                    factor = min(
                        (
                            w.factor
                            for w in availability
                            if w.engineer_id == span.engineer_id
                            and (w.start is None or w.start <= day)
                            and (w.end is None or day <= w.end)
                        ),
                        default=1.0,
                    )
                    out[span.engineer_id] = out.get(span.engineer_id, 0.0) + (
                        span.percent / 100.0
                    ) * factor
        day += timedelta(days=1)
    return {k: round(v, 1) for k, v in out.items()}
