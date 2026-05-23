"""Authentication & access — USER_FLOWS §A1 (login), §A2 (sign out)."""

import pytest

from helpers import (
    button_with_text,
    by_placeholder,
    has_text,
    login,
    logout,
    nav_link,
    wait_for_path,
)


@pytest.mark.auth
def test_invalid_credentials_show_error(driver, base_url, credentials):
    email, _ = credentials
    driver.get(f"{base_url}/login")
    email_box = by_placeholder(driver, "email")  # pre-filled — clear before typing
    email_box.clear()
    email_box.send_keys(email)
    pw_box = by_placeholder(driver, "password")
    pw_box.clear()
    pw_box.send_keys("definitely-wrong-password")
    button_with_text(driver, "Sign in").click()
    assert has_text(driver, "Invalid email or password")
    assert driver.current_url.rstrip("/").endswith("/login")


@pytest.mark.auth
def test_login_redirects_to_projects(driver, base_url, credentials):
    login(driver, base_url, *credentials)
    assert driver.current_url.rstrip("/").endswith("/projects")
    # The authenticated shell (sidebar) is present.
    assert nav_link(driver, "Projects").is_displayed()


@pytest.mark.auth
def test_protected_route_redirects_when_anonymous(driver, base_url):
    driver.get(f"{base_url}/portfolio")
    wait_for_path(driver, "/login")
    assert button_with_text(driver, "Sign in").is_displayed()


@pytest.mark.auth
def test_logout_returns_to_login(auth_driver):
    logout(auth_driver)
    assert auth_driver.current_url.rstrip("/").endswith("/login")
