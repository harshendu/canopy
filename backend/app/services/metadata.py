"""Delivery-metadata helpers (pure, unit-testable).

Small building blocks shared by the API routes and the risk scorer: tag normalisation,
3-point (PERT) estimate maths, and risk-register probability/impact grading. Kept here so
the logic is tested in isolation and the routes stay thin.
"""

from __future__ import annotations

from app.models.base import RiskGrade

# A task's estimate is "high uncertainty" when the optimistic→pessimistic spread is at
# least as large as the most-likely estimate itself (i.e. pessimistic >= ~2x optimistic).
HIGH_UNCERTAINTY_SPREAD_RATIO = 1.0

_GRADE_VALUES: dict[RiskGrade, int] = {
    RiskGrade.low: 1,
    RiskGrade.medium: 2,
    RiskGrade.high: 3,
}


def normalize_tags(raw: list[str]) -> list[str]:
    """Strip, lowercase, drop empties, and dedupe while preserving first-seen order."""
    seen: set[str] = set()
    out: list[str] = []
    for tag in raw:
        cleaned = tag.strip().lower()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            out.append(cleaned)
    return out


def pert_mean(optimistic: int, likely: int, pessimistic: int) -> float:
    """The PERT expected value: (O + 4M + P) / 6."""
    return (optimistic + 4 * likely + pessimistic) / 6


def estimate_spread(optimistic: int, pessimistic: int) -> int:
    """The estimate uncertainty band, in working days."""
    return pessimistic - optimistic


def is_high_uncertainty(optimistic: int, likely: int, pessimistic: int) -> bool:
    """True when the estimate spread is wide relative to the most-likely estimate."""
    if likely <= 0:
        return estimate_spread(optimistic, pessimistic) > 0
    return estimate_spread(optimistic, pessimistic) >= likely * HIGH_UNCERTAINTY_SPREAD_RATIO


def risk_grade_value(grade: RiskGrade) -> int:
    """Map an ordinal probability/impact grade to 1..3."""
    return _GRADE_VALUES[grade]


def risk_exposure(probability: RiskGrade, impact: RiskGrade) -> int:
    """Risk exposure = probability x impact, on a 1..9 scale."""
    return risk_grade_value(probability) * risk_grade_value(impact)


def exposure_level(exposure: int) -> str:
    """Band a 1..9 exposure onto the shared risk vocabulary (low|moderate|high|critical)."""
    if exposure < 3:
        return "low"
    if exposure < 6:
        return "moderate"
    if exposure < 9:
        return "high"
    return "critical"
