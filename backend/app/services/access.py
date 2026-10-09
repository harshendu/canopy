"""Ownership-scoped editing: an initiative's lead team edits it; everyone else reads it.

The role matrix (`app/api/deps.py`) says *what kind* of write a role may make; this layer says
*where*. A planner-role user (architect / engineering manager / legacy member) may make planning
writes only inside the initiatives they lead (`InitiativeLead`), and reads every other
initiative — complete lateral visibility, no cross-team edits. Admins are exempt, and an
initiative with **no leads at all** keeps the plain role-based rules, so installs that never set
up lead teams (and the Helix demo) behave exactly as before. Contributor-level writes by
engineers (their own task progress, blockers, criterion verdicts, decision comments) are not
scoped here — they remain governed by role alone.

Every check resolves the entity up to its initiative; a project outside any initiative is
unscoped. Raises 403 with a machine-readable `code` so the UI can explain *why*.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.models.base import UserRole
from app.models.leadership import InitiativeLead
from app.models.project import Initiative, Project, Task
from app.models.team import Engineer
from app.models.user import User

# Roles whose writes are scoped by lead-team ownership (admin is exempt; engineer/viewer writes
# are decided by role alone).
OWNERSHIP_ROLES = frozenset({UserRole.architect, UserRole.engineering_manager, UserRole.member})


async def engineer_ids_for_user(session: AsyncSession, user: User) -> set[int]:
    rows = (
        await session.execute(select(Engineer.id).where(Engineer.user_id == user.id))
    ).scalars().all()
    return {e for e in rows if e is not None}


async def led_initiative_ids(session: AsyncSession, user: User) -> set[int]:
    """Initiatives the user sits on the core team of (via their linked Engineer rows)."""
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


async def initiative_has_leads(session: AsyncSession, initiative_id: int) -> bool:
    row = (
        await session.execute(
            select(InitiativeLead.id).where(InitiativeLead.initiative_id == initiative_id).limit(1)
        )
    ).scalar_one_or_none()
    return row is not None


def can_edit(user: User, *, has_leads: bool, is_lead: bool) -> bool:
    """Pure decision: may this user make planning writes inside the initiative?"""
    if user.role == UserRole.admin:
        return True
    if user.role not in OWNERSHIP_ROLES:
        return False
    return is_lead or not has_leads


async def initiative_can_edit(session: AsyncSession, user: User, initiative_id: int) -> bool:
    has_leads = await initiative_has_leads(session, initiative_id)
    is_lead = initiative_id in await led_initiative_ids(session, user) if has_leads else False
    return can_edit(user, has_leads=has_leads, is_lead=is_lead)


async def ensure_initiative_editable(
    session: AsyncSession, user: User, initiative_id: int | None
) -> None:
    """403 when a planner-role user tries to write inside an initiative they do not lead.

    Non-planner roles pass through (their role gate decides); `None` (no initiative) is unscoped.
    """
    if initiative_id is None or user.role == UserRole.admin or user.role not in OWNERSHIP_ROLES:
        return
    if not await initiative_has_leads(session, initiative_id):
        return
    if initiative_id in await led_initiative_ids(session, user):
        return
    initiative = await session.get(Initiative, initiative_id)
    name = initiative.name if initiative is not None else f"#{initiative_id}"
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": "not_initiative_lead",
            "initiative_id": initiative_id,
            "message": f"Only the lead team of '{name}' can change its plans; "
            "you have read-only visibility.",
        },
    )


async def ensure_project_editable(session: AsyncSession, user: User, project_id: int) -> None:
    project = await session.get(Project, project_id)
    if project is None:
        return  # the handler raises its own 404
    await ensure_initiative_editable(session, user, project.initiative_id)


async def ensure_task_editable(session: AsyncSession, user: User, task_id: int) -> None:
    task = await session.get(Task, task_id)
    if task is None:
        return
    await ensure_project_editable(session, user, task.project_id)
