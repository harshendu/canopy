"""Outcomes — outcomes over output: a project/initiative is a *bet* toward a measurable result.

An `Outcome` is the hypothesis + a success metric tracked baseline→target→current with a verdict.
Scope is polymorphic (project | initiative), validated at the route (no FK), mirroring the risk
register. See `docs/AI_NATIVE_EXECUTION.md` §1/§5.
"""

from fastapi import APIRouter, HTTPException, status
from sqlmodel import col, select

from app.api.deps import CurrentUser, PlannerWriter, SessionDep
from app.models.base import OutcomeScope, OutcomeStatus
from app.models.outcome import Outcome
from app.models.project import Initiative, Project
from app.schemas.entities import OutcomeCreate, OutcomeRead, OutcomeUpdate

router = APIRouter()


async def _validate_scope(session: SessionDep, scope_level: OutcomeScope, scope_id: int) -> None:
    if scope_level == OutcomeScope.project:
        exists = await session.get(Project, scope_id) is not None
    else:
        exists = await session.get(Initiative, scope_id) is not None
    if not exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{scope_level.value} {scope_id} not found",
        )


@router.get("/outcomes", response_model=list[OutcomeRead])
async def list_outcomes(
    session: SessionDep,
    _: CurrentUser,
    scope_level: OutcomeScope | None = None,
    scope_id: int | None = None,
    status: OutcomeStatus | None = None,
) -> list[Outcome]:
    """Outcomes, newest first. Filter by scope and/or status."""
    stmt = select(Outcome)
    if scope_level is not None:
        stmt = stmt.where(Outcome.scope_level == scope_level)
    if scope_id is not None:
        stmt = stmt.where(Outcome.scope_id == scope_id)
    if status is not None:
        stmt = stmt.where(Outcome.status == status)
    rows = await session.execute(stmt.order_by(col(Outcome.id).desc()))
    return list(rows.scalars().all())


@router.post("/outcomes", response_model=OutcomeRead, status_code=status.HTTP_201_CREATED)
async def create_outcome(session: SessionDep, _: PlannerWriter, payload: OutcomeCreate) -> Outcome:
    await _validate_scope(session, payload.scope_level, payload.scope_id)
    outcome = Outcome(**payload.model_dump())
    session.add(outcome)
    await session.commit()
    await session.refresh(outcome)
    return outcome


@router.get("/outcomes/{outcome_id}", response_model=OutcomeRead)
async def get_outcome(session: SessionDep, _: CurrentUser, outcome_id: int) -> Outcome:
    outcome = await session.get(Outcome, outcome_id)
    if outcome is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Outcome not found")
    return outcome


@router.patch("/outcomes/{outcome_id}", response_model=OutcomeRead)
async def update_outcome(
    session: SessionDep, _: PlannerWriter, outcome_id: int, payload: OutcomeUpdate
) -> Outcome:
    outcome = await session.get(Outcome, outcome_id)
    if outcome is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Outcome not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(outcome, field, value)
    await session.commit()
    await session.refresh(outcome)
    return outcome


@router.delete("/outcomes/{outcome_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_outcome(session: SessionDep, _: PlannerWriter, outcome_id: int) -> None:
    outcome = await session.get(Outcome, outcome_id)
    if outcome is not None:
        await session.delete(outcome)
        await session.commit()
