"""`workflow.record_transition` is the only writer of a task's status (CLAUDE.md, "Source-of-truth
boundaries"). These static checks fail when new code writes `Task.status` / `status_category`
some other way — which would skip history, ownership and progress reconciliation."""

from __future__ import annotations

import ast
from pathlib import Path

from app.schemas.entities import TaskUpdate
from app.services.flow import ColumnDef
from app.services.workflow import heuristic_category, parse_remote_time, resolve_category

APP = Path(__file__).resolve().parent.parent / "app"
WRITER = APP / "services" / "workflow.py"
# Names that conventionally hold a Task in this codebase; an assignment `<name>.status = ...`
# outside the writer module is a bypass. (Milestones, proposals, risks, plans, drift events and
# scenarios have their own `status` and are written as `milestone.status`, `plan.status`, ...)
_TASK_NAMES = {"task", "t", "target_task", "live", "child", "row_task", "new_task"}


def _modules() -> list[Path]:
    return [p for p in APP.rglob("*.py") if p != WRITER]


def test_status_category_is_only_assigned_in_the_writer() -> None:
    offenders: list[str] = []
    for path in _modules():
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            targets: list[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, ast.AugAssign | ast.AnnAssign):
                targets = [node.target]
            for target in targets:
                if isinstance(target, ast.Attribute) and target.attr == "status_category":
                    offenders.append(f"{path.relative_to(APP)}:{node.lineno}")
    assert offenders == [], f"status_category written outside workflow.py: {offenders}"


def test_task_status_is_only_assigned_in_the_writer() -> None:
    offenders: list[str] = []
    for path in _modules():
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            targets: list[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, ast.AugAssign | ast.AnnAssign):
                targets = [node.target]
            for target in targets:
                if (
                    isinstance(target, ast.Attribute)
                    and target.attr == "status"
                    and isinstance(target.value, ast.Name)
                    and target.value.id in _TASK_NAMES
                ):
                    offenders.append(f"{path.relative_to(APP)}:{node.lineno}")
            # `Task(..., status=...)` builds a task with a status but no history row.
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "Task"
                and any(k.arg in ("status", "status_category") for k in node.keywords)
            ):
                offenders.append(f"{path.relative_to(APP)}:{node.lineno}")
    assert offenders == [], f"Task.status written outside workflow.py: {offenders}"


def test_patch_route_cannot_write_status() -> None:
    # A generic setattr loop over TaskUpdate fields must never reach `status`.
    assert "status" not in TaskUpdate.model_fields
    assert "status_category" not in TaskUpdate.model_fields
    assert "status_owner" not in TaskUpdate.model_fields


def test_category_resolution_prefers_the_tracker_then_the_workflow() -> None:
    columns = [ColumnDef("Review", "in_progress", 0), ColumnDef("Live", "done", 1)]
    assert resolve_category("Live", explicit="todo", columns=columns) == "todo"  # tracker wins
    assert resolve_category("live", columns=columns) == "done"  # workflow, case-insensitive
    assert resolve_category("Shipped") == "done"  # heuristic
    assert resolve_category("Won't Do") == "cancelled"
    assert resolve_category("Selected for Development") == "todo"
    assert resolve_category("QA") == "in_progress"  # unknown names count as started work
    assert resolve_category("Live", explicit="bogus") == "done"  # an invalid category is ignored
    assert resolve_category(None) is None
    assert heuristic_category("  ") is None


def test_remote_times_become_naive_utc() -> None:
    parsed = parse_remote_time("2026-05-02T12:00:00.000+0200")
    assert parsed is not None and parsed.tzinfo is None and parsed.hour == 10
    assert parse_remote_time("2026-05-02T10:00:00Z") == parse_remote_time(
        "2026-05-02T10:00:00+00:00"
    )
    assert parse_remote_time("not a time") is None
    assert parse_remote_time(None) is None
