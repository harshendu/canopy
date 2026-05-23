"""Blockers — USER_FLOWS §D0/§M: flag an impediment from /me and resolve it.

Self-contained: links the logged-in admin to an engineer, assigns them a task, then drives
the /me flag + resolve flow through the UI."""

import time

import pytest
from selenium.webdriver.support.ui import Select

from helpers import (
    api_create_engineer,
    api_create_project,
    api_create_task,
    api_get,
    button_with_text,
    by_placeholder,
    has_text,
    wait_until,
)


@pytest.mark.blockers
def test_flag_and_resolve_blocker_from_me(auth_driver, base_url, token):
    me = api_get(base_url, token, "/me" if False else "/auth/me")
    # Link the current login to an engineer and give them an assigned task.
    eng = api_create_engineer(base_url, token, f"Me E2E {int(time.time()) % 100000}", user_id=me["id"])
    key = f"BLK{int(time.time() * 1000) % 1_000_000}"
    proj = api_create_project(base_url, token, key, f"Blockers {key}")
    api_create_task(base_url, token, proj["id"], "My blocker task", assignee_engineer_id=eng["id"])

    auth_driver.get(f"{base_url}/me")
    assert has_text(auth_driver, "My blocker task"), "assigned task missing from /me"

    # Flag a blocker on the task.
    select_el = wait_until(
        auth_driver,
        lambda d: d.find_element("xpath", "//select[option[contains(., 'My blocker task')]]"),
    )
    Select(select_el).select_by_visible_text("My blocker task")
    by_placeholder(auth_driver, "What's blocking it?").send_keys("Waiting on review")
    button_with_text(auth_driver, "Flag").click()
    assert has_text(auth_driver, "Waiting on review"), "blocker did not appear"

    # Resolve it -> the only blocker clears.
    button_with_text(auth_driver, "resolve").click()
    assert has_text(auth_driver, "Nothing blocked"), "blocker was not resolved"
