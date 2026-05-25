"""Specs — spec-driven development: intent as the source of truth.

A `Spec` captures the problem and explicit, checkable **acceptance criteria** before work
begins; tasks implement it (`Task.spec_id`); an agent self-audits each criterion against the
implementation and records met/unmet. `GET /specs/{id}` returns the audit bundle (criteria +
linked tasks + computed readiness). See `docs/AI_NATIVE_EXECUTION.md`.
"""

from fastapi import APIRouter, HTTPException, status
from sqlmodel import col, select

from app.api.deps import ContributorWriter, CurrentUser, PlannerWriter, SessionDep
from app.models.base import SpecStatus
from app.models.project import Project, Task
from app.models.spec import Spec, SpecCriterion
from app.schemas.entities import (
    SpecCreate,
    SpecCriterionCreate,
    SpecCriterionRead,
    SpecCriterionUpdate,
    SpecDetail,
    SpecLinkedTask,
    SpecRead,
    SpecUpdate,
)
from app.services import specs as spec_service

router = APIRouter()


async def _get_spec(session: SessionDep, spec_id: int) -> Spec:
    spec = await session.get(Spec, spec_id)
    if spec is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Spec not found")
    return spec


async def _criteria(session: SessionDep, spec_id: int) -> list[SpecCriterion]:
    rows = await session.execute(
        select(SpecCriterion)
        .where(SpecCriterion.spec_id == spec_id)
        .order_by(col(SpecCriterion.sort_order), col(SpecCriterion.id))
    )
    return list(rows.scalars().all())


@router.get("/specs", response_model=list[SpecRead])
async def list_specs(
    session: SessionDep,
    _: CurrentUser,
    project_id: int | None = None,
    status: SpecStatus | None = None,
) -> list[Spec]:
    """Specs, newest first. Filter by project and/or status."""
    stmt = select(Spec)
    if project_id is not None:
        stmt = stmt.where(Spec.project_id == project_id)
    if status is not None:
        stmt = stmt.where(Spec.status == status)
    rows = await session.execute(stmt.order_by(col(Spec.id).desc()))
    return list(rows.scalars().all())


@router.post("/specs", response_model=SpecRead, status_code=status.HTTP_201_CREATED)
async def create_spec(session: SessionDep, _: PlannerWriter, payload: SpecCreate) -> Spec:
    if await session.get(Project, payload.project_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Project {payload.project_id} not found"
        )
    spec = Spec(**payload.model_dump())
    session.add(spec)
    await session.commit()
    await session.refresh(spec)
    return spec


@router.get("/specs/{spec_id}", response_model=SpecDetail)
async def get_spec(session: SessionDep, _: CurrentUser, spec_id: int) -> SpecDetail:
    """The self-audit bundle: the spec, its acceptance criteria, the tasks implementing it,
    and the computed readiness."""
    spec = await _get_spec(session, spec_id)
    criteria = await _criteria(session, spec_id)
    tasks = list(
        (
            await session.execute(
                select(Task).where(Task.spec_id == spec_id).order_by(col(Task.id))
            )
        ).scalars()
    )
    met, total, ratio = spec_service.readiness(criteria)
    detail = SpecDetail.model_validate(spec)
    detail.criteria = [SpecCriterionRead.model_validate(c) for c in criteria]
    detail.linked_tasks = [SpecLinkedTask.model_validate(t) for t in tasks]
    detail.criteria_met = met
    detail.criteria_total = total
    detail.acceptance_ratio = ratio
    return detail


@router.patch("/specs/{spec_id}", response_model=SpecRead)
async def update_spec(
    session: SessionDep, _: PlannerWriter, spec_id: int, payload: SpecUpdate
) -> Spec:
    spec = await _get_spec(session, spec_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(spec, field, value)
    await session.commit()
    await session.refresh(spec)
    return spec


@router.delete("/specs/{spec_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_spec(session: SessionDep, _: PlannerWriter, spec_id: int) -> None:
    spec = await session.get(Spec, spec_id)
    if spec is None:
        return
    # SQLite doesn't enforce FKs but Postgres/MySQL do: unlink tasks + drop criteria first.
    linked = (await session.execute(select(Task).where(Task.spec_id == spec_id))).scalars().all()
    for task in linked:
        task.spec_id = None
    for criterion in await _criteria(session, spec_id):
        await session.delete(criterion)
    await session.delete(spec)
    await session.commit()


@router.post(
    "/specs/{spec_id}/criteria",
    response_model=SpecCriterionRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_criterion(
    session: SessionDep, _: PlannerWriter, spec_id: int, payload: SpecCriterionCreate
) -> SpecCriterion:
    await _get_spec(session, spec_id)
    criterion = SpecCriterion(spec_id=spec_id, **payload.model_dump())
    session.add(criterion)
    await session.commit()
    await session.refresh(criterion)
    return criterion


@router.patch("/criteria/{criterion_id}", response_model=SpecCriterionRead)
async def update_criterion(
    session: SessionDep, _: ContributorWriter, criterion_id: int, payload: SpecCriterionUpdate
) -> SpecCriterion:
    """Record the self-audit result for one criterion (met / unmet / waived). Open to any
    contributor — the implementing engineer or the agent records the verdict."""
    criterion = await session.get(SpecCriterion, criterion_id)
    if criterion is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Criterion not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(criterion, field, value)
    await session.commit()
    await session.refresh(criterion)
    return criterion


@router.delete("/criteria/{criterion_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_criterion(session: SessionDep, _: PlannerWriter, criterion_id: int) -> None:
    criterion = await session.get(SpecCriterion, criterion_id)
    if criterion is not None:
        await session.delete(criterion)
        await session.commit()
