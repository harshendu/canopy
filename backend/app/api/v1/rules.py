"""Delivery rules — team and project working agreements and the Definition of Done
(docs/AGENT_EXECUTION.md §10, §13; feature gate `ai.stage_policy`).

Reads are open. Writes are human-only: the workspace's rules — an admin; a team's — its directors
and managers; a project's — planners who may edit it.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.api.deps import ContributorWriter, CurrentUser, HumanOnly, SessionDep, TokenScopeDep
from app.core.events import publish
from app.models.architecture import ArchitectureDecision
from app.models.base import RuleScope, TokenScope, UserRole, utcnow
from app.models.org import Team
from app.models.policy import DeliveryRule
from app.models.project import Project
from app.models.user import User
from app.schemas.policy import (
    EffectiveRuleRead,
    RuleCreate,
    RuleRead,
    RuleScopeRead,
    RuleSuggestionExample,
    RuleSuggestionRead,
    RuleUpdate,
)
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


async def scopes_for(
    session: AsyncSession, user: User, scope: TokenScope, *, project_id: int | None,
    team_id: int | None,
) -> list[RuleScopeRead]:
    """The scopes that reach a project (workspace, its team, itself) or a team (workspace,
    itself), broadest first, each with whether the caller may edit it — shared by rules and
    outbound webhooks, which follow the same permission model. Agent tokens edit none."""
    from app.services.org import project_team_id

    project: Project | None = None
    if project_id is not None:
        project = await session.get(Project, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        team_id = await project_team_id(session, project)
    elif team_id is None:
        raise HTTPException(status_code=422, detail={
            "code": "scope_required", "message": "Pass project_id or team_id"})
    levels: list[tuple[str, int, str]] = [(RuleScope.workspace.value, 0, "Workspace")]
    if team_id is not None:
        team = await session.get(Team, team_id)
        if team is None:
            if project is None:
                raise HTTPException(status_code=404, detail="Team not found")
        else:
            levels.append((RuleScope.team.value, team_id, team.name))
    if project is not None and project.id is not None:
        levels.append((RuleScope.project.value, project.id, project.name))
    return [
        RuleScopeRead(
            scope_level=level, scope_id=scope_id, name=name,
            can_edit=scope != TokenScope.agent and await may_edit(session, user, level, scope_id),
        )
        for level, scope_id, name in levels
    ]


@router.get("/rules/scopes", response_model=list[RuleScopeRead])
async def rule_scopes(
    session: SessionDep, user: CurrentUser, scope: TokenScopeDep,
    project_id: int | None = None, team_id: int | None = None,
) -> list[RuleScopeRead]:
    """The scopes whose rules reach a project or team, and which the caller may add to."""
    return await scopes_for(session, user, scope, project_id=project_id, team_id=team_id)


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


@router.get("/projects/{project_id}/rule-suggestions", response_model=list[RuleSuggestionRead])
async def rule_suggestions(
    session: SessionDep, _: CurrentUser, project_id: int, weeks: int = 12
) -> list[RuleSuggestionRead]:
    """Recurring themes in people's request-changes notes and reviewers' findings that no rule
    covers yet — candidates a session can stage as a `rule` proposal for a person to accept."""
    from datetime import timedelta

    from app.models.base import ArtifactKind, utcnow
    from app.models.gate import Gate
    from app.models.project import Task
    from app.models.work import TaskArtifact
    from app.services import rule_suggestions as rs

    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    since = utcnow() - timedelta(weeks=max(1, min(weeks, 52)))
    keys = {t.id: t.key for t in (await session.execute(
        select(Task).where(Task.project_id == project_id))).scalars().all()}
    notes: list[rs.NoteRow] = []
    for gate in (await session.execute(
        select(Gate).where(
            Gate.project_id == project_id, col(Gate.decided_at) >= since,
            col(Gate.decision).in_(["request_changes", "reject"]))
    )).scalars().all():
        if gate.id is not None and gate.response_note and gate.decided_at is not None:
            notes.append(rs.NoteRow("gate", gate.id, gate.task_id, keys.get(gate.task_id),
                                    gate.response_note, gate.decided_at))
    for review in (await session.execute(
        select(TaskArtifact).where(
            col(TaskArtifact.task_id).in_(list(keys) or [-1]),
            col(TaskArtifact.kind).in_([ArtifactKind.review.value, ArtifactKind.qa_report.value]),
            col(TaskArtifact.verdict).in_(["fail", "concerns"]),
            col(TaskArtifact.created_at) >= since)
    )).scalars().all():
        for finding in (review.data or {}).get("findings") or []:
            text = str(finding.get("note") or "") if isinstance(finding, dict) else ""
            if text and review.id is not None:
                notes.append(rs.NoteRow("review", review.id, review.task_id,
                                        keys.get(review.task_id), text, review.created_at))
    existing = [(e.key, e.rule.title, e.rule.body)
                for e in await rules_service.effective_rules(session, project)]
    return [
        RuleSuggestionRead(
            key=theme.key, words=theme.words, count=len(theme.notes), tasks=theme.tasks,
            examples=[RuleSuggestionExample(source=n.source, source_id=n.source_id,
                                            task_key=n.task_key, text=n.text[:300])
                      for n in theme.notes[:5]],
        )
        for theme in rs.suggest(notes, existing)
    ]
