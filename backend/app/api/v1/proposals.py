"""Change proposals: agents stage canopy writes; a human reviews and commits them in the UI.

The bounded-agency posture (§A6) is structural here: **staging** is a reversible
two-way-door action open to contributors and agent tokens, while **apply / reject /
per-item review** are `HumanOnly` planner actions — an agent token gets 403, so the
change can only land through a person in the review queue. Withdraw stays open to the
author (the agent cleaning up after itself is reversible).
"""

from fastapi import APIRouter, HTTPException, status
from sqlmodel import col, select

from app.api.deps import (
    ContributorWriter,
    CurrentUser,
    HumanOnly,
    PlannerWriter,
    SessionDep,
    is_planner,
)
from app.core.events import publish
from app.models.base import ProposalAction, ProposalScope, ProposalStatus, utcnow
from app.models.project import Initiative, Project
from app.models.proposal import Proposal, ProposalItem
from app.schemas.proposal import (
    ProposalApplyResult,
    ProposalCreate,
    ProposalDetail,
    ProposalItemDetail,
    ProposalItemPatch,
    ProposalItemRead,
    ProposalRead,
    ProposalRejectRequest,
)
from app.services import proposals as svc
from app.services.scheduling import CycleError

router = APIRouter()


async def _get_proposal(session: SessionDep, proposal_id: int) -> Proposal:
    proposal = await session.get(Proposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found")
    return proposal


def _require_open(proposal: Proposal) -> None:
    if proposal.status != ProposalStatus.open:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Proposal is already {proposal.status.value}",
        )


async def _scope_label(session: SessionDep, proposal: Proposal) -> str | None:
    if proposal.scope_level == ProposalScope.project:
        project = await session.get(Project, proposal.scope_id)
        return f"{project.key} · {project.name}" if project else None
    initiative = await session.get(Initiative, proposal.scope_id)
    return f"{initiative.key} · {initiative.name}" if initiative else None


def _action_counts(items: list[ProposalItem]) -> dict[str, int]:
    """Per-action tally (create/update/resolve) for the collapsed-card shape chip. Pure."""
    counts: dict[str, int] = {}
    for item in items:
        counts[item.action.value] = counts.get(item.action.value, 0) + 1
    return counts


async def _item_needs_attention(
    session: SessionDep, proposal: Proposal, item: ProposalItem
) -> bool:
    """An item a reviewer should look at before applying: it carries a stored validation error,
    or (while open, for a non-create) its live target has drifted from the stage-time snapshot."""
    if item.error:
        return True
    if proposal.status != ProposalStatus.open or item.action == ProposalAction.create:
        return False
    current = await svc.snapshot_target(session, item)
    return current != item.before


async def _read(session: SessionDep, proposal: Proposal) -> ProposalRead:
    items = await svc.load_items(session, proposal)
    view = ProposalRead.model_validate(proposal)
    view.item_count = len(items)
    view.excluded_count = sum(1 for i in items if i.excluded)
    view.action_counts = _action_counts(items)
    attention = 0
    for item in items:
        if await _item_needs_attention(session, proposal, item):
            attention += 1
    view.attention_count = attention
    view.scope_label = await _scope_label(session, proposal)
    return view


@router.get("", response_model=list[ProposalRead])
async def list_proposals(
    session: SessionDep,
    _: CurrentUser,
    scope_level: ProposalScope | None = None,
    scope_id: int | None = None,
    status: ProposalStatus | None = None,
) -> list[ProposalRead]:
    stmt = select(Proposal)
    if scope_level is not None:
        stmt = stmt.where(Proposal.scope_level == scope_level)
    if scope_id is not None:
        stmt = stmt.where(Proposal.scope_id == scope_id)
    if status is not None:
        stmt = stmt.where(Proposal.status == status)
    rows = await session.execute(stmt.order_by(col(Proposal.id).desc()))
    return [await _read(session, p) for p in rows.scalars().all()]


@router.post("", response_model=ProposalDetail, status_code=status.HTTP_201_CREATED)
async def create_proposal(
    session: SessionDep, user: ContributorWriter, payload: ProposalCreate
) -> ProposalDetail:
    """Stage a batch of changes for human review. Strict at the door: any invalid item
    rejects the whole proposal (400 with per-item errors) so the author fixes it now,
    not the reviewer later. Open to agent tokens — staging is reversible."""
    if not await svc.scope_exists(session, payload.scope_level, payload.scope_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{payload.scope_level.value} {payload.scope_id} not found",
        )
    items = [
        ProposalItem(
            proposal_id=0,  # patched after flush
            sort_order=index,
            entity_type=item.entity_type,
            action=item.action,
            entity_id=item.entity_id,
            ref=item.ref,
            payload=dict(item.payload),
            reason=item.reason,
            source_kind=item.source_kind,
            source_label=item.source_label,
            source_url=item.source_url,
        )
        for index, item in enumerate(payload.items)
    ]
    issues = await svc.check_items(session, payload.scope_level, payload.scope_id, items)
    if issues:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "invalid_items",
                "errors": [{"index": i.index, "error": i.error} for i in issues],
            },
        )
    proposal = Proposal(
        scope_level=payload.scope_level,
        scope_id=payload.scope_id,
        title=payload.title,
        summary=payload.summary,
        origin=payload.origin,
        created_by_user_id=user.id,
    )
    session.add(proposal)
    await session.flush()
    assert proposal.id is not None
    for item in items:
        item.proposal_id = proposal.id
        item.before = await svc.snapshot_target(session, item)
        session.add(item)
    await session.commit()
    await session.refresh(proposal)
    await publish(
        {
            "type": "proposal",
            "proposal_id": proposal.id,
            "status": proposal.status.value,
            "scope_level": proposal.scope_level.value,
            "scope_id": proposal.scope_id,
        }
    )
    return await _detail(session, proposal)


