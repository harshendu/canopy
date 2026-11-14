"""Project tracking — USER_FLOWS §C12: switch a native project to mirrored from a MOCKED Jira.

A Jira connection is pointed at the local mock (no external calls) without naming a project, so
the project starts native. Through the project's Tracking view the switch is previewed (the plan
lists what happens to each existing task), applied, and the first sync imports the mock's issues
into the now-mirrored project. The mock only serves the issue search; the tracker's statuses and
changelog answer 501 and are best-effort, so the sync still lands."""

import time

import pytest

from helpers import (
    accept_confirm,
    api_create_project,
    api_create_task,
    api_post,
    button_with_text,
    has_text,
    heading,
    input_with_label,
    open_project_view,
    radio_with_label,
    table_cell,
)


def _unique_key(prefix: str) -> str:
    return f"{prefix}{int(time.time() * 1000) % 1_000_000}"


@pytest.mark.connectors
def test_switch_native_project_to_mirrored_jira(auth_driver, base_url, token, mock_jira):
    key = _unique_key("TRK")
    proj = api_create_project(base_url, token, key, f"Tracking {key}", tracking_mode="native")
    api_create_task(base_url, token, proj["id"], "Canopy-only spike")
    connection = f"Mock Jira {key}"
    api_post(base_url, token, "/connectors/connections", {
        "provider": "jira", "name": connection, "token": "mock-token",
        "config": {"base_url": mock_jira.base_url, "email": "e2e@example.com"},
    })

    open_project_view(auth_driver, base_url, proj["id"], "Integrations", "Tracking")
    assert heading(auth_driver, "Native — canopy owns every status")

    # Target → scope + strategy → preview: nothing changes until the plan is applied.
    button_with_text(auth_driver, "Switch tracking…").click()
    radio_with_label(auth_driver, connection).click()
    button_with_text(auth_driver, "Next").click()
    project_key = input_with_label(auth_driver, "Project key")
    project_key.clear()
    project_key.send_keys("MOCK")
    radio_with_label(auth_driver, "Keep separate").click()
    button_with_text(auth_driver, "Preview").click()
    assert has_text(auth_driver, "Nothing has changed yet")
    assert table_cell(auth_driver, "Canopy-only spike")  # the plan table: it stays canopy-owned
    assert heading(auth_driver, "Native — canopy owns every status")

    # Apply (it asks first): the binding is made and the first sync imports the mock's issues.
    button_with_text(auth_driver, "Apply switch…").click()
    assert "Mirrored from Jira" in accept_confirm(auth_driver)
    assert has_text(auth_driver, "Switched — Mirrored from Jira.")
    assert has_text(auth_driver, "First sync from Jira: 2 created")
    button_with_text(auth_driver, "Done").click()
    assert heading(auth_driver, "Mirrored from Jira")
    assert has_text(auth_driver, "canopy owns 1 · Jira owns 2")
    assert has_text(auth_driver, connection)  # the binding card names the connection
