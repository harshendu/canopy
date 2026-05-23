"""Minimal sanity: the SPA boots and React mounts. USER_FLOWS §A1."""

import pytest

from helpers import button_with_text, has_text


@pytest.mark.smoke
def test_login_page_renders(driver, base_url):
    driver.get(f"{base_url}/login")
    # If this button exists, Vite served the bundle and React hydrated the form.
    assert button_with_text(driver, "Sign in").is_displayed()
    assert has_text(driver, "Architecture & delivery cockpit")