async def _detail(session: SessionDep, proposal: Proposal) -> ProposalDetail:
    items = await svc.load_items(session, proposal)
    detail_items: list[ProposalItemDetail] = []
    for item in items:
        view = ProposalItemDetail.model_validate(item)
        if proposal.status == ProposalStatus.open and item.action != ProposalAction.create:
            view.current = await svc.snapshot_target(session, item)
            view.stale = view.current != item.before
        detail_items.append(view)
    header = await _read(session, proposal)
    return ProposalDetail(**header.model_dump(), items=detail_items)


@router.get("/{proposal_id}", response_model=ProposalDetail)
async def get_proposal(session: SessionDep, _: CurrentUser, proposal_id: int) -> ProposalDetail:
    """The full review view: items with payloads, provenance, the stage-time `before`
    snapshot, and (while open) the live `current` values + a `stale` flag."""
    proposal = await _get_proposal(session, proposal_id)
    return await _detail(session, proposal)


@router.patch("/{proposal_id}/items/{item_id}", response_model=ProposalItemRead)
async def review_item(
    session: SessionDep,
    _: PlannerWriter,
    __: HumanOnly,
    proposal_id: int,
    item_id: int,
    payload: ProposalItemPatch,
) -> ProposalItem:
    """Include/exclude one item before applying (the reviewer's line-item veto)."""
    proposal = await _get_proposal(session, proposal_id)
    _require_open(proposal)
    item = await session.get(ProposalItem, item_id)
    if item is None or item.proposal_id != proposal_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    item.excluded = payload.excluded
    await session.commit()
    await session.refresh(item)
    return item


@router.post("/{proposal_id}/apply", response_model=ProposalApplyResult)
async def apply_proposal(
    session: SessionDep, user: PlannerWriter, _: HumanOnly, proposal_id: int
) -> ProposalApplyResult:
    """Commit every included item to canopy (all-or-nothing), then replan the affected
    projects. Human-only: an agent token cannot apply its own staged changes."""
    proposal = await _get_proposal(session, proposal_id)
    _require_open(proposal)
    try:
        outcome = await svc.apply_proposal(session, proposal, user.id)
    except svc.ProposalValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "invalid_items",
                "errors": [
                    {"index": i.index, "item_id": i.item_id, "error": i.error}
                    for i in exc.issues
                ],
            },
        ) from exc
    except CycleError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Applying these changes would create a dependency cycle",
        ) from exc
    return ProposalApplyResult(
        proposal=await _read(session, proposal),
        applied=outcome.applied,
        skipped=outcome.skipped,
        replanned_projects=outcome.replanned_projects,
    )


@router.post("/{proposal_id}/reject", response_model=ProposalRead)
async def reject_proposal(
    session: SessionDep,
    user: PlannerWriter,
    _: HumanOnly,
    proposal_id: int,
    payload: ProposalRejectRequest,
) -> ProposalRead:
    """Turn a proposal down with an optional note — the author (often the agent) reads the
    note and stages a better one."""
    proposal = await _get_proposal(session, proposal_id)
    _require_open(proposal)
    proposal.status = ProposalStatus.rejected
    proposal.reviewed_by_user_id = user.id
    proposal.reviewed_at = utcnow()
    proposal.review_note = payload.note
    await session.commit()
    await publish(
        {
            "type": "proposal",
            "proposal_id": proposal.id,
            "status": proposal.status.value,
            "scope_level": proposal.scope_level.value,
            "scope_id": proposal.scope_id,
        }
    )
    return await _read(session, proposal)


@router.post("/{proposal_id}/withdraw", response_model=ProposalRead)
async def withdraw_proposal(
    session: SessionDep, user: ContributorWriter, proposal_id: int
) -> ProposalRead:
    """The author pulls an open proposal back (agents allowed — cleaning up your own
    staged, never-applied change is reversible). Planners may withdraw any proposal."""
    proposal = await _get_proposal(session, proposal_id)
    _require_open(proposal)
    if proposal.created_by_user_id != user.id and not is_planner(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the proposal's author (or a planner) may withdraw it",
        )
    proposal.status = ProposalStatus.withdrawn
    proposal.reviewed_at = utcnow()
    await session.commit()
    await publish(
        {
            "type": "proposal",
            "proposal_id": proposal.id,
            "status": proposal.status.value,
            "scope_level": proposal.scope_level.value,
            "scope_id": proposal.scope_id,
        }
    )
    return await _read(session, proposal)
