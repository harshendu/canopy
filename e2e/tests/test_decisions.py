"""Decisions & fitness functions — USER_FLOWS §G2, §G7."""

import pytest
from selenium.webdriver.common.by import By

from helpers import has_text, open_project_tab, wait_until


@pytest.mark.decisions
def test_decisions_tab_lists_seeded_adr(auth_driver, base_url, seed):
    open_project_tab(auth_driver, base_url, seed["project_a"], "Decisions")
    assert has_text(auth_driver, "Layering: api must not import connectors")


@pytest.mark.decisions
def test_adr_detail_shows_fitness_function(auth_driver, base_url, seed):
    open_project_tab(auth_driver, base_url, seed["project_a"], "Decisions")
    # Expand the ADR row (a clickable button carrying the title) to reveal its detail panel.
    row = wait_until(
        auth_driver,
        lambda d: d.find_element(By.XPATH, "//button[contains(normalize-space(.), 'Layering')]"),
    )
    row.click()
    assert has_text(auth_driver, "Fitness functions")
    # The seeded forbid rule (api -x-> connectors) is shown.
    assert has_text(auth_driver, "must not depend on")
