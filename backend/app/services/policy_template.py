"""Applying the agentic-delivery template (docs/AGENT_EXECUTION.md Appendix A) and recording
policy changes — shared by the stage-policy API and the demo seed.

The template's columns become the scope's own workflow (cards in columns it lacks move where
`suggest_moves` says, or where the planner chose) and its documents become the columns'
policies, in one transaction the caller commits.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import WipEnforcement, WorkEventKind
from app.models.user import User
from app.services import flow, policy_store, stage_policy, work_service
from app.services import workflow as workflow_service
from app.services.workflow import ColumnInput, WorkflowView


class UnknownStatusError(ValueError):
    """A `move_tasks_to` target that isn't a column of the template."""


def suggest_moves(
    current: list[flow.ColumnDef], template: list[tuple[str, str]], overrides: dict[str, str]
) -> dict[str, str]:
    """Where each current column the template lacks sends its cards: the planner's choice,
    else by category (the last to-do column before work starts → Ready, other to-do columns →
    Backlog; a review / QA / sign-off column by name; other started work → In Progress)."""
    names = {name.casefold(): name for name, _ in template}
    chosen = {k.strip().casefold(): v for k, v in overrides.items()}
    ordered = sorted(current, key=lambda c: c.position)
    first_started = next((c.position for c in ordered if c.category == flow.IN_PROGRESS), None)
    todos_before = [c for c in ordered if c.category == flow.TODO
                    and (first_started is None or c.position < first_started)]
    feeder = todos_before[-1].name.casefold() if todos_before else None
    moves: dict[str, str] = {}
    for column in ordered:
        key = column.name.casefold()
        if key in names:
            continue
        if key in chosen:
            target = names.get(chosen[key].strip().casefold())
            if target is None:
                raise UnknownStatusError(f"{chosen[key]!r} is not a column of the template")
            moves[column.name] = target
            continue
        lowered = column.name.lower()
        if column.category == flow.TODO:
            moves[column.name] = "Ready" if key == feeder else "Backlog"
        elif column.category == flow.DONE:
            moves[column.name] = "Done"
        elif column.category == flow.CANCELLED:
            moves[column.name] = "Cancelled"
        elif "review" in lowered:
            moves[column.name] = "In Review"
        elif any(word in lowered for word in ("qa", "test", "verif")):
            moves[column.name] = "QA"
        elif any(word in lowered for word in ("sign", "approv", "accept")):
            moves[column.name] = "Sign-off"
        else:
            moves[column.name] = "In Progress"
    return moves


async def record_policy_change(
    session: AsyncSession, user: User, view: WorkflowView, pipeline: stage_policy.Pipeline,
    *, team_id: int | None, project_id: int | None, template: str | None = None,
) -> None:
    """A `policy_changed` work event on every project the scope's columns reach."""
    caller = await work_service.caller_for(session, user, None, is_agent=False)
    configured = [s.status_name for s in pipeline.stages if s.has_policy]
    for project in await workflow_service.projects_using_scope(
        session, team_id=team_id, project_id=project_id
    ):
        if project.id is None:
            continue
        work_service.record_event(
            session, kind=WorkEventKind.policy_changed, project_id=project.id, task_id=None,
            caller=caller, data={"scope": view.scope, "workflow_id": view.id,
                                 "columns": configured, "template": template},
        )


async def save_policies(
    session: AsyncSession, user: User, view: WorkflowView, policies: dict[str, Any],
    *, team_id: int | None, project_id: int | None, template: str | None = None,
) -> stage_policy.Pipeline:
    """Replace the policies of `view`'s columns (raises `stage_policy.PolicyError`)."""
    assert view.id is not None
    pipeline = await policy_store.save(session, workflow_id=view.id, columns=view.columns,
                                       policies=policies, user_id=user.id)
    await record_policy_change(session, user, view, pipeline, team_id=team_id,
                               project_id=project_id, template=template)
    return pipeline


async def apply_template(
    session: AsyncSession, user: User, *, actor: str, team_id: int | None,
    project_id: int | None, move_tasks_to: dict[str, str] | None = None,
) -> tuple[WorkflowView, stage_policy.Pipeline]:
    """Save the template's columns and policies as the scope's own. Raises `UnknownStatusError`,
    `workflow.TrackingError` (a column change the board refuses) or
    `stage_policy.PolicyError`; the caller commits or rolls back."""
    columns, policies = stage_policy.agentic_delivery_template()
    current = await workflow_service.current_view(session, team_id=team_id,
                                                  project_id=project_id)
    moves = suggest_moves(current.columns, columns, move_tasks_to or {})
    limits = {c.name.casefold(): c.wip_limit for c in current.columns}
    view = await workflow_service.save_workflow(
        session, team_id=team_id, project_id=project_id,
        name=current.name if not current.inherited else "Agentic delivery",
        wip_enforcement=WipEnforcement.block.value,
        columns=[ColumnInput(name=name, category=category, wip_limit=limits.get(name.casefold()))
                 for name, category in columns],
        move_tasks_to=moves, actor=actor,
    )
    pipeline = await save_policies(session, user, view, dict(policies), team_id=team_id,
                                   project_id=project_id, template=stage_policy.TEMPLATE_KEY)
    return view, pipeline
