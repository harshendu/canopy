"""The engineer workspace (`/me`): the current user's own surface — their assigned
tasks and the decisions they own or must review. The user is mapped to a team member
via `Engineer.user_id`."""

from datetime import date, timedelta

from fastapi import APIRouter
from sqlmodel import col, select

from app.api.deps import CurrentUser, SessionDep
from app.api.v1.architecture import _adr_read, _component_ids, _stakeholder_ids
from app.models.architecture import ADRStakeholder, ArchitectureDecision
from app.models.base import ADRStatus, TaskType
from app.models.project import Task
from app.models.team import Engineer
from app.schemas.auth import UserRead
from app.schemas.entities import (
    ADRRead,
    EngineerRead,
    MyTodayResponse,
    MyWorkspaceResponse,
    TaskRead,
)

router = APIRouter()


@router.get("/workspace", response_model=MyWorkspaceResponse)
async def my_workspace(session: SessionDep, user: CurrentUser) -> MyWorkspaceResponse:
    engineer = (
        await session.execute(select(Engineer).where(Engineer.user_id == user.id))
    ).scalars().first()

    assigned: list[TaskRead] = []
    owned: list[ADRRead] = []
    stakeholder: list[ADRRead] = []

    if engineer is not None and engineer.id is not None:
        tasks = (
            await session.execute(
                select(Task).where(Task.assignee_engineer_id == engineer.id)
            )
        ).scalars().all()
        # Open leaf tasks, most-critical (then soonest) first.
        open_tasks = [
            t for t in tasks if t.type != TaskType.summary and t.percent_complete < 100
        ]
        open_tasks.sort(key=lambda t: (not t.is_critical, t.end or date.max))
        assigned = [TaskRead.model_validate(t) for t in open_tasks]

        async def to_read(adr: ArchitectureDecision) -> ADRRead:
            assert adr.id is not None
            return _adr_read(
                adr,
                await _component_ids(session, adr.id),
                await _stakeholder_ids(session, adr.id),
            )

        owned_adrs = (
            await session.execute(
                select(ArchitectureDecision).where(
                    ArchitectureDecision.decision_owner_id == engineer.id
                )
            )
        ).scalars().all()
        owned = [await to_read(a) for a in owned_adrs if a.id is not None]

        stake_ids = list(
            (
                await session.execute(
                    select(ADRStakeholder.adr_id).where(
                        ADRStakeholder.engineer_id == engineer.id
                    )
                )
            ).scalars().all()
        )
        if stake_ids:
            stake_adrs = (
                await session.execute(
                    select(ArchitectureDecision).where(col(ArchitectureDecision.id).in_(stake_ids))
                )
            ).scalars().all()
            stakeholder = [await to_read(a) for a in stake_adrs if a.id is not None]

    return MyWorkspaceResponse(
        user=UserRead.model_validate(user),
        engineer=EngineerRead.model_validate(engineer) if engineer is not None else None,
        assigned_tasks=assigned,
        owned_decisions=owned,
        stakeholder_decisions=stakeholder,
    )


@router.get("/today", response_model=MyTodayResponse)
async def my_today(session: SessionDep, user: CurrentUser) -> MyTodayResponse:
    """The daily focus view: today's most-pressing assigned work and the one or two
    decisions to push on."""
    engineer = (
        await session.execute(select(Engineer).where(Engineer.user_id == user.id))
    ).scalars().first()

    focus: list[TaskRead] = []
    decisions: list[ADRRead] = []
    if engineer is not None and engineer.id is not None:
        horizon = date.today() + timedelta(days=7)
        tasks = (
            await session.execute(
                select(Task).where(Task.assignee_engineer_id == engineer.id)
            )
        ).scalars().all()
        focus_tasks = [
            t
            for t in tasks
            if t.type != TaskType.summary
            and t.percent_complete < 100
            and (t.is_critical or (t.end is not None and t.end <= horizon))
        ]
        focus_tasks.sort(key=lambda t: (not t.is_critical, t.end or date.max))
        focus = [TaskRead.model_validate(t) for t in focus_tasks]

        owned = (
            await session.execute(
                select(ArchitectureDecision).where(
                    ArchitectureDecision.decision_owner_id == engineer.id,
                    col(ArchitectureDecision.status).in_(
                        [ADRStatus.proposed, ADRStatus.under_discussion]
                    ),
                )
            )
        ).scalars().all()
        decisions = [
            _adr_read(
                a, await _component_ids(session, a.id), await _stakeholder_ids(session, a.id)
            )
            for a in owned
            if a.id is not None
        ]

    return MyTodayResponse(
        user=UserRead.model_validate(user), focus_tasks=focus, decisions_to_push=decisions
    )
