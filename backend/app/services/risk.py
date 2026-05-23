"""Project risk scoring (pure, unit-testable).

A leading-indicator companion to the lagging Alerts digest. Turns raw project signals
into a 0-100 risk score with a drillable breakdown across four families:

  * **schedule**     — deadline misses, baseline drift, critical-path float consumption
  * **capacity**     — engineer-week over-allocation
  * **architecture** — deferred decisions past their decide-by, decisions stuck in
                       discussion (both from the decisions slice)
  * **quality**      — build failures + open incidents (from §J8 observability events).
                       When a project has NO observability wired, we can't measure quality,
                       so the family scores that **missing coverage** as an explicit risk and
                       the report's `confidence` drops to "low" — a blind project is never
                       silently treated as safer (the old behaviour excluded the family and
                       renormalised, which made unobserved projects look lower-risk).

The score is deliberately opinionated and arguable — its job is to start a conversation,
not to be precise. All weights/thresholds live here so they're easy to tune and test.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Family weights for the overall score. Every family is always scored (total weight 1.0);
# the quality family scores the absence of observability as its own risk rather than
# dropping out, so the overall is never silently renormalised in a blind project's favour.
SCHEDULE_WEIGHT = 0.35
CAPACITY_WEIGHT = 0.20
ARCHITECTURE_WEIGHT = 0.25
QUALITY_WEIGHT = 0.20

# With no CI/observability events we are blind to quality. That blindness is itself a
# moderate, named risk (and forces confidence to "low") — not an excluded family.
UNMEASURED_QUALITY_SCORE = 40


def _cap(value: float) -> int:
    return max(0, min(100, round(value)))


@dataclass
class RiskSignals:
    # schedule
    deadline_violations: list[tuple[int, str]] = field(default_factory=list)  # (task_id, name)
    drifted_tasks: list[tuple[int, str]] = field(default_factory=list)  # (task_id, name)
    critical_task_count: int = 0
    critical_zero_float_count: int = 0
    # capacity
    over_allocations: list[tuple[str, str, float]] = field(
        default_factory=list
    )  # (engineer_name, week_iso, percent)
    # architecture (decisions + drift)
    deferred_overdue: list[tuple[int, str]] = field(default_factory=list)  # (number, title)
    stuck_decisions: list[tuple[int, str]] = field(default_factory=list)  # (number, title)
    drift_score: int = 0  # the §N drift score folds into architecture risk
    # quality (from §J8 CI/observability events)
    quality_available: bool = False  # True once observability events exist for the project
    build_failures: int = 0
    open_incidents: int = 0


@dataclass
class RiskIndicator:
    key: str
    label: str
    score: int
    summary: str
    details: list[str]


@dataclass
class RiskFamily:
    key: str
    label: str
    available: bool
    score: int
    weight: float
    indicators: list[RiskIndicator]


@dataclass
class RiskReport:
    score: int
    level: str  # low | moderate | high | critical
    families: list[RiskFamily]
    confidence: str = "high"  # high | low — how much of the picture we can actually measure
    confidence_note: str = ""


def _family_score(indicators: list[RiskIndicator]) -> int:
    if not indicators:
        return 0
    return _cap(sum(i.score for i in indicators) / len(indicators))


def _level(score: int) -> str:
    if score < 20:
        return "low"
    if score < 45:
        return "moderate"
    if score < 70:
        return "high"
    return "critical"


def _schedule_family(s: RiskSignals) -> RiskFamily:
    indicators = [
        RiskIndicator(
            key="deadline_violations",
            label="Deadline misses",
            score=_cap(len(s.deadline_violations) * 25),
            summary=f"{len(s.deadline_violations)} task(s) past their deadline",
            details=[f"#{tid} {name}" for tid, name in s.deadline_violations],
        ),
        RiskIndicator(
            key="schedule_variance",
            label="Schedule variance vs baseline",
            score=_cap(len(s.drifted_tasks) * 15),
            summary=f"{len(s.drifted_tasks)} task(s) drifted from baseline",
            details=[f"#{tid} {name}" for tid, name in s.drifted_tasks],
        ),
        RiskIndicator(
            key="critical_float",
            label="Critical-path float consumption",
            score=_cap(
                (s.critical_zero_float_count / s.critical_task_count) * 100
                if s.critical_task_count
                else 0
            ),
            summary=(
                f"{s.critical_zero_float_count}/{s.critical_task_count} critical tasks "
                "have zero float"
            ),
            details=[],
        ),
    ]
    return RiskFamily(
        key="schedule",
        label="Schedule risk",
        available=True,
        score=_family_score(indicators),
        weight=SCHEDULE_WEIGHT,
        indicators=indicators,
    )


def _capacity_family(s: RiskSignals) -> RiskFamily:
    indicators = [
        RiskIndicator(
            key="over_allocation",
            label="Over-allocation",
            score=_cap(len(s.over_allocations) * 20),
            summary=f"{len(s.over_allocations)} engineer-week(s) over 100%",
            details=[
                f"{name} at {pct:.0f}% in week of {week}"
                for name, week, pct in s.over_allocations
            ],
        ),
    ]
    return RiskFamily(
        key="capacity",
        label="Capacity risk",
        available=True,
        score=_family_score(indicators),
        weight=CAPACITY_WEIGHT,
        indicators=indicators,
    )


def _architecture_family(s: RiskSignals) -> RiskFamily:
    indicators = [
        RiskIndicator(
            key="deferred_overdue",
            label="Deferred decisions past decide-by",
            score=_cap(len(s.deferred_overdue) * 34),
            summary=f"{len(s.deferred_overdue)} deferred decision(s) past decide-by",
            details=[f"ADR-{num:04d} {title}" for num, title in s.deferred_overdue],
        ),
        RiskIndicator(
            key="stuck_decisions",
            label="Decisions stuck in discussion",
            score=_cap(len(s.stuck_decisions) * 25),
            summary=f"{len(s.stuck_decisions)} decision(s) stuck > 14 days",
            details=[f"ADR-{num:04d} {title}" for num, title in s.stuck_decisions],
        ),
        RiskIndicator(
            key="drift",
            label="Architecture drift",
            score=_cap(s.drift_score),
            summary=f"Drift score {s.drift_score}",
            details=[],
        ),
    ]
    return RiskFamily(
        key="architecture",
        label="Architecture risk",
        available=True,
        score=_family_score(indicators),
        weight=ARCHITECTURE_WEIGHT,
        indicators=indicators,
    )


def _quality_family(s: RiskSignals) -> RiskFamily:
    # Fed by §J8 CI/observability events. With no such events we can't measure quality, so
    # the family carries an explicit "observability coverage" risk (and the report drops to
    # low confidence) instead of dropping out and making the project look safer.
    if s.quality_available:
        indicators = [
            RiskIndicator(
                key="build_failures",
                label="Build failures",
                score=_cap(s.build_failures * 15),
                summary=f"{s.build_failures} build failure event(s)",
                details=[],
            ),
            RiskIndicator(
                key="open_incidents",
                label="Open incidents",
                score=_cap(s.open_incidents * 30),
                summary=f"{s.open_incidents} open incident(s)",
                details=[],
            ),
        ]
    else:
        indicators = [
            RiskIndicator(
                key="observability_coverage",
                label="Observability coverage",
                score=UNMEASURED_QUALITY_SCORE,
                summary="No observability wired — quality risk is unmeasured",
                details=[
                    "No deploy / build-failure / incident events recorded for this project.",
                    "Wire CI/observability (POST /webhooks/events, or the Activity tab) so "
                    "build failures and incidents feed this score.",
                ],
            ),
        ]
    return RiskFamily(
        key="quality",
        label="Quality risk",
        available=True,  # always scored — missing coverage is itself a signal
        score=_family_score(indicators),
        weight=QUALITY_WEIGHT,
        indicators=indicators,
    )


def compute_risk(signals: RiskSignals) -> RiskReport:
    families = [
        _schedule_family(signals),
        _capacity_family(signals),
        _architecture_family(signals),
        _quality_family(signals),
    ]
    available = [f for f in families if f.available]
    total_weight = sum(f.weight for f in available)
    overall = (
        _cap(sum(f.score * f.weight for f in available) / total_weight)
        if total_weight
        else 0
    )
    if signals.quality_available:
        confidence, note = "high", "All risk families have data."
    else:
        confidence, note = "low", (
            "Quality is unmeasured — no observability events for this project. The score "
            "reflects missing coverage, not a clean bill of health; wire CI/observability "
            "to raise confidence."
        )
    return RiskReport(
        score=overall,
        level=_level(overall),
        families=families,
        confidence=confidence,
        confidence_note=note,
    )
