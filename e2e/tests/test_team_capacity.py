"""Team & capacity — USER_FLOWS §F: roster, add engineer, org-wide + per-project capacity."""

import time

import pytest

from helpers import button_with_text, by_placeholder, has_text, nav_link, open_project_tab, wait_for_path


@pytest.mark.team
def test_team_page_lists_seeded_engineers_and_org_capacity(auth_driver, base_url, seed):
    nav_link(auth_driver, "Team").click()
    wait_for_path(auth_driver, "/team")
    assert has_text(auth_driver, "Ada Lovelace")
    assert has_text(auth_driver, "Alan Turing")
    # Org-wide capacity grid (cross-project) renders.
    assert has_text(auth_driver, "Capacity across all projects")


@pytest.mark.team
def test_add_engineer_via_ui(auth_driver, base_url):
    nav_link(auth_driver, "Team").click()
    wait_for_path(auth_driver, "/team")
    name = f"Grace Hopper {int(time.time() * 1000) % 1_000_000}"
    by_placeholder(auth_driver, "Name").send_keys(name)
    # The engineer "Add" button is the first Add on the page (before the role form).
    button_with_text(auth_driver, "Add").click()
    assert has_text(auth_driver, name), "new engineer not listed"


@pytest.mark.capacity
def test_project_capacity_tab(auth_driver, base_url, seed):
    open_project_tab(auth_driver, base_url, seed["project_a"], "Capacity")
    # The allocate form + heatmap render (seed allocated Ada to this project).
    assert has_text(auth_driver, "Allocate")
