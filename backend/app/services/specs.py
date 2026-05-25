"""Spec readiness — pure logic for the spec-driven self-audit.

Readiness = how much of a spec's intent is verified met. Waived criteria are consciously
dropped, so they're excluded from both numerator and denominator.
"""

from app.models.base import CriterionStatus
from app.models.spec import SpecCriterion


def readiness(criteria: list[SpecCriterion]) -> tuple[int, int, float]:
    """Return (met, effective_total, ratio). `ratio` is met / effective_total (0.0 if none)."""
    effective = [c for c in criteria if c.status != CriterionStatus.waived]
    met = sum(1 for c in effective if c.status == CriterionStatus.met)
    total = len(effective)
    ratio = round(met / total, 3) if total else 0.0
    return met, total, ratio
