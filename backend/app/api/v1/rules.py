"""Delivery rules — team and project working agreements and the Definition of Done
(docs/AGENT_EXECUTION.md §10, §13; feature gate `ai.stage_policy`).

Reads are open. Writes are human-only: the workspace's rules — an admin; a team's — its directors
and managers; a project's — planners who may edit it.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ContributorWriter, CurrentUser, HumanOnly, SessionDep, TokenScopeDep
from app.core.events import publish
from app.models.architecture import ArchitectureDecision
from app.models.base import RuleScope, TokenScope, UserRole, utcnow
from app.models.org import Team
from app.models.policy import DeliveryRule
from app.models.project import Project
from app.models.user import User
from app.schemas.policy import EffectiveRuleRead, RuleCreate, RuleRead, RuleUpdate
from app.services import rules as rules_service
from app.services.access import project_can_edit, team_can_manage

router = APIRouter()


async def may_edit(session: AsyncSession, user: User, level: str, scope_id: int) -> bool:
    if user.role == UserRole.admin:
        return True
    if level == RuleScope.team.value:
        return await team_can_manage(session, user, scope_id)
    if level == RuleScope.project.value:
        project = await session.get(Project, scope_id)
        return (
            project is not None
            and user.role in (UserRole.architect, UserRole.engineering_manager, UserRole.member)
            and await project_can_edit(session, user, project)
        )
    return False  # the workspace's rules: admins only


async def _ensure_may_edit(session: AsyncSession, user: User, level: str, scope_id: int) -> None:
    if not await may_edit(session, user, level, scope_id):
        raise HTTPException(status_code=403, detail={
            "code": "not_permitted",
            "message": {
                RuleScope.workspace.value: "Only an admin edits the workspace's rules",
                RuleScope.team.value: "Only the team's directors and managers edit its rules",
            }.get(level, "Only planners who may edit the project edit its rules"),
        })


async def _ensure_scope(session: AsyncSession, level: str, scope_id: int) -> None:
    if level == RuleScope.workspace.value:
        if scope_id != 0:
            raise HTTPException(status_code=422, detail={
                "code": "bad_scope", "message": "The workspace's rules use scope_id 0"})
        return
    model = Team if level == RuleScope.team.value else Project
    if await session.get(model, scope_id) is None:
        raise HTTPException(status_code=404, detail=f"{level.title()} not found")


async def _ensure_adr(session: AsyncSession, adr_id: int | None) -> None:
    if adr_id is not None and await session.get(ArchitectureDecision, adr_id) is None:
        raise HTTPException(status_code=422, detail={
            "code": "unknown_adr", "message": "No such decision"})


def _clean_roles(roles: list[str]) -> list[str]:
    from app.services.agent_tokens import ROLE_KEY_RE

    out: list[str] = []
    for raw in roles:
        role = raw.strip().lower()
        if not ROLE_KEY_RE.match(role):
            raise HTTPException(status_code=422, detail={
                "code": "bad_role", "message": f"{raw!r} is not a role key"})
        if role not in out:
            out.append(role)
    return out


@router.get("/rules", response_model=list[RuleRead])
async def list_rules(
    session: SessionDep, _: CurrentUser, scope_level: str = RuleScope.workspace.value,
    scope_id: int = 0,
) -> list[DeliveryRule]:
    """The rules defined at one scope (`workspace` with id 0, a team, or a project)."""
    return await rules_service.scope_rules(session, scope_level, scope_id)


@router.get("/rules/effective", response_model=list[EffectiveRuleRead])
async def effective_rules(
    session: SessionDep, user: CurrentUser, scope: TokenScopeDep, project_id: int
) -> list[EffectiveRuleRead]:
    """A project's resolved rules — workspace, then team, then project; nearest wins unless a
    rule is locked; for attestations the stricter enforcement wins — each with its origin and
    whether its source decision moved on (stale)."""
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    out: list[EffectiveRuleRead] = []
    for e in await rules_service.effective_rules(session, project):
        can_edit = scope != TokenScope.agent and await may_edit(
            session, user, e.rule.scope_level, e.rule.scope_id)
        out.append(EffectiveRuleRead(
            rule=RuleRead.model_validate(e.rule), origin=e.origin, overrides=e.overrides,
            enforcement=e.enforcement, stale=e.stale, stale_reason=e.stale_reason,
            can_edit=can_edit,
        ))
    return out


@router.post("/rules", response_model=RuleRead, status_code=status.HTTP_201_CREATED)
async def create_rule(
    session: SessionDep, user: ContributorWriter, _human: HumanOnly, payload: RuleCreate
) -> DeliveryRule:
    """Add a rule at a scope (human-only). A `key` an outer scope already uses overrides it
    here, unless that one is locked."""
    await _ensure_scope(session, payload.scope_level, payload.scope_id)
    await _ensure_may_edit(session, user, payload.scope_level, payload.scope_id)
    await _ensure_adr(session, payload.source_adr_id)
    rule = DeliveryRule(
        scope_level=payload.scope_level, scope_id=payload.scope_id, key=payload.key,
        title=payload.title.strip(), body=payload.body.strip(), kind=payload.kind,
        roles=_clean_roles(payload.roles), selector=payload.selector.model_dump(),
        enforcement=payload.enforcement, locked=payload.locked, disabled=payload.disabled,
        source_adr_id=payload.source_adr_id, source_url=payload.source_url,
        created_by_user_id=user.id,
    )
    session.add(rule)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail={
            "code": "rule_exists",
            "message": f"This scope already has a rule {payload.key!r} — edit it instead"},
        ) from exc
    await session.refresh(rule)
    await publish({"type": "rules", "scope_level": rule.scope_level, "scope_id": rule.scope_id})
    return rule


async def _rule(session: AsyncSession, rule_id: int) -> DeliveryRule:
    rule = await session.get(DeliveryRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    return rule


@router.patch("/rules/{rule_id}", response_model=RuleRead)
async def update_rule(
    session: SessionDep, user: ContributorWriter, _human: HumanOnly, rule_id: int,
    payload: RuleUpdate,
) -> DeliveryRule:
    rule = await _rule(session, rule_id)
    await _ensure_may_edit(session, user, rule.scope_level, rule.scope_id)
    data = payload.model_dump(exclude_unset=True)
    if "source_adr_id" in data:
        await _ensure_adr(session, data["source_adr_id"])
    if "roles" in data and data["roles"] is not None:
        data["roles"] = _clean_roles(data["roles"])
    if "selector" in data and data["selector"] is not None:
        data["selector"] = dict(data["selector"])
    for name, value in data.items():
        if value is None and name not in ("source_adr_id", "source_url"):
            continue
        setattr(rule, name, value.strip() if isinstance(value, str) and name in (
            "title", "body") else value)
    rule.updated_at = utcnow()
    await session.commit()
    await session.refresh(rule)
    await publish({"type": "rules", "scope_level": rule.scope_level, "scope_id": rule.scope_id})
    return rule


@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    session: SessionDep, user: ContributorWriter, _human: HumanOnly, rule_id: int
) -> None:
    rule = await _rule(session, rule_id)
    await _ensure_may_edit(session, user, rule.scope_level, rule.scope_id)
    level, scope_id = rule.scope_level, rule.scope_id
    await session.delete(rule)
    await session.commit()
    await publish({"type": "rules", "scope_level": level, "scope_id": scope_id})
