"""Projects & cockpit — USER_FLOWS §B2 (create), §B3 (open the tabbed cockpit)."""

import time

import pytest

from helpers import (
    api_create_project,
    api_token,
    button_with_text,
    by_placeholder,
    has_text,
    tab,
    wait_for_path,
    wait_until,
)


def _unique_key(prefix: str = "E2E") -> str:
    return f"{prefix}{int(time.time() * 1000) % 1_000_000}"


@pytest.mark.projects
def test_create_project_via_ui(auth_driver, base_url):
    key = _unique_key()
    name = f"E2E Project {key}"
    by_placeholder(auth_driver, "KEY").send_keys(key)
    by_placeholder(auth_driver, "Project name").send_keys(name)
    button_with_text(auth_driver, "Add").click()
    # The new project shows up in the list (cache invalidated + refetched).
    assert has_text(auth_driver, name), f"created project '{name}' not listed"


@pytest.mark.projects
def test_open_project_shows_cockpit_tabs(auth_driver, base_url, credentials):
    # Arrange a project via the API, then open it through the UI.
    token = api_token(base_url, *credentials)
    key = _unique_key("OPEN")
    proj = api_create_project(base_url, token, key, f"Cockpit {key}")
    auth_driver.get(f"{base_url}/projects/{proj['id']}")
    # The tabbed workspace renders its tab strip.
    for label in ("Gantt", "Dependencies", "Risk", "Decisions"):
        assert tab(auth_driver, label).is_displayed(), f"missing tab: {label}"
    # Header shows the project name.
    assert has_text(auth_driver, f"Cockpit {key}")


@pytest.mark.projects
def test_project_card_links_into_cockpit(auth_driver, base_url, credentials):
    token = api_token(base_url, *credentials)
    key = _unique_key("LINK")
    proj = api_create_project(base_url, token, key, f"Linked {key}")
    auth_driver.get(f"{base_url}/projects")
    link = wait_until(
        auth_driver,
        lambda d: d.find_element("xpath", f"//a[contains(@href, '/projects/{proj['id']}')]"),
    )
    link.click()
    wait_for_path(auth_driver, f"/projects/{proj['id']}")
    assert tab(auth_driver, "Gantt").is_displayed()
