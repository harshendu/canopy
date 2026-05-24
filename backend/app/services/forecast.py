"""Probabilistic delivery forecast (pure, unit-testable).

A throughput-based Monte-Carlo forecast: how many calendar weeks to finish the remaining
backlog, sampling (with replacement) from the team's *historical* weekly throughput — the
count of items completed each past week, including slow/zero weeks. Reports P50/P85 completion
dates to sit alongside the deterministic CPM date.

This is the honest answer for knowledge work, where single-point estimates are
precise-but-wrong: it needs no per-task estimates, only a count of remaining items and a
history of weekly throughput. The distribution (not any single value) is the point.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import date, timedelta

DEFAULT_TRIALS = 10_000
MIN_HISTORY_WEEKS = 3
_MAX_WEEKS = 1000  # safety cap for mostly-zero throughput (terminates anyway since sum > 0)


@dataclass
class ForecastResult:
    sufficient: bool
    remaining_items: int
    history_weeks: int
    trials: int
    reason: str | None = None
    p50_weeks: int | None = None
    p85_weeks: int | None = None
    p50_date: date | None = None
    p85_date: date | None = None


def weekly_throughput(done_dates: list[date], today: date) -> list[int]:
    """Items completed per ISO week, from the first completion's week through `today`'s week.

    Includes zero-throughput weeks — stall weeks are real signal the forecast must account for."""
    if not done_dates:
        return []
    start = min(done_dates)
    week = start - timedelta(days=start.weekday())  # Monday of the first completion
    last = today - timedelta(days=today.weekday())
    counts: list[int] = []
    while week <= last:
        week_end = week + timedelta(days=6)
        counts.append(sum(1 for d in done_dates if week <= d <= week_end))
        week += timedelta(days=7)
    return counts


def _percentile(values: list[int], pct: float) -> int:
    """Nearest-rank percentile of a non-empty list."""
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return ordered[rank - 1]


def monte_carlo_forecast(
    remaining_items: int,
    throughput: list[int],
    today: date,
    trials: int = DEFAULT_TRIALS,
    seed: int = 12345,
) -> ForecastResult:
    """Simulate finishing `remaining_items` by drawing weekly throughput samples."""
    history_weeks = len(throughput)
    if remaining_items <= 0:
        return ForecastResult(
            sufficient=True,
            remaining_items=0,
            history_weeks=history_weeks,
            trials=trials,
            p50_weeks=0,
            p85_weeks=0,
            p50_date=today,
            p85_date=today,
        )
    if history_weeks < MIN_HISTORY_WEEKS or sum(throughput) <= 0:
        return ForecastResult(
            sufficient=False,
            remaining_items=remaining_items,
            history_weeks=history_weeks,
            trials=trials,
            reason=(
                "Not enough completed-work history to forecast — needs at least "
                f"{MIN_HISTORY_WEEKS} weeks with some throughput (sync Jira status, or mark "
                "tasks done, to build a trend)."
            ),
        )

    rng = random.Random(seed)
    weeks_to_finish: list[int] = []
    for _ in range(trials):
        done = 0
        weeks = 0
        while done < remaining_items and weeks < _MAX_WEEKS:
            done += rng.choice(throughput)
            weeks += 1
        weeks_to_finish.append(weeks)

    p50 = _percentile(weeks_to_finish, 50)
    p85 = _percentile(weeks_to_finish, 85)
    return ForecastResult(
        sufficient=True,
        remaining_items=remaining_items,
        history_weeks=history_weeks,
        trials=trials,
        p50_weeks=p50,
        p85_weeks=p85,
        p50_date=today + timedelta(weeks=p50),
        p85_date=today + timedelta(weeks=p85),
    )
