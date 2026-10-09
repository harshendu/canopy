"""Ownership-scoped editing across the org structure (USER_FLOWS §R6).

The role matrix (`app/api/deps.py`) says *what kind* of write a role may make; this layer says
*where*. For a planner-role user (architect / engineering manager / legacy member):

* an **initiative owner** (`InitiativeLead`: a pod's technical / product / design lead, or a
  manager — several per initiative, and one person may own several initiatives) plans the whole
  initiative and every project in it;
* a **team director** (`TeamMember` role `director`) plans every initiative in their team;
* a **project owner** (`Project.owner_engineer_id`, exactly one per project) plans that project,
  even inside an initiative they do not own;
* everyone else reads — complete lateral visibility, no cross-team edits.

Admins are exempt. An initiative is *governed* once it has owners or belongs to a team; an
ungoverned initiative (and the Helix demo, which sets neither) keeps the plain role rules.
Contributor writes by engineers (own-task progress, blockers, criterion verdicts, decision
comments) are not scoped here — they stay governed by role alone.

Denials are 403 with a machine-readable `code` so the UI can explain *why*.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.models.base import TeamRole, UserRole
from app.models.leadership import InitiativeLead
from app.models.org import TeamMember
from app.models.project import Initiative, Project, Task
from app.models.team import Engineer
from app.models.user import User

# Roles whose writes are scoped by ownership (admin is exempt; engineer/viewer writes are
# decided by role alone).
OWNERSHIP_ROLES = frozenset({UserRole.architect, UserRole.engineering_manager, UserRole.member})


async def engineer_ids_for_user(session: AsyncSession, user: User) -> set[int]:
    rows = (
        await session.execute(select(Engineer.id).where(Engineer.user_id == user.id))
    ).scalars().all()
    return {e for e in rows if e is not None}


async def led_initiative_ids(session: AsyncSession, user: User) -> set[int]:
    """Initiatives the user is an owner of (via their linked Engineer rows)."""
    eng_ids = await engineer_ids_for_user(session, user)
    if not eng_ids:
        return set()
    rows = (
        await session.execute(
            select(InitiativeLead.initiative_id).where(
                col(InitiativeLead.engineer_id).in_(eng_ids)
            )
        )
    ).scalars().all()
    return set(rows)


async def directed_team_ids(session: AsyncSession, user: User) -> set[int]:
    """Teams the user is a director of."""
    eng_ids = await engineer_ids_for_user(session, user)
    if not eng_ids:
        return set()
    rows = (
        await session.execute(
            select(TeamMember.team_id).where(
                col(TeamMember.engineer_id).in_(eng_ids),
                TeamMember.role == TeamRole.director,
            )
        )
    ).scalars().all()
    return set(rows)


async def owned_project_ids(session: AsyncSession, user: User) -> set[int]:
    eng_ids = await engineer_ids_for_user(session, user)
    if not eng_ids:
        return set()
    rows = (
        await session.execute(
            select(Project.id).where(col(Project.owner_engineer_id).in_(eng_ids))
        )
    ).scalars().all()
    return {p for p in rows if p is not None}


async def initiative_has_leads(session: AsyncSession, initiative_id: int) -> bool:
    row = (
        await session.execute(
            select(InitiativeLead.id).where(InitiativeLead.initiative_id == initiative_id).limit(1)
        )
    ).scalar_one_or_none()
    return row is not None


def can_edit(
    user: User,
    *,
    governed: bool,
    is_lead: bool,
    is_director: bool = False,
    is_project_owner: bool = False,
) -> bool:
    """Pure decision: may this user make planning writes here?"""
    if user.role == UserRole.admin:
        return True
    if user.role not in OWNERSHIP_ROLES:
        return False
    return not governed or is_lead or is_director or is_project_owner


async def _initiative_facts(
    session: AsyncSession, user: User, initiative_id: int
) -> tuple[bool, bool, bool]:
    """(governed, is_lead, is_director) for one initiative."""
    initiative = await session.get(Initiative, initiative_id)
    team_id = initiative.team_id if initiative is not None else None
    has_leads = await initiative_has_leads(session, initiative_id)
    governed = has_leads or team_id is not None
    if not governed:
        return False, False, False
    is_lead = initiative_id in await led_initiative_ids(session, user)
    is_director = team_id is not None and team_id in await directed_team_ids(session, user)
    return True, is_lead, is_director


async def initiative_can_edit(session: AsyncSession, user: User, initiative_id: int) -> bool:
    governed, is_lead, is_director = await _initiative_facts(session, user, initiative_id)
    return can_edit(user, governed=governed, is_lead=is_lead, is_director=is_director)


async def project_can_edit(session: AsyncSession, user: User, project: Project) -> bool:
    is_owner = project.id is not None and project.id in await owned_project_ids(session, user)
    if project.initiative_id is None:
        # Outside any initiative a project is governed only by its own owner.
        governed = project.owner_engineer_id is not None
        return can_edit(user, governed=governed, is_lead=False, is_project_owner=is_owner)
    governed, is_lead, is_director = await _initiative_facts(session, user, project.initiative_id)
    governed = governed or project.owner_engineer_id is not None
    return can_edit(
        user,
        governed=governed,
        is_lead=is_lead,
        is_director=is_director,
        is_project_owner=is_owner,
    )


def _denied(name: str, initiative_id: int | None) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": "not_initiative_lead",
            "initiative_id": initiative_id,
            "message": f"Only the owners of '{name}' can change its plans; "
            "you have read-only visibility.",
        },
    )


async def ensure_initiative_editable(
    session: AsyncSession, user: User, initiative_id: int | None
) -> None:
    """403 when a planner-role user tries an initiative-level write they do not own.

    Non-planner roles pass through (their role gate decides); `None` (no initiative) is unscoped.
    """
    if initiative_id is None or user.role == UserRole.admin or user.role not in OWNERSHIP_ROLES:
        return
    if await initiative_can_edit(session, user, initiative_id):
        return
    initiative = await session.get(Initiative, initiative_id)
    raise _denied(initiative.name if initiative is not None else f"#{initiative_id}", initiative_id)


async def ensure_project_editable(session: AsyncSession, user: User, project_id: int) -> None:
    """403 when a planner-role user tries a project write outside what they own or direct."""
    if user.role == UserRole.admin or user.role not in OWNERSHIP_ROLES:
        return
    project = await session.get(Project, project_id)
    if project is None:
        return  # the handler raises its own 404
    if await project_can_edit(session, user, project):
        return
    raise _denied(project.name, project.initiative_id)


async def ensure_task_editable(session: AsyncSession, user: User, task_id: int) -> None:
    task = await session.get(Task, task_id)
    if task is None:
        return
    await ensure_project_editable(session, user, task.project_id)
