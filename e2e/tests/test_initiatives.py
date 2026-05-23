"""Initiatives — USER_FLOWS §R: list/create, the rollup cockpit, cross-project critical path."""

import time

import pytest

from helpers import button_with_text, by_placeholder, has_text, nav_link, wait_for_path


@pytest.mark.initiatives
def test_create_initiative_via_ui(auth_driver, base_url):
    nav_link(auth_driver, "Initiatives").click()
    wait_for_path(auth_driver, "/initiatives")
    key = f"NEW{int(time.time() * 1000) % 1_000_000}"
    name = f"Initiative {key}"
    by_placeholder(auth_driver, "KEY").send_keys(key)
    by_placeholder(auth_driver, "Initiative name").send_keys(name)
    button_with_text(auth_driver, "Add").click()
    assert has_text(auth_driver, name), "new initiative not listed"


@pytest.mark.initiatives
def test_initiative_cockpit_rolls_up_subprojects(auth_driver, base_url, seed):
    auth_driver.get(f"{base_url}/initiatives/{seed['initiative_id']}")
    # Outcome + the rolled-up sections render.
    assert has_text(auth_driver, "Q3 Platform")
    assert has_text(auth_driver, "Ship the multi-tenant platform")
    assert has_text(auth_driver, "Sub-projects")
    assert has_text(auth_driver, "Risk (worst)")
    # Both sub-projects appear as cards.
    assert has_text(auth_driver, seed["project_a_name"])
    assert has_text(auth_driver, seed["project_b_name"])


@pytest.mark.initiatives
def test_cross_project_critical_path_panel(auth_driver, base_url, seed):
    auth_driver.get(f"{base_url}/initiatives/{seed['initiative_id']}")
    # Seed wired an Alpha->Beta hand-off, so the cross-project critical path spans projects.
    assert has_text(auth_driver, "Cross-project critical path")
    assert has_text(auth_driver, "hand-off")
