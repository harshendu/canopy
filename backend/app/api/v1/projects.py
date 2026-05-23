from fastapi import APIRouter, HTTPException, status
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep
from app.models.base import TaskType
from app.models.project import Project, Task
from app.schemas.entities import (
    PortfolioResponse,
    ProjectCreate,
    ProjectRead,
    ProjectSummary,
    ProjectUpdate,
)

router = APIRouter()


@router.get("/portfolio", response_model=PortfolioResponse)
async def portfolio(session: SessionDep, _: CurrentUser) -> PortfolioResponse:
    projects = (await session.execute(select(Project).order_by(Project.name))).scalars().all()
    summaries: list[ProjectSummary] = []
    for project in projects:
        tasks = list(
            (
                await session.execute(select(Task).where(Task.project_id == project.id))
            ).scalars().all()
        )
        leaves = [t for t in tasks if t.type != TaskType.summary]
        total = len(leaves)
        completed = sum(1 for t in leaves if t.percent_complete >= 100)
        avg = sum(t.percent_complete for t in leaves) / total if total else 0.0
        ends = [t.end for t in tasks if t.end]
        summaries.append(
            ProjectSummary(
                id=project.id,
                key=project.key,
                name=project.name,
                total_tasks=total,
                completed_tasks=completed,
                avg_percent_complete=round(avg, 1),
                critical_tasks=sum(1 for t in leaves if t.is_critical),
                project_end=max(ends) if ends else None,
                target_date=project.target_date,
            )
        )
    return PortfolioResponse(projects=summaries)


@router.get("", response_model=list[ProjectRead])
async def list_projects(session: SessionDep, _: CurrentUser) -> list[Project]:
    result = await session.execute(select(Project).order_by(Project.name))
    return list(result.scalars().all())


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def create_project(session: SessionDep, _: CurrentUser, payload: ProjectCreate) -> Project:
    existing = await session.execute(select(Project).where(Project.key == payload.key))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Project key exists")
    project = Project(**payload.model_dump())
    session.add(project)
    await session.commit()
    await session.refresh(project)
    return project


@router.get("/{project_id}", response_model=ProjectRead)
async def get_project(session: SessionDep, _: CurrentUser, project_id: int) -> Project:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


@router.patch("/{project_id}", response_model=ProjectRead)
async def update_project(
    session: SessionDep, _: CurrentUser, project_id: int, payload: ProjectUpdate
) -> Project:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(project, field, value)
    await session.commit()
    await session.refresh(project)
    return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(session: SessionDep, _: CurrentUser, project_id: int) -> None:
    project = await session.get(Project, project_id)
    if project is not None:
        await session.delete(project)
        await session.commit()
