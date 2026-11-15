"""`design_docs.approve` is the only writer of a design doc's approval (CLAUDE.md, design docs;
USER_FLOWS §V8). Approval is a human act, so no other code path may stamp it — these static
checks fail when new code does."""

from __future__ import annotations

import ast
from pathlib import Path

from app.schemas.docs import DocRegisterIn, DocRevisionIn
from app.schemas.entities import DocReferenceCreate, DocReferenceUpdate

APP = Path(__file__).resolve().parent.parent / "app"
WRITER = APP / "services" / "design_docs.py"
SEED = APP / "services" / "seed"  # demo data is built as-of a moment; it is not a write path
_APPROVAL_FIELDS = {"approved_version", "approved_by_user_id", "approved_at"}


def _modules() -> list[Path]:
    return [p for p in APP.rglob("*.py") if p != WRITER and SEED not in p.parents]


def test_approval_fields_are_only_assigned_in_the_writer() -> None:
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
                if isinstance(target, ast.Attribute) and target.attr in _APPROVAL_FIELDS:
                    offenders.append(f"{path.relative_to(APP)}:{node.lineno}")
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "DocReference"
                and any(k.arg in _APPROVAL_FIELDS for k in node.keywords)
            ):
                offenders.append(f"{path.relative_to(APP)}:{node.lineno}")
    assert offenders == [], f"doc approval written outside design_docs.py: {offenders}"


def test_approved_status_is_only_set_by_approve() -> None:
    """Only `approve` assigns `review_status = DocReviewStatus.approved`."""
    tree = ast.parse(WRITER.read_text())
    setters: list[str] = []
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.AsyncFunctionDef | ast.FunctionDef):
            continue
        for node in ast.walk(fn):
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Attribute) and t.attr == "review_status" for t in node.targets
            ):
                source = ast.unparse(node.value)
                if "approved" in source:
                    setters.append(fn.name)
    assert setters == ["approve"], setters
    for path in _modules():
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Attribute) and t.attr == "review_status" for t in node.targets
            ):
                assert "approved" not in ast.unparse(node.value), (
                    f"{path.relative_to(APP)}:{node.lineno} sets an approved review status"
                )


def test_no_input_schema_can_carry_approval() -> None:
    for schema in (DocReferenceCreate, DocReferenceUpdate, DocRegisterIn, DocRevisionIn):
        fields = set(schema.model_fields)
        assert not fields & (_APPROVAL_FIELDS | {"review_status"}), (schema.__name__, fields)
