"""Pytest + Selenium fixtures for canopy's browser-driven end-to-end suite.

Configuration is entirely via environment variables so the same specs run
against a local dev stack, CI, or this cloud container without edits:

    CANOPY_BASE_URL    front-door URL of the running app (default http://127.0.0.1:5173)
    CANOPY_EMAIL       login used by the auth fixtures   (default architect@example.com)
    CANOPY_PASSWORD    password for that login           (default canopy-dev-password)
    E2E_HEADLESS       "1" (default) runs Chrome headless; "0" shows a window
    E2E_CHROME_BINARY  explicit Chrome/Chromium binary; auto-detected if unset
    E2E_CHROMEDRIVER   explicit chromedriver path; falls back to Selenium Manager / PATH

Driver/browser resolution is deliberately forgiving: on a normal dev machine
Selenium Manager finds Chrome + the matching driver automatically, so no env
is needed. In a sandbox you point E2E_CHROME_BINARY / E2E_CHROMEDRIVER at the
binaries you have.
"""

from __future__ import annotations

import glob
import os
import shutil
from collections.abc import Iterator

import pytest
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

from helpers import login as ui_login

DEFAULT_BASE_URL = "http://127.0.0.1:5173"
DEFAULT_EMAIL = "architect@example.com"
DEFAULT_PASSWORD = "canopy-dev-password"


def _detect_chrome_binary() -> str | None:
    """Find a Chrome/Chromium binary: explicit env → system → Playwright cache."""
    explicit = os.environ.get("E2E_CHROME_BINARY")
    if explicit:
        return explicit
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            return found
    # Playwright-managed Chromium (present in many CI/cloud images).
    for pattern in (
        "/opt/pw-browsers/chromium-*/chrome-linux/chrome",
        os.path.expanduser("~/.cache/ms-playwright/chromium-*/chrome-linux/chrome"),
    ):
        hits = sorted(glob.glob(pattern))
        if hits:
            return hits[-1]
    return None  # let Selenium Manager try to locate one


def _detect_chromedriver() -> str | None:
    """Find a chromedriver: explicit env → repo-local download → leave to Selenium Manager."""
    explicit = os.environ.get("E2E_CHROMEDRIVER")
    if explicit:
        return explicit
    local = os.path.join(os.path.dirname(__file__), ".drivers", "chromedriver")
    if os.path.exists(local):
        return local
    return None


def _make_driver() -> webdriver.Chrome:
    opts = Options()
    binary = _detect_chrome_binary()
    if binary:
        opts.binary_location = binary
    if os.environ.get("E2E_HEADLESS", "1") != "0":
        opts.add_argument("--headless=new")
    for arg in (
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--window-size=1280,1000",
    ):
        opts.add_argument(arg)
    driver_path = _detect_chromedriver()
    service = Service(executable_path=driver_path) if driver_path else Service()
    driver = webdriver.Chrome(options=opts, service=service)
    driver.set_page_load_timeout(30)
    return driver


@pytest.fixture(scope="session")
def base_url() -> str:
    return os.environ.get("CANOPY_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


@pytest.fixture(scope="session")
def credentials() -> tuple[str, str]:
    return (
        os.environ.get("CANOPY_EMAIL", DEFAULT_EMAIL),
        os.environ.get("CANOPY_PASSWORD", DEFAULT_PASSWORD),
    )


@pytest.fixture()
def driver() -> Iterator[webdriver.Chrome]:
    """A fresh, isolated browser per test (no shared cookies/localStorage)."""
    drv = _make_driver()
    try:
        yield drv
    finally:
        drv.quit()


@pytest.fixture()
def auth_driver(
    driver: webdriver.Chrome, base_url: str, credentials: tuple[str, str]
) -> webdriver.Chrome:
    """A browser already logged in and sitting on /projects."""
    ui_login(driver, base_url, *credentials)
    return driver
