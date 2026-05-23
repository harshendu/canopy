"""Architecture drift — USER_FLOWS §N: scan staleness + fitness-violation surfacing.

The server can't crawl code, so the Drift Sentinel posts observations via the scan API; here
we post a violating edge through the API (mocking the Sentinel's observation) and assert the
UI surfaces the fitness violation. Seed already attached a forbid(api -> connectors) rule to an
accepted ADR and bound the `api` component to code."""

import pytest

from helpers import api_post, has_text, open_project_tab


@pytest.mark.drift
def test_drift_tab_flags_scan_due(auth_driver, base_url, seed):
    open_project_tab(auth_driver, base_url, seed["project_a"], "Drift")
    assert has_text(auth_driver, "Drift score")
    # Bindings exist but nothing has scanned yet -> staleness badge.
    assert has_text(auth_driver, "scan due")


@pytest.mark.drift
def test_fitness_violation_surfaces_after_scan(auth_driver, base_url, seed, token):
    # The Sentinel observes api -> connectors in code, which the accepted ADR forbids.
    api_post(
        base_url, token, f"/projects/{seed['project_a']}/drift/scan",
        {"actual_edges": [[seed["component_api"], seed["component_connectors"]]]},
    )
    open_project_tab(auth_driver, base_url, seed["project_a"], "Drift")
    assert has_text(auth_driver, "Fitness violation")
