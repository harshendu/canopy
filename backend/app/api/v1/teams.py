"""Teams and pods — the org structure above initiatives (USER_FLOWS §R6).

A team owns a product or a platform and holds pods; its directors may plan every initiative in
the team, its managers own the initiatives they are seated on. Reads are open to every signed-in
user (lateral visibility); creating teams/pods and seating directors/managers is admin-only.
Core (ungated), like the engineer roster at `/team`.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.api.deps import AdminUser, CurrentUser, SessionDep
from app.models.org import Pod, Team, TeamMember
from app.models.team import Engineer
from app.schemas.leadership import (
    PodCreate,
    PodRead,
    TeamCreate,
    TeamMemberIn,
    TeamMemberRead,
    TeamRead,
)

router = APIRouter()


async def team_reads(session: AsyncSession) -> list[TeamRead]:
    """Every team with its pods and director/manager seats (names resolved)."""
    teams = list((await session.execute(select(Team).order_by(col(Team.id)))).scalars())
    pods = list((await session.execute(select(Pod).order_by(col(Pod.name)))).scalars())
    seats = (
        await session.execute(
            select(TeamMember, Engineer)
            .join(Engineer, col(Engineer.id) == col(TeamMember.engineer_id))
            .order_by(col(TeamMember.role), col(Engineer.name))
        )
    ).all()
    out: list[TeamRead] = []
    for t in teams:
        assert t.id is not None
        out.append(
            TeamRead(
                id=t.id,
                key=t.key,
                name=t.name,
                description=t.description,
                pods=[
                    PodRead(id=p.id or 0, team_id=p.team_id, name=p.name)
                    for p in pods
                    if p.team_id == t.id
                ],
                members=[
                    TeamMemberRead(
                        team_id=m.team_id,
                        engineer_id=m.engineer_id,
                        engineer_name=e.name,
                        role=m.role,
                        user_id=e.user_id,
                    )
                    for m, e in seats
                    if m.team_id == t.id
                ],
            )
        )
    return out


@router.get("", response_model=list[TeamRead])
async def list_teams(session: SessionDep, _: CurrentUser) -> list[TeamRead]:
    return await team_reads(session)


@router.post("", response_model=TeamRead, status_code=status.HTTP_201_CREATED)
async def create_team(session: SessionDep, _: AdminUser, payload: TeamCreate) -> TeamRead:
    existing = await session.execute(select(Team).where(Team.key == payload.key))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Team key exists")
    team = Team(**payload.model_dump())
    session.add(team)
    await session.commit()
    await session.refresh(team)
    assert team.id is not None
    return TeamRead(id=team.id, key=team.key, name=team.name, description=team.description)


@router.post("/{team_id}/pods", response_model=PodRead, status_code=status.HTTP_201_CREATED)
async def create_pod(
    session: SessionDep, _: AdminUser, team_id: int, payload: PodCreate
) -> PodRead:
    if await session.get(Team, team_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    pod = Pod(team_id=team_id, name=payload.name)
    session.add(pod)
    await session.commit()
    await session.refresh(pod)
    assert pod.id is not None
    return PodRead(id=pod.id, team_id=pod.team_id, name=pod.name)


@router.put("/{team_id}/members", response_model=list[TeamMemberRead])
async def set_team_members(
    session: SessionDep, _: AdminUser, team_id: int, payload: list[TeamMemberIn]
) -> list[TeamMemberRead]:
    """Replace the team's director/manager seats."""
    if await session.get(Team, team_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    for item in payload:
        if await session.get(Engineer, item.engineer_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Engineer {item.engineer_id} not found",
            )
    for seat in (
        await session.execute(select(TeamMember).where(TeamMember.team_id == team_id))
    ).scalars().all():
        await session.delete(seat)
    await session.flush()
    for item in payload:
        session.add(TeamMember(team_id=team_id, engineer_id=item.engineer_id, role=item.role))
    await session.commit()
    teams = await team_reads(session)
    return next((t.members for t in teams if t.id == team_id), [])
