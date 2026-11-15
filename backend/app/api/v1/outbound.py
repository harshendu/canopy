"""Outbound webhooks — push starts for runners and gate notifications for people
(docs/AGENT_EXECUTION.md §15, Phase 3; USER_FLOWS §AE9; feature gate `integrations.outbound`).

A webhook lives at a scope like a rule: the workspace's (admins), a team's (its directors and
managers), a project's (planners who may edit it). Writes are human-only. A destination's full
URL and secret are shown only to people who may edit it — a Slack incoming-webhook URL is a
credential. Deliveries go through the outbox (`app/services/notify.py`).
"""

from __future__ import annotations

from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.api.deps import ContributorWriter, CurrentUser, HumanOnly, SessionDep, TokenScopeDep
from app.api.v1.rules import may_edit, scopes_for
from app.core.config import settings
from app.models.base import RuleScope, TokenScope, utcnow
from app.models.notify import OutboundWebhook, OutboxMessage
from app.models.org import Team
from app.models.project import Project
from app.models.user import User
from app.schemas.notify import (
    DeliveryRead,
    TestDeliveryRead,
    WebhookCatalog,
    WebhookCreate,
    WebhookRead,
    WebhookUpdate,
)
from app.schemas.policy import RuleScopeRead
from app.services import notify
from app.services.org import project_team_id

router = APIRouter()


def _masked(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.hostname or ''}/…"


async def _scope_name(session: AsyncSession, level: str, scope_id: int) -> str | None:
    if level == RuleScope.team.value:
        team = await session.get(Team, scope_id)
        return team.name if team is not None else None
    if level == RuleScope.project.value:
        project = await session.get(Project, scope_id)
        return project.name if project is not None else None
    return "Workspace"


async def _read(
    session: AsyncSession, hook: OutboundWebhook, user: User, scope: TokenScope
) -> WebhookRead:
    assert hook.id is not None
    editable = scope != TokenScope.agent and await may_edit(
        session, user, hook.scope_level, hook.scope_id)
    return WebhookRead(
        id=hook.id, scope_level=hook.scope_level, scope_id=hook.scope_id,
        scope_name=await _scope_name(session, hook.scope_level, hook.scope_id),
        name=hook.name, url=hook.url if editable else _masked(hook.url), format=hook.format,
        events=list(hook.events or []), has_secret=bool(hook.secret_encrypted),
        enabled=hook.enabled, last_delivery_at=hook.last_delivery_at,
        last_status=hook.last_status, consecutive_failures=hook.consecutive_failures,
        can_edit=editable, created_at=hook.created_at,
    )


async def _ensure_may_edit(session: AsyncSession, user: User, level: str, scope_id: int) -> None:
    if not await may_edit(session, user, level, scope_id):
        raise HTTPException(status_code=403, detail={
            "code": "not_permitted",
            "message": {
                RuleScope.workspace.value: "Only an admin manages the workspace's webhooks",
                RuleScope.team.value: "Only the team's directors and managers manage its webhooks",
            }.get(level, "Only planners who may edit the project manage its webhooks"),
        })


async def _ensure_scope(session: AsyncSession, level: str, scope_id: int) -> None:
    if level == RuleScope.workspace.value:
        if scope_id != 0:
            raise HTTPException(status_code=422, detail={
                "code": "bad_scope", "message": "The workspace's webhooks use scope_id 0"})
        return
    model = Team if level == RuleScope.team.value else Project
    if await session.get(model, scope_id) is None:
        raise HTTPException(status_code=404, detail=f"{level.title()} not found")


def _ensure_url(url: str) -> str:
    clean = url.strip()
    reason = notify.validate_url(clean, allow_insecure=settings.OUTBOUND_WEBHOOKS_ALLOW_PRIVATE)
    if reason:
        raise HTTPException(status_code=422, detail={"code": "bad_url", "message": reason})
    return clean


async def _hook(session: AsyncSession, hook_id: int) -> OutboundWebhook:
    hook = await session.get(OutboundWebhook, hook_id)
    if hook is None:
        raise HTTPException(status_code=404, detail="Webhook not found")
    return hook


@router.get("/outbound-webhooks/catalog", response_model=WebhookCatalog)
async def catalog(_: CurrentUser) -> WebhookCatalog:
    """What a webhook can hear, the formats, and whether email notifications are on."""
    return WebhookCatalog(events=list(notify.EVENTS), formats=list(notify.FORMATS),
                          email_enabled=notify.email_enabled(),
                          signature_header=notify.SIGNATURE_HEADER)


@router.get("/outbound-webhooks/scopes", response_model=list[RuleScopeRead])
async def webhook_scopes(
    session: SessionDep, user: CurrentUser, scope: TokenScopeDep,
    project_id: int | None = None, team_id: int | None = None,
) -> list[RuleScopeRead]:
    """The scopes whose webhooks reach a project or team, and which the caller may add to."""
    return await scopes_for(session, user, scope, project_id=project_id, team_id=team_id)


