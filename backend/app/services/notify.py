"""Outbound notifications — docs/AGENT_EXECUTION.md §15 (push starts), §17 (the plan on the
ticket) and Phase 3's gate notifications.

Everything outbound goes through a **transactional outbox** (`OutboxMessage`): the change that
causes a notification queues it in its own transaction, and the worker's `deliver_outbox`
drains the outbox with retries and backoff. Nothing is sent for a change that rolled back, and
nothing is lost while the network (or Redis) is down.

What goes out:

* **Webhooks** a team configures (`OutboundWebhook`, workspace / team / project scope):
  `work.ready` when delegated work becomes ready for a role — the task key and the role and
  nothing more, so a forged or replayed call can start a session but never hand it work (the
  session still claims through MCP) — and `gate.opened` · `gate.reminder` · `gate.escalated` ·
  `gate.decided`. `json` destinations get a JSON body signed with HMAC-SHA256
  (`X-Canopy-Signature: sha256=…`) when they have a secret; `slack` destinations get an
  incoming-webhook message.
* **Email** to the people who may decide a gate, when `NOTIFY_EMAIL_GATES` and SMTP are set.
* **The approved plan as a comment** on a mirrored ticket, when the tracker supports comments
  and its writes are direct — content only, and only after a person decided in canopy.

Notifications carry canopy's own wording and a link back — never text an agent wrote, so a
turned session can't use canopy to phish the people who approve its work.
"""

from __future__ import annotations

import asyncio
import contextvars
import hashlib
import hmac
import ipaddress
import json
import logging
import smtplib
import socket
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime, timedelta
from email.message import EmailMessage
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.connectors.http import request_with_retry
from app.core.config import settings
from app.core.crypto import decrypt_token, encrypt_token
from app.models.base import RuleScope, utcnow
from app.models.gate import Gate
from app.models.notify import OutboundWebhook, OutboxMessage
from app.models.project import Project, Task
from app.models.user import User
from app.models.work import WorkEvent
from app.services.features import feature_enabled

log = logging.getLogger(__name__)

EVENTS = ("work.ready", "gate.opened", "gate.reminder", "gate.escalated", "gate.decided")
FORMATS = ("json", "slack")
WEBHOOK = "webhook"
COMMENT = "tracker_comment"
EMAIL = "email"
FEATURE = "integrations.outbound"
# Minutes before each retry; a delivery that fails them all is marked failed.
BACKOFF_MINUTES = (1, 5, 30, 120, 480)
MAX_ATTEMPTS = len(BACKOFF_MINUTES) + 1
SIGNATURE_HEADER = "X-Canopy-Signature"
# Work events that can make a task ready again (the `work.ready` dedupe stamp).
READY_KINDS = ("delegated", "claim_ended", "advanced", "returned", "gate_decided",
               "tracker_moved")

_queued: contextvars.ContextVar[bool] = contextvars.ContextVar("canopy_outbox_queued",
                                                               default=False)


