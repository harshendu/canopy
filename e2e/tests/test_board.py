"""Flow board — USER_FLOWS §C9: status lanes, WIP, cycle-time aging."""

import pytest

from helpers import has_text, open_project_tab


@pytest.mark.board
def test_board_shows_status_lanes_and_wip(auth_driver, base_url, seed):
    open_project_tab(auth_driver, base_url, seed["project_a"], "Board")
    # Seeded tasks carry "In Progress" and "To Do" statuses -> two lanes.
    assert has_text(auth_driver, "In Progress")
    assert has_text(auth_driver, "To Do")
    # The flow controls render.
    assert has_text(auth_driver, "WIP limit per lane")
    assert has_text(auth_driver, "cycle-time P85")
