"""Stored stage policies — docs/AGENT_EXECUTION.md §9.1 (database side of `stage_policy.py`).

A policy belongs to one column of one workflow (`StagePolicy.owner_type = "workflow"`) and
travels with it: a project uses its own workflow's policies, else its team's, else the
workspace template's — exactly as it resolves its columns (§C9.1). A mirrored project's columns
are its tracker's statuses, so its policies belong to the tracker binding instead
(`owner_type = "binding"`, §17). A workflow nobody gave policies runs the built-in default
pipeline.

Every write validates the whole set against the workflow's columns first (the same parser the
pipeline uses), so what is stored can always be loaded.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.models.base import utcnow
from app.models.policy import StagePolicy
from app.services import flow, stage_policy
from app.services.stage_policy import Pipeline

WORKFLOW = "workflow"
BINDING = "binding"


def owner_of(view: Any) -> tuple[str, int] | None:
    """Who owns the policies of a resolved workflow view: a tracker view's binding, else the
    workflow itself (None for the built-in default — nothing stored)."""
    if getattr(view, "scope", None) == "tracker":
        binding_id = getattr(view, "binding_id", None)
        return (BINDING, int(binding_id)) if binding_id is not None else None
    workflow_id = getattr(view, "id", None)
    return (WORKFLOW, int(workflow_id)) if workflow_id is not None else None

_FIELDS = ("worked_by", "artifact", "instructions", "pulls_from", "enter", "on_changes",
           "decision", "checkpoints", "lease_minutes", "max_attempts", "max_rework")


def row_to_doc(row: StagePolicy) -> dict[str, Any]:
    """The stored row as the policy document `stage_policy.apply_policy_doc` reads."""
    doc: dict[str, Any] = {name: getattr(row, name) for name in _FIELDS}
    return {k: v for k, v in doc.items() if v not in (None, {}, "")} | {
        "worked_by": row.worked_by
    }


def _row_values(doc: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "worked_by": doc.get("worked_by"),
        "artifact": doc.get("artifact") or None,
        "instructions": str(doc.get("instructions") or ""),
        "pulls_from": doc.get("pulls_from"),
        "enter": dict(doc.get("enter") or {}),
        "on_changes": doc.get("on_changes"),
        "decision": doc.get("decision"),
        "checkpoints": dict(doc.get("checkpoints") or {}),
        "lease_minutes": doc.get("lease_minutes"),
        "max_attempts": doc.get("max_attempts"),
        "max_rework": doc.get("max_rework"),
    }


async def rows_for(
    session: AsyncSession, owner_id: int, owner_type: str = WORKFLOW
) -> list[StagePolicy]:
    return list(
        (
            await session.execute(
                select(StagePolicy)
                .where(StagePolicy.owner_type == owner_type, StagePolicy.owner_id == owner_id)
                .order_by(col(StagePolicy.id))
            )
        ).scalars().all()
    )


async def policies_for(
    session: AsyncSession, owner_id: int | None, owner_type: str = WORKFLOW
) -> dict[str, dict[str, Any]]:
    """The stored documents of a workflow (or a binding), keyed by column name ({} for the
    built-in default)."""
    if owner_id is None:
        return {}
    return {
        row.status_name: row_to_doc(row)
        for row in await rows_for(session, owner_id, owner_type)
    }


async def policies_of_view(session: AsyncSession, view: Any) -> dict[str, dict[str, Any]]:
    """The stored documents for the columns a resolved view describes."""
    owner = owner_of(view)
    if owner is None:
        return {}
    return await policies_for(session, owner[1], owner[0])


async def has_policies(
    session: AsyncSession, owner_id: int | None, owner_type: str = WORKFLOW
) -> bool:
    if owner_id is None:
        return False
    return bool(
        (
            await session.execute(
                select(StagePolicy.id).where(
                    StagePolicy.owner_type == owner_type, StagePolicy.owner_id == owner_id
                )
            )
        ).scalars().first()
    )


def validate(
    columns: Sequence[flow.ColumnDef], policies: Mapping[str, Mapping[str, Any] | None]
) -> Pipeline:
    """The pipeline these documents make (raises `stage_policy.PolicyError`). A document for a
    column the workflow doesn't have is refused rather than silently dropped."""
    names = {c.name.casefold(): c.name for c in columns}
    clean: dict[str, Mapping[str, Any]] = {}
    for name, doc in policies.items():
        if doc is None:
            continue
        found = names.get(name.strip().casefold())
        if found is None:
            raise stage_policy.PolicyError(f"{name!r} is not a column of this workflow",
                                           column=name)
        if not isinstance(doc, Mapping):
            raise stage_policy.PolicyError("A policy must be an object", column=found)
        clean[found] = doc
    return stage_policy.pipeline_from_policies(columns, clean)


async def save(
    session: AsyncSession,
    *,
    workflow_id: int,
    columns: Sequence[flow.ColumnDef],
    policies: Mapping[str, Mapping[str, Any] | None],
    user_id: int | None,
    owner_type: str = WORKFLOW,
) -> Pipeline:
    """Replace the policies of one workflow — or, with `owner_type="binding"`, of one tracker
    binding (`workflow_id` is then the binding's id) — validated first. An empty set returns it
    to the built-in default. Does not commit."""
    pipeline = validate(columns, policies)
    for row in await rows_for(session, workflow_id, owner_type):
        await session.delete(row)
    await session.flush()
    for stage in pipeline.stages:
        if not stage.has_policy:
            continue
        doc = stage.policy_doc()
        session.add(StagePolicy(owner_type=owner_type, owner_id=workflow_id,
                                status_name=stage.status_name, updated_by_user_id=user_id,
                                **_row_values(doc)))
    await session.flush()
    return pipeline


async def carry_over(
    session: AsyncSession, workflow_id: int, *, renames: Mapping[str, str],
    removed: Sequence[str],
) -> None:
    """After a workflow save: a renamed column keeps its policy, a removed one drops it, and
    references to a renamed column (pulls_from, on_changes, a decision's routing) follow."""
    rows = await rows_for(session, workflow_id)
    if not rows:
        return
    rename = {old.casefold(): new for old, new in renames.items()}
    gone = {name.casefold() for name in removed}

    def ref(value: Any) -> Any:
        if isinstance(value, str):
            return rename.get(value.casefold(), value)
        return value

    for row in rows:
        key = row.status_name.casefold()
        if key in gone and key not in rename:
            await session.delete(row)
            continue
        row.status_name = rename.get(key, row.status_name)
        row.on_changes = ref(row.on_changes)
        if row.pulls_from:
            row.pulls_from = [ref(v) for v in row.pulls_from if str(v).casefold() not in gone]
        if row.decision:
            row.decision = {k: (ref(v) if k.startswith("on_") else v)
                            for k, v in row.decision.items()}
        row.updated_at = utcnow()
    await session.flush()
