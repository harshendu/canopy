from app.models.base import RiskGrade
from app.services.metadata import (
    estimate_spread,
    exposure_level,
    is_high_uncertainty,
    normalize_tags,
    pert_mean,
    risk_exposure,
    risk_grade_value,
)


def test_normalize_tags_strips_lowercases_dedupes_preserving_order():
    assert normalize_tags([" Backend ", "API", "api", "", "  ", "Backend"]) == [
        "backend",
        "api",
    ]


def test_normalize_tags_empty():
    assert normalize_tags([]) == []


def test_pert_mean():
    assert pert_mean(2, 5, 14) == (2 + 4 * 5 + 14) / 6


def test_estimate_spread():
    assert estimate_spread(2, 9) == 7


def test_is_high_uncertainty_when_spread_at_least_likely():
    assert is_high_uncertainty(2, 5, 12) is True  # spread 10 >= likely 5
    assert is_high_uncertainty(4, 5, 7) is False  # spread 3 < likely 5


def test_is_high_uncertainty_zero_likely():
    assert is_high_uncertainty(1, 0, 3) is True
    assert is_high_uncertainty(2, 0, 2) is False


def test_risk_grade_value():
    assert risk_grade_value(RiskGrade.low) == 1
    assert risk_grade_value(RiskGrade.medium) == 2
    assert risk_grade_value(RiskGrade.high) == 3


def test_risk_exposure_is_probability_times_impact():
    assert risk_exposure(RiskGrade.high, RiskGrade.high) == 9
    assert risk_exposure(RiskGrade.low, RiskGrade.medium) == 2


def test_exposure_level_bands():
    assert exposure_level(1) == "low"
    assert exposure_level(2) == "low"
    assert exposure_level(3) == "moderate"
    assert exposure_level(4) == "moderate"
    assert exposure_level(6) == "high"
    assert exposure_level(9) == "critical"
