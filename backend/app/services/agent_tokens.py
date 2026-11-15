"""Agent-token self-service (§A6): mint a bounded agent token for the current user to hand to
Claude / the MCP server, list the user's live tokens with expiry, and revoke one before it
expires. The JWT stays stateless; this only persists metadata (`AgentTokenRecord`) so the token
can be listed and revoked. `token_status` is a pure helper (unit-tested)."""

import re
import uuid
from datetime import datetime, timedelta

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.core.security import create_access_token
from app.models.agent_token import AgentTokenRecord
from app.models.base import TokenScope, utcnow
from app.models.project import Project
from app.models.user import User
from app.schemas.auth import AgentToken, AgentTokenInfo, AgentTokenScope

AGENT_TOKEN_DEFAULT_MINUTES = 7 * 24 * 60  # 7 days
AGENT_TOKEN_MAX_MINUTES = 30 * 24 * 60  # 30 days
MAX_ACTIVE_CLAIMS_LIMIT = 10
LAST_USED_RESOLUTION = timedelta(minutes=1)  # `last_used_at` is written at most this often
# An agent role key: built-in implementer / reviewer / qa, or a team's own (planner, …).
ROLE_KEY_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


class AgentTokenError(ValueError):
    """A mint request that cannot be honoured (unknown project, malformed role, …)."""


def clamp_minutes(requested: int | None) -> int:
    """Requested lifetime, defaulted to 7 days and clamped to [1 minute, 30 days]."""
    return max(min(requested or AGENT_TOKEN_DEFAULT_MINUTES, AGENT_TOKEN_MAX_MINUTES), 1)


def token_status(expires_at: datetime, revoked_at: datetime | None, now: datetime) -> str:
    """Pure: the display status of a token — revoked wins over expired wins over active."""
    if revoked_at is not None:
        return "revoked"
    if expires_at <= now:
        return "expired"
    return "active"


def _clean_label(label: str | None) -> str:
    cleaned = (label or "").strip()
    return cleaned[:120] if cleaned else "Agent token"


def clean_roles(roles: list[str] | None) -> list[str]:
    """Role keys, trimmed, lower-cased and de-duplicated; a malformed key is refused."""
    out: list[str] = []
    for raw in roles or []:
        key = str(raw).strip().lower()
        if not ROLE_KEY_RE.match(key):
            raise AgentTokenError(
                f"Role {raw!r} is not a role key (lower-case letters, digits, - and _)"
            )
        if key not in out:
            out.append(key)
    if len(out) > 16:
        raise AgentTokenError("A token can be scoped to at most 16 roles")
    return out


def clamp_claims(requested: int | None) -> int:
    """Concurrent claims a token may hold: default 1, clamped to [1, 10]."""
    return max(min(requested or 1, MAX_ACTIVE_CLAIMS_LIMIT), 1)


async def _clean_project_ids(session: AsyncSession, project_ids: list[int] | None) -> list[int]:
    ids = sorted({int(p) for p in project_ids or []})
    if not ids:
        return []
    found = set(
        (await session.execute(select(Project.id).where(col(Project.id).in_(ids))))
        .scalars()
        .all()
    )
    missing = [p for p in ids if p not in found]
    if missing:
        raise AgentTokenError(f"Unknown project ids: {missing}")
    return ids


