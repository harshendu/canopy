"""Leadership notes + the business review — the executive layer's write surface.

Executives (``function == leadership``) and admins leave **notes** on a specific view: something
to *watch*, a *priority* call, or free-form *feedback*, optionally pinned to a decision / risk /
outcome / milestone inside an initiative or project. The initiative's lead team acknowledges or
resolves each note with a response, so the loop closes where the work is. ``GET /review`` rolls
every initiative up for a monthly business review: lead team, headline health, outcomes, and the
notes still open. Gate: ``portfolio.leadership``.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, status
from sqlmodel import col, select

from app.api.deps import CurrentUser, SessionDep
from app.api.v1.initiatives import initiative_rollup, lead_reads
from app.api.v1.teams import team_reads
from app.models.architecture import ArchitectureDecision
from app.models.base import (
    ADRStatus,
    LeadershipNoteStatus,
    LeadershipScope,
    LeadershipTargetKind,
    OutcomeScope,
    UserFunction,
    UserRole,
)
from app.models.leadership import LeadershipNote
from app.models.outcome import Outcome
from app.models.project import Blocker, Initiative, Milestone, Project, Task
from app.models.risk_register import RiskItem
from app.models.user import User
from app.schemas.leadership import (
    BusinessReview,
    LeadershipNoteCreate,
    LeadershipNoteRead,
    LeadershipNoteUpdate,
    ReviewInitiative,
    ReviewOutcome,
)
from app.services.access import directed_team_ids, initiative_can_edit

router = APIRouter()


async def _is_leadership(session: SessionDep, user: User) -> bool:
    """Heads of engineering/product (the leadership persona), team directors, or an admin."""
    if user.role == UserRole.admin or user.function == UserFunction.leadership:
        return True
    return bool(await directed_team_ids(session, user))


async def _validate_scope(
    session: SessionDep, scope_level: LeadershipScope, scope_id: int
) -> None:
    model = Initiative if scope_level == LeadershipScope.initiative else Project
    if await session.get(model, scope_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{scope_level.value} {scope_id} not found",
        )


async def _target_label(
    session: SessionDep, kind: LeadershipTargetKind | None, target_id: int | None
) -> str | None:
    """Resolve the human label of a finer target (captured at write time)."""
    if kind is None or target_id is None:
        return None
    if kind == LeadershipTargetKind.decision:
        adr = await session.get(ArchitectureDecision, target_id)
        return f"ADR-{adr.number:04d} {adr.title}" if adr is not None else None
    if kind == LeadershipTargetKind.risk:
        risk = await session.get(RiskItem, target_id)
        return risk.title if risk is not None else None
    if kind == LeadershipTargetKind.outcome:
        outcome = await session.get(Outcome, target_id)
        return outcome.statement if outcome is not None else None
    milestone = await session.get(Milestone, target_id)
    return milestone.name if milestone is not None else None


async def _initiative_of_scope(
    session: SessionDep, scope_level: LeadershipScope, scope_id: int
) -> int | None:
    if scope_level == LeadershipScope.initiative:
        return scope_id
    project = await session.get(Project, scope_id)
    return project.initiative_id if project is not None else None


async def _reads(session: SessionDep, notes: list[LeadershipNote]) -> list[LeadershipNoteRead]:
    ids = {n.author_user_id for n in notes} | {
        n.responded_by_user_id for n in notes if n.responded_by_user_id is not None
    }
    names: dict[int, str] = {}
    if ids:
        for u in (await session.execute(select(User).where(col(User.id).in_(ids)))).scalars():
            if u.id is not None:
                names[u.id] = u.full_name or u.email
    out: list[LeadershipNoteRead] = []
    for n in notes:
        read = LeadershipNoteRead.model_validate(n)
        read.author_name = names.get(n.author_user_id)
        if n.responded_by_user_id is not None:
            read.responded_by_name = names.get(n.responded_by_user_id)
        out.append(read)
    return out


@router.get("/notes", response_model=list[LeadershipNoteRead])
async def list_notes(
    session: SessionDep,
    _: CurrentUser,
    scope_level: LeadershipScope | None = None,
    scope_id: int | None = None,
    status: LeadershipNoteStatus | None = None,
) -> list[LeadershipNoteRead]:
    """Leadership notes, newest first; filter by scope and/or status. Reads are open."""
    stmt = select(LeadershipNote)
    if scope_level is not None:
        stmt = stmt.where(LeadershipNote.scope_level == scope_level)
    if scope_id is not None:
        stmt = stmt.where(LeadershipNote.scope_id == scope_id)
    if status is not None:
        stmt = stmt.where(LeadershipNote.status == status)
    rows = list((await session.execute(stmt.order_by(col(LeadershipNote.id).desc()))).scalars())
    return await _reads(session, rows)


@router.post("/notes", response_model=LeadershipNoteRead, status_code=status.HTTP_201_CREATED)
async def create_note(
    session: SessionDep, user: CurrentUser, payload: LeadershipNoteCreate
) -> LeadershipNoteRead:
    """Leave a note on a view. Leadership persona, a team director, or an admin."""
    if not await _is_leadership(session, user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only leadership (heads, team directors) or an admin can leave leadership notes",
        )
    await _validate_scope(session, payload.scope_level, payload.scope_id)
    label = await _target_label(session, payload.target_kind, payload.target_id)
    if payload.target_kind is not None and label is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target not found")
    assert user.id is not None
    note = LeadershipNote(
        **payload.model_dump(), target_label=label, author_user_id=user.id
    )
    session.add(note)
    await session.commit()
    await session.refresh(note)
    return (await _reads(session, [note]))[0]


@router.patch("/notes/{note_id}", response_model=LeadershipNoteRead)
async def update_note(
    session: SessionDep, user: CurrentUser, note_id: int, payload: LeadershipNoteUpdate
) -> LeadershipNoteRead:
    """The author edits body/priority; the scope's lead team (or admin) acknowledges / resolves
    with a response."""
    note = await session.get(LeadershipNote, note_id)
    if note is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
    data = payload.model_dump(exclude_unset=True)
    is_author = note.author_user_id == user.id
    touches_content = "body" in data or "priority" in data
    touches_response = "status" in data or "response" in data
    if touches_content and not (is_author or user.role == UserRole.admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only the author can edit a note"
        )
    if touches_response:
        initiative_id = await _initiative_of_scope(session, note.scope_level, note.scope_id)
        allowed = user.role == UserRole.admin or is_author
        if not allowed and initiative_id is not None:
            allowed = await initiative_can_edit(session, user, initiative_id)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the lead team of this initiative can respond to a note",
            )
        if not is_author or "response" in data:
            from app.models.base import utcnow

            note.responded_by_user_id = user.id
            note.responded_at = utcnow()
    for field, value in data.items():
        setattr(note, field, value)
    await session.commit()
    await session.refresh(note)
    return (await _reads(session, [note]))[0]


@router.delete("/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_note(session: SessionDep, user: CurrentUser, note_id: int) -> None:
    note = await session.get(LeadershipNote, note_id)
    if note is None:
        return
    if note.author_user_id != user.id and user.role != UserRole.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only the author can delete a note"
        )
    await session.delete(note)
    await session.commit()


@router.get("/review", response_model=BusinessReview)
async def business_review(session: SessionDep, user: CurrentUser) -> BusinessReview:
    """The monthly-business-review roll-up across every initiative (reads are open)."""
    initiatives = list(
        (
            await session.execute(
                select(Initiative)
                .where(col(Initiative.archived).is_(False))
                .order_by(col(Initiative.name))
            )
        ).scalars()
    )
    open_notes = list(
        (
            await session.execute(
                select(LeadershipNote)
                .where(LeadershipNote.status != LeadershipNoteStatus.resolved)
                .order_by(col(LeadershipNote.id).desc())
            )
        ).scalars()
    )
    note_reads = await _reads(session, open_notes)
    out: list[ReviewInitiative] = []
    attention: list[str] = []
    for init in initiatives:
        assert init.id is not None
        rollup = await initiative_rollup(session, user, init.id)
        project_ids = [p.id for p in rollup.projects]
        outcomes = list(
            (
                await session.execute(
                    select(Outcome).where(
                        Outcome.scope_level == OutcomeScope.initiative,
                        Outcome.scope_id == init.id,
                    )
                )
            ).scalars()
        )
        open_blockers = 0
        if project_ids:
            task_ids = set(
                (
                    await session.execute(
                        select(Task.id).where(col(Task.project_id).in_(project_ids))
                    )
                ).scalars()
            )
            if task_ids:
                open_blockers = len(
                    list(
                        (
                            await session.execute(
                                select(Blocker.id).where(
                                    col(Blocker.task_id).in_(task_ids),
                                    col(Blocker.resolved_at).is_(None),
                                )
                            )
                        ).scalars()
                    )
                )
        notes_here = [
            n
            for n in note_reads
            if (n.scope_level == LeadershipScope.initiative and n.scope_id == init.id)
            or (n.scope_level == LeadershipScope.project and n.scope_id in project_ids)
        ]
        if rollup.on_track is False:
            attention.append(f"{init.name}: behind its target date.")
        if rollup.risk_level in {"high", "critical"}:
            attention.append(f"{init.name}: risk is {rollup.risk_level}.")
        priorities = [n for n in notes_here if n.kind == "priority" and n.status != "resolved"]
        if priorities:
            attention.append(f"{init.name}: {len(priorities)} open leadership priority call(s).")
        out.append(
            ReviewInitiative(
                id=init.id,
                key=init.key,
                name=init.name,
                outcome_statement=init.outcome_statement,
                target_date=init.target_date,
                health=init.health,
                status_note=init.status_note,
                leads=await lead_reads(session, init.id),
                team_id=init.team_id,
                pods=rollup.pods,
                project_count=len(rollup.projects),
                avg_percent_complete=rollup.avg_percent_complete,
                project_end=rollup.project_end,
                on_track=rollup.on_track,
                risk_score=rollup.risk_score,
                risk_level=rollup.risk_level,
                drift_score=rollup.drift_score,
                drift_level=rollup.drift_level,
                open_decisions=rollup.open_decisions,
                open_blockers=open_blockers,
                outcomes=[
                    ReviewOutcome(
                        id=o.id or 0,
                        statement=o.statement,
                        status=o.status.value,
                        current_value=o.current_value,
                        target_value=o.target_value,
                        unit=o.unit,
                    )
                    for o in outcomes
                ],
                open_notes=notes_here,
            )
        )
    # Unused-but-informative: decisions stuck across the portfolio feed the attention list too.
    stuck = len(
        list(
            (
                await session.execute(
                    select(ArchitectureDecision.id).where(
                        ArchitectureDecision.status == ADRStatus.under_discussion
                    )
                )
            ).scalars()
        )
    )
    if stuck:
        attention.append(f"{stuck} decision(s) still under discussion across the portfolio.")
    return BusinessReview(
        generated_on=date.today(),
        teams=await team_reads(session),
        initiatives=out,
        open_note_count=len(note_reads),
        attention=attention,
    )