class DeliveryError(Exception):
    """A delivery that failed. `retryable` ones are tried again later."""

    def __init__(self, message: str, *, retryable: bool, status: int | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status = status


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #


def sign(secret: str, body: bytes) -> str:
    """The `X-Canopy-Signature` value: `sha256=` + the hex HMAC-SHA256 of the raw body."""
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def gate_url(gate_id: int) -> str:
    return f"{settings.FRONTEND_BASE_URL.rstrip('/')}/reviews/gates/{gate_id}"


_GATE_WORDS = {
    "question": "A question", "escalation": "An escalation", "plan_approval": "A plan approval",
    "handoff_approval": "A hand-off approval", "signoff": "A sign-off",
}


def message_text(event: str, payload: dict[str, Any]) -> str:
    """One line for Slack and email subjects — canopy's wording only, never agent text."""
    task = payload.get("task_key") or f"task #{payload.get('task_id')}"
    project = payload.get("project_key") or ""
    where = f" ({project})" if project else ""
    if event == "work.ready":
        return f"{task}{where} is ready for a {payload.get('role')} session"
    what = _GATE_WORDS.get(str(payload.get("kind")), "A decision")
    url = payload.get("url") or ""
    if event == "gate.opened":
        return f"{what} on {task}{where} is waiting on a person — {url}"
    if event == "gate.reminder":
        return f"Still waiting: {what.lower()} on {task}{where} — {url}"
    if event == "gate.escalated":
        return (f"Escalated (level {payload.get('level')}): {what.lower()} on {task}{where} — "
                f"more people may decide now — {url}")
    if event == "gate.decided":
        decision = str(payload.get("decision") or "decided").replace("_", " ")
        return f"{what} on {task}{where}: {decision} — {url}"
    return f"{event}: {task}{where}"


def validate_url(url: str, *, allow_insecure: bool = False) -> str | None:
    """Why a webhook URL is refused (None = fine): https only (http when the install allows
    private destinations — a dev setting), with a host."""
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("https", "http") or not parsed.hostname:
        return "Give a full https:// URL"
    if parsed.scheme == "http" and not allow_insecure:
        return "Use https:// — plain http is allowed only with OUTBOUND_WEBHOOKS_ALLOW_PRIVATE"
    return None


def _blocked_ip(raw: str) -> bool:
    ip = ipaddress.ip_address(raw)
    return bool(ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified)


async def _resolve_ips(host: str) -> list[str]:
    infos = await asyncio.to_thread(socket.getaddrinfo, host, None)
    return sorted({str(info[4][0]) for info in infos})


async def check_destination(url: str) -> None:
    """Refuse destinations inside the network (SSRF): a planner may configure a project's
    webhook, so its host must resolve to public addresses only — checked at every delivery, so
    a DNS change can't slip one in later."""
    allow = settings.OUTBOUND_WEBHOOKS_ALLOW_PRIVATE
    reason = validate_url(url, allow_insecure=allow)
    if reason:
        raise DeliveryError(reason, retryable=False)
    if allow:
        return
    host = urlparse(url).hostname or ""
    try:
        addresses = await _resolve_ips(host)
    except OSError as exc:
        raise DeliveryError(f"Couldn't resolve {host}", retryable=True) from exc
    if not addresses or any(_blocked_ip(a) for a in addresses):
        raise DeliveryError(f"{host} resolves to a private address", retryable=False)


# --------------------------------------------------------------------------- #
# Queueing (inside the caller's transaction)
# --------------------------------------------------------------------------- #


async def queue(
    session: AsyncSession,
    *,
    channel: str,
    event: str,
    payload: dict[str, Any],
    webhook_id: int | None = None,
    connection_id: int | None = None,
    project_id: int | None = None,
    task_id: int | None = None,
    recipient: str | None = None,
    dedupe_key: str | None = None,
) -> OutboxMessage | None:
    """Queue one delivery (None when `dedupe_key` was queued before). Does not commit."""
    if dedupe_key is not None:
        key = dedupe_key[:255]
        seen = (await session.execute(
            select(OutboxMessage.id).where(OutboxMessage.dedupe_key == key).limit(1)
        )).first()
        if seen is not None:
            return None
        dedupe_key = key
    row = OutboxMessage(
        channel=channel, event=event, payload=payload, webhook_id=webhook_id,
        connection_id=connection_id, project_id=project_id, task_id=task_id,
        recipient=recipient, dedupe_key=dedupe_key, next_attempt_at=utcnow(),
    )
    session.add(row)
    _queued.set(True)
    return row


async def hooks_for(session: AsyncSession, project: Project, event: str) -> list[OutboundWebhook]:
    """The enabled webhooks that hear `event` for this project: the workspace's, its team's,
    its own."""
    from app.services.org import project_team_id

    team_id = await project_team_id(session, project)
    rows = (await session.execute(
        select(OutboundWebhook).where(col(OutboundWebhook.enabled).is_(True))
    )).scalars().all()
    out: list[OutboundWebhook] = []
    for hook in rows:
        level, scope_id = hook.scope_level, hook.scope_id
        if not (
            level == RuleScope.workspace.value
            or (level == RuleScope.team.value and team_id is not None and scope_id == team_id)
            or (level == RuleScope.project.value and scope_id == project.id)
        ):
            continue
        if event in (hook.events or []):
            out.append(hook)
    return out


def email_enabled() -> bool:
    return bool(settings.NOTIFY_EMAIL_GATES and settings.SMTP_HOST)


async def deciders(session: AsyncSession, gate: Gate) -> list[User]:
    """The active people with an email address who may decide this gate (not its requester
    when separation of duties applies)."""
    from app.services import gates

    out: list[User] = []
    for user in (await session.execute(
        select(User).where(col(User.is_active).is_(True))
    )).scalars().all():
        if not user.email or (gate.exclude_requester and user.id == gate.requested_by_user_id):
            continue
        ok, _ = await gates.may_decide(session, gate, user)
        if ok:
            out.append(user)
    return out


async def gate_event(session: AsyncSession, gate: Gate, event: str) -> int:
    """Queue a gate notification: to the webhooks that hear it, and (opened, reminders,
    escalations) by email to whoever may decide. Returns how many were queued."""
    if gate.id is None or not await feature_enabled(session, FEATURE):
        return 0
    project = await session.get(Project, gate.project_id)
    task = await session.get(Task, gate.task_id)
    if project is None or task is None:
        return 0
    payload: dict[str, Any] = {
        "event": event, "gate_id": gate.id, "kind": gate.kind, "status": gate.status,
        "task_id": task.id, "task_key": task.key, "project_id": project.id,
        "project_key": project.key, "url": gate_url(gate.id),
    }
    if event == "gate.decided":
        payload["decision"] = gate.decision
    if event == "gate.escalated":
        payload["level"] = gate.escalation_level
    stamp = f"{gate.id}:{gate.escalation_level}" if event == "gate.escalated" else str(gate.id)
    count = 0
    for hook in await hooks_for(session, project, event):
        if await queue(session, channel=WEBHOOK, event=event, payload=payload,
                       webhook_id=hook.id, project_id=project.id, task_id=task.id,
                       dedupe_key=f"{event}:{stamp}:hook:{hook.id}"):
            count += 1
    if email_enabled() and event in ("gate.opened", "gate.reminder", "gate.escalated"):
        for user in await deciders(session, gate):
            if await queue(session, channel=EMAIL, event=event, payload=payload,
                           project_id=project.id, task_id=task.id, recipient=user.email,
                           dedupe_key=f"{event}:{stamp}:mail:{user.id}"):
                count += 1
    return count


async def queue_ready(
    session: AsyncSession, project: Project, task_ids: Sequence[int] | None = None,
    now: datetime | None = None,
) -> int:
    """Announce `work.ready` for delegated tasks that are ready for a role now — once per
    readiness (a task ready again after rework or a person's answer is announced again).
    Cheap when nothing listens: no webhook, no readiness computed."""
    if project.id is None or not await feature_enabled(session, FEATURE):
        return 0
    hooks = await hooks_for(session, project, "work.ready")
    if not hooks:
        return 0
    from app.services.agent_flow_service import ready_work

    await session.flush()
    rows = [r for r in await ready_work(session, [project.id], now=now)
            if task_ids is None or r.task_id in set(task_ids)]
    if not rows:
        return 0
    ids = sorted({r.task_id for r in rows})
    # A readiness is identified by the last event that could have made the task ready (a
    # delegation, a claim ending, a move, a decision) — a note or a component change isn't one.
    last: dict[int, int] = {
        int(task_id): int(event_id or 0) for task_id, event_id in (await session.execute(
            select(WorkEvent.task_id, func.max(WorkEvent.id))
            .where(col(WorkEvent.task_id).in_(ids), col(WorkEvent.kind).in_(READY_KINDS))
            .group_by(col(WorkEvent.task_id))
        )).all() if task_id is not None
    }
    tasks = {t.id: t for t in (await session.execute(
        select(Task).where(col(Task.id).in_(ids)))).scalars().all()}
    count = 0
    for row in rows:
        task = tasks.get(row.task_id)
        if task is None:
            continue
        payload = {"event": "work.ready", "task_id": task.id, "task_key": task.key,
                   "role": row.role, "project_id": project.id, "project_key": project.key}
        stamp = f"{task.id}:{row.role}:{(task.status or '').casefold()}:{last.get(row.task_id, 0)}"
        for hook in hooks:
            if await queue(session, channel=WEBHOOK, event="work.ready", payload=payload,
                           webhook_id=hook.id, project_id=project.id, task_id=task.id,
                           dedupe_key=f"work.ready:{stamp}:hook:{hook.id}"):
                count += 1
    return count


async def queue_ready_for_task(session: AsyncSession, task: Task) -> int:
    project = await session.get(Project, task.project_id)
    if project is None or task.id is None:
        return 0
    return await queue_ready(session, project, [task.id])


async def queue_plan_comment(
    session: AsyncSession, gate: Gate, task: Task, *, approver: User | None
) -> dict[str, Any] | None:
    """A person approved a plan in canopy on a mirrored ticket (§17): post the plan to the
    ticket as a comment when its tracker supports comments and writes go direct. When the
    install routes tracker writes through Claude (`write_strategy=mcp`), canopy doesn't post —
    it returns `{key, body}` for the session to post with its own tools. None otherwise."""
    from app.connectors.tracker import tracker_class
    from app.models.base import WriteStrategy
    from app.models.integration import Connection, ExternalRef
    from app.services import integration_policy
    from app.services.tracker_sync import binding_for_project
    from app.services.work_service import latest_artifact

    if task.id is None or gate.subject_artifact_id is None:
        return None
    binding = await binding_for_project(session, task.project_id)
    if binding is None:
        return None
    cls = tracker_class(binding.provider)
    if cls is None or not cls.capabilities.comments:
        return None
    from app.models.base import ArtifactKind
    from app.models.work import TaskArtifact

    plan = await session.get(TaskArtifact, gate.subject_artifact_id)
    if plan is None or plan.kind != ArtifactKind.plan.value:
        plan = await latest_artifact(session, task.id, ArtifactKind.plan)
    if plan is None:
        return None
    who = (approver.full_name or approver.email) if approver is not None else "a person"
    steps = [str(s.get("content")) for s in (plan.data or {}).get("steps") or []
             if isinstance(s, dict) and s.get("content")]
    body = (f"canopy: plan approved by {who} (revision {plan.revision}).\n\n"
            f"{(plan.body or '').strip()[:6000]}")
    if steps:
        body += "\n\nSteps:\n" + "\n".join(f"- {s[:300]}" for s in steps[:20])
    setting = await integration_policy.get_setting(session, binding.provider)
    if setting.write_strategy == WriteStrategy.mcp:
        return {"key": task.key, "provider": binding.provider.value, "body": body}
    if setting.write_strategy == WriteStrategy.disabled:
        return None
    connection = await session.get(Connection, binding.connection_id)
    if connection is None:
        return None
    ref = (await session.execute(
        select(ExternalRef).where(
            ExternalRef.entity_type == "task", ExternalRef.entity_id == task.id,
            col(ExternalRef.detached_at).is_(None),
        ).order_by(col(ExternalRef.id).desc())
    )).scalars().first()
    if ref is None:
        return None
    await queue(session, channel=COMMENT, event="plan.approved",
                payload={"external_id": ref.external_id, "key": task.key, "body": body,
                         "scope": binding.scope.values, "mapping": binding.scope.mapping,
                         "scope_kind": binding.scope.kind,
                         "user_id": approver.id if approver is not None else None},
                connection_id=connection.id, project_id=task.project_id, task_id=task.id,
                dedupe_key=f"plan.approved:{gate.id}")
    return None


async def sweep(session: AsyncSession, now: datetime | None = None) -> int:
    """The periodic pass (the reaper's): reminders for gates past their reminder, and
    `work.ready` for work that became ready without a canopy action (a dependency finished, a
    blocker cleared). Commits."""
    from app.models.base import AgentIntake, GateStatus

    now = now or utcnow()
    if not await feature_enabled(session, FEATURE):
        return 0
    count = 0
    for gate in (await session.execute(
        select(Gate).where(Gate.status == GateStatus.open.value,
                           col(Gate.remind_at).is_not(None), col(Gate.remind_at) <= now)
    )).scalars().all():
        count += await gate_event(session, gate, "gate.reminder")
    for project in (await session.execute(
        select(Project).where(Project.agent_intake == AgentIntake.on.value)
    )).scalars().all():
        count += await queue_ready(session, project, now=now)
    await session.commit()
    return count


async def kick() -> None:
    """After a commit that queued deliveries, wake the worker's drain — when there is a worker
    (Redis). Never fails the caller: the worker's minute cron drains whatever is pending."""
    if not _queued.get():
        return
    _queued.set(False)
    if settings.EVENTS_BACKEND != "redis":
        return
    try:
        from app.workers.queue import enqueue

        await asyncio.wait_for(enqueue("deliver_outbox"), timeout=2)
    except Exception:  # best effort: the worker's cron drains it anyway
        log.debug("couldn't kick the outbox drain", exc_info=True)


# --------------------------------------------------------------------------- #
# Webhook CRUD helpers
# --------------------------------------------------------------------------- #


def set_secret(hook: OutboundWebhook, secret: str | None) -> None:
    hook.secret_encrypted = encrypt_token(secret) if secret else None


def secret_of(hook: OutboundWebhook) -> str | None:
    return decrypt_token(hook.secret_encrypted) if hook.secret_encrypted else None


# --------------------------------------------------------------------------- #
# Delivery (the worker)
# --------------------------------------------------------------------------- #


async def _post(client: httpx.AsyncClient, url: str, body: bytes,
                headers: dict[str, str]) -> int:
    try:
        response = await request_with_retry(client, "POST", url, content=body, headers=headers,
                                            max_retries=0, timeout=10.0)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        raise DeliveryError(f"{status} from the destination", status=status,
                            retryable=status == 429 or status >= 500) from exc
    except httpx.HTTPError as exc:
        raise DeliveryError(f"{type(exc).__name__}: couldn't reach the destination",
                            retryable=True) from exc
    return response.status_code


async def _deliver_webhook(session: AsyncSession, row: OutboxMessage,
                           client: httpx.AsyncClient) -> int:
    hook = await session.get(OutboundWebhook, row.webhook_id) if row.webhook_id else None
    if hook is None or not hook.enabled:
        raise DeliveryError("The webhook was removed or switched off", retryable=False)
    await check_destination(hook.url)
    payload = {**row.payload, "delivery_id": row.id,
               "sent_at": utcnow().isoformat(timespec="seconds") + "Z"}
    headers = {"Content-Type": "application/json", "User-Agent": "canopy-webhooks/1",
               "X-Canopy-Event": row.event, "X-Canopy-Delivery": str(row.id)}
    if hook.format == "slack":
        body = json.dumps({"text": message_text(row.event, row.payload)}).encode()
    else:
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        secret = secret_of(hook)
        if secret:
            headers[SIGNATURE_HEADER] = sign(secret, body)
    try:
        status = await _post(client, hook.url, body, headers)
    except DeliveryError as exc:
        hook.consecutive_failures += 1
        hook.last_status = str(exc)[:200]
        hook.last_delivery_at = utcnow()
        raise
    hook.consecutive_failures = 0
    hook.last_status = str(status)
    hook.last_delivery_at = utcnow()
    return status


async def _deliver_comment(session: AsyncSession, row: OutboxMessage) -> None:
    from app.connectors import get_connector
    from app.connectors.tracker import WorkTracker
    from app.models.integration import Connection
    from app.services import integration_policy
    from app.services.tracker_types import ItemRef, Scope

    connection = await session.get(Connection, row.connection_id) if row.connection_id else None
    if connection is None:
        raise DeliveryError("The tracker connection is gone", retryable=False)
    data = row.payload
    user_id = data.get("user_id")
    credential, reason = await integration_policy.resolve_write_credential(
        session, connection, int(user_id) if user_id is not None else None)
    if credential is None:
        raise DeliveryError(reason, retryable=False)
    tracker = get_connector(credential, session)
    if not isinstance(tracker, WorkTracker) or not tracker.capabilities.comments:
        raise DeliveryError("The tracker doesn't take comments", retryable=False)
    scope = Scope(kind=str(data.get("scope_kind") or "project"),
                  values=dict(data.get("scope") or {}), mapping=dict(data.get("mapping") or {}))
    try:
        await tracker.add_comment(scope, ItemRef(external_id=str(data["external_id"]),
                                                 key=data.get("key")), str(data["body"]))
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        raise DeliveryError(f"{status} from the tracker", status=status,
                            retryable=status == 429 or status >= 500) from exc
    except httpx.HTTPError as exc:
        raise DeliveryError("Couldn't reach the tracker", retryable=True) from exc


def _send_email(recipient: str, subject: str, text: str) -> None:
    message = EmailMessage()
    message["From"] = settings.SMTP_FROM
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(text)
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as smtp:
        if settings.SMTP_STARTTLS:
            smtp.starttls()
        if settings.SMTP_USERNAME:
            smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        smtp.send_message(message)


async def _deliver_email(row: OutboxMessage) -> None:
    if not settings.SMTP_HOST or not row.recipient:
        raise DeliveryError("Email isn't configured (SMTP_HOST)", retryable=False)
    line = message_text(row.event, row.payload)
    text = (f"{line}\n\nOpen it in canopy to decide: {row.payload.get('url', '')}\n\n"
            "You get this because you may decide it. Nothing is approved by a timeout.")
    try:
        await asyncio.to_thread(_send_email, row.recipient, f"[canopy] {line.split(' — ')[0]}",
                                text)
    except (smtplib.SMTPException, OSError) as exc:
        raise DeliveryError(f"SMTP: {type(exc).__name__}", retryable=True) from exc


async def deliver_due(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    client: httpx.AsyncClient | None = None,
    limit: int = 100,
    send_email: Callable[[OutboxMessage], Awaitable[None]] | None = None,
    ids: Sequence[int] | None = None,
) -> dict[str, int]:
    """Send what is due, oldest first. A failure is retried after 1, 5, 30, 120 and 480
    minutes, then marked failed; a permanent one (a 4xx, a removed webhook, a private address)
    fails at once. Commits."""
    now = now or utcnow()
    stmt = select(OutboxMessage).where(OutboxMessage.status == "pending",
                                       col(OutboxMessage.next_attempt_at) <= now)
    if ids is not None:
        stmt = stmt.where(col(OutboxMessage.id).in_(list(ids)))
    rows = (await session.execute(stmt.order_by(col(OutboxMessage.id)).limit(limit))
            ).scalars().all()
    counts = {"sent": 0, "retrying": 0, "failed": 0}
    if not rows:
        return counts
    own = client is None
    http = client or httpx.AsyncClient(follow_redirects=False)
    try:
        for row in rows:
            row.attempts += 1
            try:
                if row.channel == WEBHOOK:
                    row.response_status = await _deliver_webhook(session, row, http)
                elif row.channel == COMMENT:
                    await _deliver_comment(session, row)
                elif row.channel == EMAIL:
                    await (send_email or _deliver_email)(row)
                else:
                    raise DeliveryError(f"Unknown channel {row.channel}", retryable=False)
            except DeliveryError as exc:
                row.last_error = str(exc)[:2000]
                row.response_status = exc.status
                if exc.retryable and row.attempts < MAX_ATTEMPTS:
                    row.next_attempt_at = now + timedelta(
                        minutes=BACKOFF_MINUTES[min(row.attempts, len(BACKOFF_MINUTES)) - 1])
                    counts["retrying"] += 1
                else:
                    row.status = "failed"
                    counts["failed"] += 1
                continue
            except Exception as exc:  # one bad row never stops the drain
                log.exception("outbox delivery %s crashed", row.id)
                row.last_error = f"{type(exc).__name__}: {exc}"[:2000]
                row.status = "failed" if row.attempts >= MAX_ATTEMPTS else "pending"
                row.next_attempt_at = now + timedelta(minutes=BACKOFF_MINUTES[-1])
                counts["failed" if row.status == "failed" else "retrying"] += 1
                continue
            row.status = "sent"
            row.sent_at = now
            row.last_error = None
            counts["sent"] += 1
    finally:
        if own:
            await http.aclose()
    await session.commit()
    return counts