async def mint_agent_token(
    session: AsyncSession,
    user: User,
    *,
    label: str | None,
    expires_minutes: int | None,
    roles: list[str] | None = None,
    project_ids: list[int] | None = None,
    max_active_claims: int | None = None,
) -> AgentToken:
    """Persist a token record + mint the matching JWT (carrying its `jti`). Returns the secret —
    the only time it is exposed. Raises AgentTokenError on a malformed scope."""
    assert user.id is not None  # set once loaded from the DB
    minutes = clamp_minutes(expires_minutes)
    scoped_roles = clean_roles(roles)
    scoped_projects = await _clean_project_ids(session, project_ids)
    jti = uuid.uuid4().hex
    expires_at = utcnow() + timedelta(minutes=minutes)
    record = AgentTokenRecord(
        user_id=user.id,
        jti=jti,
        label=_clean_label(label),
        scope=TokenScope.agent.value,
        expires_at=expires_at,
        roles=scoped_roles,
        project_ids=scoped_projects,
        max_active_claims=clamp_claims(max_active_claims),
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    assert record.id is not None  # set after flush
    token = create_access_token(
        user.email, expires_minutes=minutes, scope=TokenScope.agent.value, jti=jti
    )
    return AgentToken(
        access_token=token,
        id=record.id,
        label=record.label,
        expires_minutes=minutes,
        expires_at=expires_at,
        roles=list(record.roles or []),
        project_ids=list(record.project_ids or []),
        max_active_claims=record.max_active_claims,
    )


async def list_agent_tokens(session: AsyncSession, user: User) -> list[AgentTokenInfo]:
    """The caller's minted tokens, newest first — metadata only (never the secret)."""
    result = await session.execute(
        select(AgentTokenRecord)
        .where(AgentTokenRecord.user_id == user.id)
        .order_by(col(AgentTokenRecord.created_at).desc())
    )
    now = utcnow()
    return [
        AgentTokenInfo(
            id=r.id,
            label=r.label,
            scope=r.scope,
            issued_at=r.created_at,
            expires_at=r.expires_at,
            revoked_at=r.revoked_at,
            status=token_status(r.expires_at, r.revoked_at, now),
            roles=list(r.roles or []),
            project_ids=list(r.project_ids or []),
            max_active_claims=r.max_active_claims,
            last_used_at=r.last_used_at,
        )
        for r in result.scalars().all()
        if r.id is not None
    ]


async def revoke_agent_token(session: AsyncSession, user: User, token_id: int) -> bool:
    """Revoke one of the caller's own tokens (idempotent). False if it isn't theirs / is missing."""
    record = await session.get(AgentTokenRecord, token_id)
    if record is None or record.user_id != user.id:
        return False
    if record.revoked_at is None:
        record.revoked_at = utcnow()
        await session.commit()
    return True


async def record_for_jti(session: AsyncSession, jti: str) -> AgentTokenRecord | None:
    return (
        await session.execute(select(AgentTokenRecord).where(AgentTokenRecord.jti == jti))
    ).scalars().first()


def scope_of(record: AgentTokenRecord) -> AgentTokenScope:
    assert record.id is not None
    return AgentTokenScope(
        id=record.id,
        label=record.label,
        roles=list(record.roles or []),
        project_ids=list(record.project_ids or []),
        max_active_claims=record.max_active_claims,
    )


async def touch_last_used(session: AsyncSession, record: AgentTokenRecord) -> None:
    """Note that the token was just used — written at most once a minute, with a conditional
    UPDATE so concurrent requests don't race, and committed at once (this runs while
    authenticating, before the request has done anything else)."""
    now = utcnow()
    if record.last_used_at is not None and now - record.last_used_at < LAST_USED_RESOLUTION:
        return
    threshold = now - LAST_USED_RESOLUTION
    await session.execute(
        update(AgentTokenRecord)
        .where(
            col(AgentTokenRecord.id) == record.id,
            col(AgentTokenRecord.last_used_at).is_(None)
            | (col(AgentTokenRecord.last_used_at) < threshold),
        )
        .values(last_used_at=now)
        .execution_options(synchronize_session=False)
    )
    await session.commit()
    record.last_used_at = now


async def token_is_revoked(session: AsyncSession, jti: str) -> bool:
    """Whether the persisted token with this `jti` has been revoked — checked on every request that
    presents a token carrying a `jti` (i.e. agent tokens)."""
    result = await session.execute(
        select(AgentTokenRecord).where(AgentTokenRecord.jti == jti)
    )
    record = result.scalars().first()
    return record is not None and record.revoked_at is not None
