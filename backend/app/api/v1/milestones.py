from fastapi import APIRouter, status
from sqlmodel import col, select

from app.api.deps import CurrentUser, PlannerWriter, SessionDep
from app.models.project import Milestone
from app.schemas.entities import MilestoneCreate, MilestoneRead

router = APIRouter()


@router.get("", response_model=list[MilestoneRead])
async def list_milestones(
    session: SessionDep, _: CurrentUser, project_id: int | None = None
) -> list[Milestone]:
    stmt = select(Milestone)
    if project_id is not None:
        stmt = stmt.where(Milestone.project_id == project_id)
    result = await session.execute(stmt.order_by(col(Milestone.target_date)))
    return list(result.scalars().all())


@router.post("", response_model=MilestoneRead, status_code=status.HTTP_201_CREATED)
async def create_milestone(
    session: SessionDep, _: PlannerWriter, payload: MilestoneCreate
) -> Milestone:
    milestone = Milestone(**payload.model_dump())
    session.add(milestone)
    await session.commit()
    await session.refresh(milestone)
    return milestone


@router.delete("/{milestone_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_milestone(session: SessionDep, _: PlannerWriter, milestone_id: int) -> None:
    milestone = await session.get(Milestone, milestone_id)
    if milestone is not None:
        await session.delete(milestone)
        await session.commit()
