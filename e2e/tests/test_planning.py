"""WBS + scheduling — USER_FLOWS §C1 (add task), §C3 (Schedule/CPM), §B3 (tabs).

These drive the Gantt tab: add work through the UI, run the critical-path
scheduler, and assert the result banner — the core planning loop an architect
performs. A planner-role login is required (the add-task form is hidden for
non-planners, §A3a); the default fixture user is an admin.
"""

import time

import pytest

from helpers import (
    api_create_project,
    api_token,
    button_with_text,
    by_placeholder,
    has_text,
    tab,
    wait_until,
)


def _unique_key(prefix: str = "PLAN") -> str:
    return f"{prefix}{int(time.time() * 1000) % 1_000_000}"


@pytest.fixture()
def empty_project(base_url, credentials):
    token = api_token(base_url, *credentials)
    key = _unique_key()
    proj = api_create_project(base_url, token, key, f"Plan {key}")
    return proj


def _add_task(driver, name: str) -> None:
    box = by_placeholder(driver, "Task name")
    box.clear()
    box.send_keys(name)
    # ProjectView has exactly one "Add" button (the add-task form).
    button_with_text(driver, "Add").click()
    assert has_text(driver, name), f"task '{name}' did not appear on the Gantt"


@pytest.mark.planning
def test_add_tasks_and_run_cpm(auth_driver, base_url, empty_project):
    auth_driver.get(f"{base_url}/projects/{empty_project['id']}")
    # Empty state first.
    assert has_text(auth_driver, "No tasks yet")

    _add_task(auth_driver, "Design")
    _add_task(auth_driver, "Build")

    button_with_text(auth_driver, "Schedule (CPM)").click()
    # Replan banner reports how many tasks were scheduled.
    assert has_text(auth_driver, "Scheduled 2 tasks"), "CPM replan banner missing/incorrect"


@pytest.mark.planning
def test_tabs_render_without_error(auth_driver, base_url, empty_project, credentials):
    # Seed a task so data-bearing tabs have something to draw.
    token = api_token(base_url, *credentials)
    from helpers import api_create_task

    api_create_task(base_url, token, empty_project["id"], "Seeded task")
    auth_driver.get(f"{base_url}/projects/{empty_project['id']}")

    # Each tab should mount its view (lazy chunks load) without throwing.
    checks = {
        "Capacity": "Capacity",
        "Roadmap": "milestone",   # roadmap shows milestone groupings / add form
        "Risk": "isk",            # "Risk" heading/score
        "Activity": "ctivity",
    }
    for label, marker in checks.items():
        tab(auth_driver, label).click()
        assert wait_until(
            auth_driver,
            lambda d, m=marker: m.lower() in d.find_element("tag name", "main").text.lower(),
        ), f"tab '{label}' did not render expected content"
