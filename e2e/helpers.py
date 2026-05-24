"""Reusable selectors, waits, and arrange-helpers for the e2e specs.

The React app ships no ``data-testid`` hooks, so selectors target user-visible
anchors (placeholders, button/label/link text, headings) via XPath — the same
things a human reads on screen. Keep selectors here so a UI label change is a
one-line fix, not a shotgun edit across specs.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any, Callable, TypeVar

from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

DEFAULT_TIMEOUT = 15
T = TypeVar("T")


# --------------------------------------------------------------------------- #
# Waiting
# --------------------------------------------------------------------------- #
def wait_until(driver: WebDriver, condition: Callable[[WebDriver], T], timeout: int = DEFAULT_TIMEOUT) -> T:
    return WebDriverWait(driver, timeout).until(condition)


def wait_for_path(driver: WebDriver, suffix: str, timeout: int = DEFAULT_TIMEOUT) -> None:
    """Block until the SPA URL ends with ``suffix`` (e.g. ``/projects``)."""
    wait_until(driver, lambda d: d.current_url.rstrip("/").endswith(suffix.rstrip("/")), timeout)


# --------------------------------------------------------------------------- #
# Selectors (XPath against visible text)
# --------------------------------------------------------------------------- #
def _xp(driver: WebDriver, xpath: str, timeout: int = DEFAULT_TIMEOUT) -> WebElement:
    return wait_until(driver, EC.presence_of_element_located((By.XPATH, xpath)), timeout)


def by_placeholder(driver: WebDriver, placeholder: str, timeout: int = DEFAULT_TIMEOUT) -> WebElement:
    return _xp(driver, f"//input[@placeholder={_q(placeholder)}]", timeout)


def button_with_text(driver: WebDriver, text: str, timeout: int = DEFAULT_TIMEOUT) -> WebElement:
    return wait_until(
        driver,
        EC.element_to_be_clickable((By.XPATH, f"//button[normalize-space()={_q(text)}]")),
        timeout,
    )


def nav_link(driver: WebDriver, text: str, timeout: int = DEFAULT_TIMEOUT) -> WebElement:
    return wait_until(
        driver,
        EC.element_to_be_clickable((By.XPATH, f"//a[normalize-space()={_q(text)}]")),
        timeout,
    )


def tab(driver: WebDriver, label: str, timeout: int = DEFAULT_TIMEOUT) -> WebElement:
    """A ProjectView tab button (Gantt, Dependencies, Risk, ...)."""
    return button_with_text(driver, label, timeout)


def has_text(driver: WebDriver, text: str, timeout: int = DEFAULT_TIMEOUT) -> bool:
    """True once ``text`` appears anywhere in the rendered body."""
    try:
        wait_until(
            driver,
            EC.presence_of_element_located((By.XPATH, f"//*[contains(normalize-space(.), {_q(text)})]")),
            timeout,
        )
        return True
    except Exception:
        return False


def _q(value: str) -> str:
    """Quote a string for XPath, handling embedded quotes via concat()."""
    if '"' not in value:
        return f'"{value}"'
    if "'" not in value:
        return f"'{value}'"
    parts = value.split('"')
    return "concat(" + ", '\"', ".join(f'"{p}"' for p in parts) + ")"


# --------------------------------------------------------------------------- #
# Flows
# --------------------------------------------------------------------------- #
def login(driver: WebDriver, base_url: str, email: str, password: str) -> None:
    """Log in through the UI and wait for the /projects landing."""
    driver.get(f"{base_url}/login")
    email_box = by_placeholder(driver, "email")
    email_box.clear()
    email_box.send_keys(email)
    pw_box = by_placeholder(driver, "password")
    pw_box.clear()
    pw_box.send_keys(password)
    button_with_text(driver, "Sign in").click()
    wait_for_path(driver, "/projects")


def logout(driver: WebDriver) -> None:
    button_with_text(driver, "Sign out").click()
    wait_for_path(driver, "/login")


# --------------------------------------------------------------------------- #
# Arrange via API (stdlib only) — fast preconditions for UI act/assert
# --------------------------------------------------------------------------- #
def _api(base_url: str) -> str:
    return f"{base_url}/api/v1"


def api_token(base_url: str, email: str, password: str) -> str:
    body = urllib.parse.urlencode({"username": email, "password": password}).encode()
    req = urllib.request.Request(
        f"{_api(base_url)}/auth/login",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return str(json.load(resp)["access_token"])


def _request(base_url: str, token: str, method: str, path: str, payload: dict[str, Any] | None) -> Any:
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Authorization": f"Bearer {token}"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{_api(base_url)}{path}", data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read()
        return json.loads(body) if body else None


def api_post(base_url: str, token: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    return dict(_request(base_url, token, "POST", path, payload))


def api_get(base_url: str, token: str, path: str) -> Any:
    return _request(base_url, token, "GET", path, None)


def api_patch(base_url: str, token: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    return dict(_request(base_url, token, "PATCH", path, payload))


def api_create_project(base_url: str, token: str, key: str, name: str, **extra: Any) -> dict[str, Any]:
    return api_post(base_url, token, "/projects", {"key": key, "name": name, **extra})


def api_create_task(base_url: str, token: str, project_id: int, name: str, duration: int = 3, **extra: Any) -> dict[str, Any]:
    return api_post(
        base_url, token, "/tasks",
        {"project_id": project_id, "name": name, "duration": duration, "type": "task", **extra},
    )


def api_create_initiative(base_url: str, token: str, key: str, name: str, **extra: Any) -> dict[str, Any]:
    return api_post(base_url, token, "/initiatives", {"key": key, "name": name, **extra})


def api_create_engineer(base_url: str, token: str, name: str, **extra: Any) -> dict[str, Any]:
    return api_post(base_url, token, "/team/engineers", {"name": name, **extra})


def api_create_component(base_url: str, token: str, project_id: int, name: str, **extra: Any) -> dict[str, Any]:
    return api_post(base_url, token, "/architecture/components", {"project_id": project_id, "name": name, **extra})


def api_create_adr(base_url: str, token: str, project_id: int, title: str, **extra: Any) -> dict[str, Any]:
    return api_post(base_url, token, "/architecture/adrs", {"project_id": project_id, "title": title, **extra})


def open_project_tab(driver: WebDriver, base_url: str, project_id: int, tab_label: str) -> None:
    """Open a project's cockpit and click a tab."""
    driver.get(f"{base_url}/projects/{project_id}")
    tab(driver, tab_label).click()
