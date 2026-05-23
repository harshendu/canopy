from fastapi import APIRouter, HTTPException, status
from sqlmodel import col, select

from app.api.deps import CurrentUser, SessionDep
from app.models.project import Task, TaskStatusHistory
from app.schemas.entities import (
    TaskCreate,
    TaskRead,
    TaskStatusHistoryRead,
    TaskUpdate,
)

router = APIRouter()


@router.get("", response_model=list[TaskRead])
async def list_tasks(
    session: SessionDep, _: CurrentUser, project_id: int | None = None
) -> list[Task]:
    stmt = select(Task)
    if project_id is not None:
        stmt = stmt.where(Task.project_id == project_id)
    result = await session.execute(stmt.order_by(col(Task.id)))
    return list(result.scalars().all())


@router.post("", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
async def create_task(session: SessionDep, _: CurrentUser, payload: TaskCreate) -> Task:
    task = Task(**payload.model_dump())
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


@router.get("/{task_id}", response_model=TaskRead)
async def get_task(session: SessionDep, _: CurrentUser, task_id: int) -> Task:
    task = await session.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return task


@router.get("/{task_id}/history", response_model=list[TaskStatusHistoryRead])
async def get_task_history(
    session: SessionDep, _: CurrentUser, task_id: int
) -> list[TaskStatusHistory]:
    result = await session.execute(
        select(TaskStatusHistory)
        .where(TaskStatusHistory.task_id == task_id)
        .order_by(col(TaskStatusHistory.changed_at))
    )
    return list(result.scalars().all())


@router.patch("/{task_id}", response_model=TaskRead)
async def update_task(
    session: SessionDep, _: CurrentUser, task_id: int, payload: TaskUpdate
) -> Task:
    task = await session.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(task, field, value)
    await session.commit()
    await session.refresh(task)
    return task


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(session: SessionDep, _: CurrentUser, task_id: int) -> None:
    task = await session.get(Task, task_id)
    if task is not None:
        await session.delete(task)
        await session.commit()
