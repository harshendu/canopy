"""Org lookups shared by the board, workflows and sprints: which team runs a project, and which
projects a team runs. A project's team is its pod's team, else its initiative's team."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.models.org import Pod
from app.models.project import Initiative, Project


async def project_team_id(session: AsyncSession, project: Project) -> int | None:
    if project.pod_id is not None:
        pod = await session.get(Pod, project.pod_id)
        if pod is not None:
            return pod.team_id
    if project.initiative_id is not None:
        initiative = await session.get(Initiative, project.initiative_id)
        if initiative is not None:
            return initiative.team_id
    return None


async def team_project_ids(session: AsyncSession, team_id: int) -> list[int]:
    """Every live project the team runs: through one of its pods, or (pod-less) through one of
    its initiatives."""
    pod_ids = {
        p
        for p in (await session.execute(select(Pod.id).where(Pod.team_id == team_id)))
        .scalars()
        .all()
        if p is not None
    }
    initiative_ids = {
        i
        for i in (
            await session.execute(select(Initiative.id).where(Initiative.team_id == team_id))
        )
        .scalars()
        .all()
        if i is not None
    }
    projects = (
        await session.execute(select(Project).where(col(Project.archived).is_(False)))
    ).scalars().all()
    out: list[int] = []
    for project in projects:
        if project.id is None:
            continue
        if project.pod_id is not None:
            if project.pod_id in pod_ids:
                out.append(project.id)
        elif project.initiative_id is not None and project.initiative_id in initiative_ids:
            out.append(project.id)
    return sorted(out)
