"""Connectors — USER_FLOWS §J: manage connections, and sync from a MOCKED Jira.

The Jira sync exercises the real connector code path against a local mock server (no external
calls): a connection is pointed at the mock, a full sync is triggered, and the imported issues
must appear as tasks on the project's Gantt."""

import time

import pytest

from helpers import api_create_project, api_post, has_text, nav_link, wait_for_path


@pytest.mark.connectors
def test_connectors_page_lists_a_connection(auth_driver, base_url, token):
    api_post(base_url, token, "/connectors/connections", {
        "provider": "github", "name": "Acme repo", "token": "ghp_mock",
        "config": {"owner": "acme", "repo": "platform"},
    })
    nav_link(auth_driver, "Connectors").click()
    wait_for_path(auth_driver, "/connectors")
    assert has_text(auth_driver, "Acme repo")
    assert has_text(auth_driver, "Add connection")  # the create form renders


@pytest.mark.connectors
def test_jira_sync_imports_tasks_from_mock(auth_driver, base_url, token, mock_jira):
    key = f"SYNC{int(time.time() * 1000) % 1_000_000}"
    proj = api_create_project(base_url, token, key, f"Sync {key}")
    conn = api_post(base_url, token, "/connectors/connections", {
        "provider": "jira", "name": "Mock Jira", "token": "mock-token",
        "config": {
            "base_url": mock_jira.base_url, "project_id": proj["id"],
            "jira_project_key": "MOCK", "email": "e2e@example.com",
        },
    })
    # Trigger a full sync (runs inline) against the mock; it returns created/updated counts.
    result = api_post(base_url, token, f"/connectors/connections/{conn['id']}/sync", {})
    assert result.get("created", 0) >= 2, result

    # The mocked issues now show as tasks on the project's Gantt.
    auth_driver.get(f"{base_url}/projects/{proj['id']}")
    assert has_text(auth_driver, "Checkout epic")
    assert has_text(auth_driver, "Build cart")
