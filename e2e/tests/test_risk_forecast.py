"""Risk dashboard + probabilistic forecast — USER_FLOWS §Q, §C8."""

import pytest

from helpers import has_text, open_project_tab


@pytest.mark.risk
def test_risk_tab_renders_score(auth_driver, base_url, seed):
    open_project_tab(auth_driver, base_url, seed["project_a"], "Risk")
    assert has_text(auth_driver, "Risk score")
    # The lagging alerts digest lives inside the Risk tab; the seeded blocker shows there.
    assert has_text(auth_driver, "Alerts")


@pytest.mark.forecast
def test_gantt_shows_probabilistic_forecast(auth_driver, base_url, seed):
    # The Gantt tab carries the Monte-Carlo forecast card next to the CPM schedule.
    auth_driver.get(f"{base_url}/projects/{seed['project_a']}")
    assert has_text(auth_driver, "Probabilistic forecast")
