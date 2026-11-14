"""Kanban board — USER_FLOWS §C9: workflow columns, WIP, cycle-time aging, moves."""

import pytest

from helpers import has_text, open_project_tab


@pytest.mark.board
def test_board_shows_workflow_columns_and_flow_controls(auth_driver, base_url, seed):
    open_project_tab(auth_driver, base_url, seed["project_a"], "Board")
    # The workflow's columns render in order, empty ones included; the seed creates tasks
    # "In Progress" and "To Do" through POST /tasks (a canopy-owned status).
    assert has_text(auth_driver, "Backlog")
    assert has_text(auth_driver, "In Progress")
    assert has_text(auth_driver, "To Do")
    # The flow controls render.
    assert has_text(auth_driver, "cycle-time P85")
    assert has_text(auth_driver, "Swimlanes")
