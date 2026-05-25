"""Demo / seeded-data mode — USER_FLOWS §Z.

Opt-in: this spec **reseeds** (wiping all data, including the shared `seed` fixture used by the
rest of the suite), so it only runs when ``E2E_DEMO=1``. It loads the full demo dataset via the
admin endpoint, then drives the real UI to confirm the seeded content renders.

Requires the backend to be running with ``DEMO_MODE=true`` (run_e2e.sh sets this) and the fixture
login to be an admin (the seeded superuser is).
"""

import os

import pytest

from helpers import api_reseed_demo, has_text, nav_link, wait_for_path

pytestmark = pytest.mark.skipif(
    os.environ.get("E2E_DEMO") != "1",
    reason="opt-in: set E2E_DEMO=1 — this reseeds and wipes other fixtures' data",
)


def test_admin_can_load_and_browse_demo_data(auth_driver, base_url, token):
    counts = api_reseed_demo(base_url, token)["counts"]
    assert counts["projects"] >= 8

    # Admin → Demo data shows the dataset + the demo logins.
    nav_link(auth_driver, "Demo data").click()
    wait_for_path(auth_driver, "/admin/demo")
    assert has_text(auth_driver, "Demo logins")
    assert has_text(auth_driver, "sofia@helix.dev")

    # The seeded data renders in the real views.
    nav_link(auth_driver, "Projects").click()
    wait_for_path(auth_driver, "/projects")
    assert has_text(auth_driver, "Intelligence Engine")

    nav_link(auth_driver, "Initiatives").click()
    wait_for_path(auth_driver, "/initiatives")
    assert has_text(auth_driver, "Data Plane v2")