@router.get("/outbound-webhooks", response_model=list[WebhookRead])
async def list_webhooks(
    session: SessionDep, user: CurrentUser, scope: TokenScopeDep,
    project_id: int | None = None, team_id: int | None = None,
) -> list[WebhookRead]:
    """The webhooks that reach a project (the workspace's, its team's, its own) or a team (the
    workspace's and its own); with neither, the workspace's."""
    if project_id is not None:
        project = await session.get(Project, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        team_id = await project_team_id(session, project)
    wanted: set[tuple[str, int]] = {(RuleScope.workspace.value, 0)}
    if team_id is not None:
        wanted.add((RuleScope.team.value, team_id))
    if project_id is not None:
        wanted.add((RuleScope.project.value, project_id))
    rows = (await session.execute(
        select(OutboundWebhook).order_by(col(OutboundWebhook.id))
    )).scalars().all()
    return [await _read(session, h, user, scope) for h in rows
            if (h.scope_level, h.scope_id) in wanted]


@router.post("/outbound-webhooks", response_model=WebhookRead,
             status_code=status.HTTP_201_CREATED)
async def create_webhook(
    session: SessionDep, user: ContributorWriter, _human: HumanOnly, scope: TokenScopeDep,
    payload: WebhookCreate,
) -> WebhookRead:
    await _ensure_scope(session, payload.scope_level, payload.scope_id)
    await _ensure_may_edit(session, user, payload.scope_level, payload.scope_id)
    hook = OutboundWebhook(
        scope_level=payload.scope_level, scope_id=payload.scope_id, name=payload.name.strip(),
        url=_ensure_url(payload.url), format=payload.format,
        events=sorted(set(payload.events)), enabled=payload.enabled,
        created_by_user_id=user.id,
    )
    notify.set_secret(hook, (payload.secret or "").strip() or None)
    session.add(hook)
    await session.commit()
    await session.refresh(hook)
    return await _read(session, hook, user, scope)


@router.patch("/outbound-webhooks/{hook_id}", response_model=WebhookRead)
async def update_webhook(
    session: SessionDep, user: ContributorWriter, _human: HumanOnly, scope: TokenScopeDep,
    hook_id: int, payload: WebhookUpdate,
) -> WebhookRead:
    hook = await _hook(session, hook_id)
    await _ensure_may_edit(session, user, hook.scope_level, hook.scope_id)
    data = payload.model_dump(exclude_unset=True)
    if data.get("name") is not None:
        hook.name = str(data["name"]).strip()
    if data.get("url") is not None:
        hook.url = _ensure_url(str(data["url"]))
    if data.get("format") is not None:
        hook.format = str(data["format"])
    if data.get("events") is not None:
        hook.events = sorted(set(data["events"]))
    if "secret" in data:
        notify.set_secret(hook, (data["secret"] or "").strip() or None)
    if data.get("enabled") is not None:
        hook.enabled = bool(data["enabled"])
        if hook.enabled:
            hook.consecutive_failures = 0
    hook.updated_at = utcnow()
    await session.commit()
    await session.refresh(hook)
    return await _read(session, hook, user, scope)


@router.delete("/outbound-webhooks/{hook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook(
    session: SessionDep, user: ContributorWriter, _human: HumanOnly, hook_id: int
) -> None:
    hook = await _hook(session, hook_id)
    await _ensure_may_edit(session, user, hook.scope_level, hook.scope_id)
    for row in (await session.execute(
        select(OutboxMessage).where(OutboxMessage.webhook_id == hook_id,
                                    OutboxMessage.status == "pending")
    )).scalars().all():
        row.status = "failed"
        row.last_error = "The webhook was deleted"
    await session.delete(hook)
    await session.commit()


@router.get("/outbound-webhooks/{hook_id}/deliveries", response_model=list[DeliveryRead])
async def deliveries(
    session: SessionDep, user: CurrentUser, hook_id: int, limit: int = 20
) -> list[OutboxMessage]:
    """The latest deliveries to a webhook (people who may edit it)."""
    hook = await _hook(session, hook_id)
    await _ensure_may_edit(session, user, hook.scope_level, hook.scope_id)
    return list((await session.execute(
        select(OutboxMessage).where(OutboxMessage.webhook_id == hook_id)
        .order_by(col(OutboxMessage.id).desc()).limit(max(1, min(limit, 100)))
    )).scalars().all())


@router.post("/outbound-webhooks/{hook_id}/test", response_model=TestDeliveryRead)
async def test_webhook(
    session: SessionDep, user: ContributorWriter, _human: HumanOnly, hook_id: int
) -> TestDeliveryRead:
    """Send a `ping` now and say how it went (human-only, people who may edit the hook)."""
    hook = await _hook(session, hook_id)
    await _ensure_may_edit(session, user, hook.scope_level, hook.scope_id)
    row = await notify.queue(
        session, channel=notify.WEBHOOK, event="ping", webhook_id=hook.id,
        payload={"event": "ping", "webhook_id": hook.id, "message": "canopy test delivery"},
    )
    assert row is not None
    await session.flush()
    assert row.id is not None
    await notify.deliver_due(session, ids=[row.id])
    await session.refresh(row)
    if row.status == "pending":  # a test isn't retried later
        row.status = "failed"
        await session.commit()
    return TestDeliveryRead(delivered=row.status == "sent", status=row.status,
                            response_status=row.response_status, error=row.last_error)
