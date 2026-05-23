from fastapi import APIRouter, HTTPException, status
from sqlmodel import select

from app.api.deps import CurrentUser, PlannerWriter, SessionDep
from app.models.project import Dependency, Task
from app.schemas.entities import DependencyCreate, DependencyRead

router = APIRouter()


@router.get("", response_model=list[DependencyRead])
async def list_dependencies(
    session: SessionDep, _: CurrentUser, project_id: int | None = None
) -> list[Dependency]:
    if project_id is None:
        result = await session.execute(select(Dependency))
        return list(result.scalars().all())
    # Filter to dependencies whose endpoints belong to the project.
    task_ids = (
        await session.execute(select(Task.id).where(Task.project_id == project_id))
    ).scalars().all()
    task_id_set = set(task_ids)
    result = await session.execute(select(Dependency))
    return [
        d
        for d in result.scalars().all()
        if d.predecessor_id in task_id_set or d.successor_id in task_id_set
    ]


@router.post("", response_model=DependencyRead, status_code=status.HTTP_201_CREATED)
async def create_dependency(
    session: SessionDep, _: PlannerWriter, payload: DependencyCreate
) -> Dependency:
    if payload.predecessor_id == payload.successor_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Self-dependency")
    dependency = Dependency(**payload.model_dump())
    session.add(dependency)
    await session.commit()
    await session.refresh(dependency)
    return dependency


@router.delete("/{dependency_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dependency(session: SessionDep, _: PlannerWriter, dependency_id: int) -> None:
    dependency = await session.get(Dependency, dependency_id)
    if dependency is not None:
        await session.delete(dependency)
        await session.commit()
