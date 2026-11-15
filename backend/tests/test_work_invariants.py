"""Single writers for agent work (docs/AGENT_EXECUTION.md §12), pinned the way
`test_status_single_writer.py` pins `Task.status`:

- `app/services/work_service.py` is the only writer of a claim's `state` and of
  `Task.active_claim_id` — the compare-and-swap that keeps one live claim per task, and the
  fencing that stops a lost session from writing anything.
- `app/services/gates.py` is the only writer of a gate's `status` and `decision` — deciding is
  human-only, and every decision routes the task.
- `app/services/work_service.py` is the only writer of a mirrored task's **clearance**
  (`Task.clearance_status` / `clearance_at`, §17) — canopy clears moves it may not make, and
  only the work service decides what was cleared.

These static checks fail when new code writes those fields some other way."""

from __future__ import annotations

import ast
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"
WORK_SERVICE = APP / "services" / "work_service.py"
GATES = APP / "services" / "gates.py"

# Names that conventionally hold a claim / a gate here. `.state` and `.status` are common
# attribute names (sprints, PRs, proposals…), so only these receivers count.
_CLAIM_NAMES = {"claim", "old", "held", "work_claim", "existing_claim", "row_claim"}
_GATE_NAMES = {"gate", "g", "park", "open_gate", "row_gate"}


def _modules(skip: Path) -> list[Path]:
    return [p for p in APP.rglob("*.py") if p != skip]


def _assigned_attributes(tree: ast.AST) -> list[tuple[ast.Attribute, int]]:
    out: list[tuple[ast.Attribute, int]] = []
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AugAssign | ast.AnnAssign):
            targets = [node.target]
        for target in targets:
            if isinstance(target, ast.Attribute):
                out.append((target, node.lineno))
    return out


def _calls(tree: ast.AST) -> list[ast.Call]:
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call)]


def _is_update_of(call: ast.Call, model: str) -> bool:
    return (
        isinstance(call.func, ast.Name)
        and call.func.id == "update"
        and bool(call.args)
        and isinstance(call.args[0], ast.Name)
        and call.args[0].id == model
    )


def test_claim_state_is_only_written_by_the_work_service() -> None:
    offenders: list[str] = []
    for path in _modules(WORK_SERVICE):
        tree = ast.parse(path.read_text())
        where = str(path.relative_to(APP))
        for target, line in _assigned_attributes(tree):
            if (
                target.attr in ("state", "outcome")
                and isinstance(target.value, ast.Name)
                and target.value.id in _CLAIM_NAMES
            ):
                offenders.append(f"{where}:{line}")
        for call in _calls(tree):
            # A bulk UPDATE of claims, or a claim built with its state set.
            if _is_update_of(call, "WorkClaim"):
                offenders.append(f"{where}:{call.lineno}")
            if (
                isinstance(call.func, ast.Name)
                and call.func.id == "WorkClaim"
                and any(k.arg in ("state", "outcome") for k in call.keywords)
            ):
                offenders.append(f"{where}:{call.lineno}")
    assert offenders == [], f"WorkClaim.state written outside work_service.py: {offenders}"


def test_active_claim_pointer_is_only_written_by_the_work_service() -> None:
    offenders: list[str] = []
    for path in _modules(WORK_SERVICE):
        tree = ast.parse(path.read_text())
        where = str(path.relative_to(APP))
        for target, line in _assigned_attributes(tree):
            if target.attr == "active_claim_id":
                offenders.append(f"{where}:{line}")
        for call in _calls(tree):
            if any(k.arg == "active_claim_id" for k in call.keywords) and (
                (isinstance(call.func, ast.Attribute) and call.func.attr == "values")
                or (isinstance(call.func, ast.Name) and call.func.id == "Task")
            ):
                offenders.append(f"{where}:{call.lineno}")
    assert offenders == [], f"Task.active_claim_id written outside work_service.py: {offenders}"


def test_clearance_is_only_written_by_the_work_service() -> None:
    offenders: list[str] = []
    for path in _modules(WORK_SERVICE):
        tree = ast.parse(path.read_text())
        where = str(path.relative_to(APP))
        for target, line in _assigned_attributes(tree):
            if target.attr in ("clearance_status", "clearance_at"):
                offenders.append(f"{where}:{line}")
        for call in _calls(tree):
            if any(k.arg in ("clearance_status", "clearance_at") for k in call.keywords) and (
                (isinstance(call.func, ast.Attribute) and call.func.attr == "values")
                or (isinstance(call.func, ast.Name) and call.func.id == "Task")
            ):
                offenders.append(f"{where}:{call.lineno}")
    assert offenders == [], f"Task.clearance_* written outside work_service.py: {offenders}"


def test_gate_status_and_decision_are_only_written_by_the_gate_service() -> None:
    offenders: list[str] = []
    for path in _modules(GATES):
        tree = ast.parse(path.read_text())
        where = str(path.relative_to(APP))
        for target, line in _assigned_attributes(tree):
            if (
                target.attr in ("status", "decision")
                and isinstance(target.value, ast.Name)
                and target.value.id in _GATE_NAMES
            ):
                offenders.append(f"{where}:{line}")
        for call in _calls(tree):
            if _is_update_of(call, "Gate"):
                offenders.append(f"{where}:{call.lineno}")
            if (
                isinstance(call.func, ast.Name)
                and call.func.id == "Gate"
                and any(k.arg in ("status", "decision") for k in call.keywords)
            ):
                offenders.append(f"{where}:{call.lineno}")
    assert offenders == [], f"Gate.status/decision written outside gates.py: {offenders}"


def test_no_route_decides_a_gate_for_an_agent_token() -> None:
    """The decide and reassign endpoints depend on `HumanOnly`; deciding has no MCP tool."""
    source = (APP / "api" / "v1" / "gates.py").read_text()
    tree = ast.parse(source)
    human_only: dict[str, bool] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef):
            human_only[node.name] = any(
                isinstance(a.annotation, ast.Name) and a.annotation.id == "HumanOnly"
                for a in node.args.args
            )
    assert human_only["decide_gate"] and human_only["reassign_gate"]
    plugin = APP.parent.parent / "plugin" / "mcp_server" / "tools"
    if plugin.exists():  # the plugin ships beside the backend in this repository
        for path in plugin.glob("*.py"):
            text = path.read_text()
            assert "/decide" not in text, f"{path.name} must not decide gates"
            assert "/delegation" not in text and "/agent-intake" not in text, path.name
