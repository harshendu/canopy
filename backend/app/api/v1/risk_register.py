"""Risk register (RAID): human-tracked risks at task / project / initiative scope.

Distinct from the *computed* risk score in `risk.py` — these are qualitative risks an
architect/PM records by hand (probability x impact, owner, mitigation, contingency). They
are kept separate from the computed score; their exposure is derived at read time.
"""

from fastapi import APIRouter, HTTPException, status
from sqlmodel import col, select

from app.api.deps import CurrentUser, PlannerWriter, SessionDep
from app.models.base import RiskScope, RiskStatus, utcnow
from app.models.project import Initiative, Project, Task
from app.models.risk_register import RiskItem
from app.schemas.entities import (
    RiskItemClose,
    RiskItemCreate,
    RiskItemRead,
    RiskItemUpdate,
)

router = APIRouter()

# Terminal states close a risk (it's no longer an active threat).
_TERMINAL_STATUSES = {RiskStatus.resolved, RiskStatus.accepted, RiskStatus.occurred}


async def _validate_scope(session: SessionDep, scope_level: RiskScope, scope_id: int) -> None:
    """A register risk's scope is polymorphic (no FK) — confirm the target exists."""
    if scope_level == RiskScope.task:
        exists = await session.get(Task, scope_id) is not None
    elif scope_level == RiskScope.project:
        exists = await session.get(Project, scope_id) is not None
    else:
        exists = await session.get(Initiative, scope_id) is not None
    if not exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{scope_level.value} {scope_id} not found",
        )


def _apply_status_side_effects(item: RiskItem) -> None:
    """Stamp resolved_at when a risk reaches a terminal state; clear it if reopened."""
    if item.status in _TERMINAL_STATUSES:
        if item.resolved_at is None:
            item.resolved_at = utcnow()
    else:
        item.resolved_at = None


@router.get("/risks", response_model=list[RiskItemRead])
async def list_risks(
    session: SessionDep,
    _: CurrentUser,
    scope_level: RiskScope | None = None,
    scope_id: int | None = None,
    status: RiskStatus | None = None,
) -> list[RiskItem]:
    """Risk-register entries, newest first. Filter by scope and/or status."""
    stmt = select(RiskItem)
    if scope_level is not None:
        stmt = stmt.where(RiskItem.scope_level == scope_level)
    if scope_id is not None:
        stmt = stmt.where(RiskItem.scope_id == scope_id)
    if status is not None:
        stmt = stmt.where(RiskItem.status == status)
    rows = await session.execute(stmt.order_by(col(RiskItem.id).desc()))
    return list(rows.scalars().all())


@router.post("/risks", response_model=RiskItemRead, status_code=status.HTTP_201_CREATED)
async def create_risk(
    session: SessionDep, _: PlannerWriter, payload: RiskItemCreate
) -> RiskItem:
    await _validate_scope(session, payload.scope_level, payload.scope_id)
    item = RiskItem(**payload.model_dump())
    _apply_status_side_effects(item)
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item


@router.get("/risks/{risk_id}", response_model=RiskItemRead)
async def get_risk(session: SessionDep, _: CurrentUser, risk_id: int) -> RiskItem:
    item = await session.get(RiskItem, risk_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Risk not found")
    return item


@router.patch("/risks/{risk_id}", response_model=RiskItemRead)
async def update_risk(
    session: SessionDep, _: PlannerWriter, risk_id: int, payload: RiskItemUpdate
) -> RiskItem:
    item = await session.get(RiskItem, risk_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Risk not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    _apply_status_side_effects(item)
    await session.commit()
    await session.refresh(item)
    return item


@router.post("/risks/{risk_id}/close", response_model=RiskItemRead)
async def close_risk(
    session: SessionDep, _: PlannerWriter, risk_id: int, payload: RiskItemClose
) -> RiskItem:
    """Close a risk to a terminal state (resolved | accepted | occurred), optionally with a note."""
    item = await session.get(RiskItem, risk_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Risk not found")
    item.status = payload.status
    if payload.note:
        note = f"Resolution: {payload.note}"
        item.mitigation = f"{item.mitigation}\n{note}" if item.mitigation else note
    _apply_status_side_effects(item)
    await session.commit()
    await session.refresh(item)
    return item


@router.delete("/risks/{risk_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_risk(session: SessionDep, _: PlannerWriter, risk_id: int) -> None:
    item = await session.get(RiskItem, risk_id)
    if item is not None:
        await session.delete(item)
        await session.commit()
