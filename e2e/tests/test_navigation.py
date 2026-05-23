"""Sidebar navigation across the authenticated shell — USER_FLOWS §A,B,F,G,J,M.

Each row: (sidebar link text, expected URL suffix, a heading/text the page renders).
``None`` heading means "just assert the route changed and the shell is intact"
(the /me workspace heading is the user's own name, which varies by fixture user).
"""

import pytest

from helpers import has_text, nav_link, wait_for_path

ROUTES = [
    ("Portfolio", "/portfolio", "Portfolio"),
    ("Projects", "/projects", "Projects"),
    ("Decisions", "/decisions", "Decisions"),
    ("Team", "/team", "Team"),
    ("Connectors", "/connectors", "Connectors"),
    ("Users", "/admin/users", "Users"),   # admin-only link; fixture user is admin
    ("My work", "/me", None),
]


@pytest.mark.nav
@pytest.mark.parametrize("link_text,suffix,heading", ROUTES, ids=[r[1] for r in ROUTES])
def test_sidebar_navigates(auth_driver, link_text, suffix, heading):
    nav_link(auth_driver, link_text).click()
    wait_for_path(auth_driver, suffix)
    if heading is not None:
        assert has_text(auth_driver, heading), f"expected '{heading}' on {suffix}"
    # Shell stayed intact (still authenticated, sidebar present).
    assert nav_link(auth_driver, "Projects").is_displayed()
