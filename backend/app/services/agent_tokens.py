"""Agent-token self-service (§A6): mint a bounded agent token for the current user to hand to
Claude / the MCP server, list the user's live tokens with expiry, and revoke one before it
expires. The JWT stays stateless; this only persists metadata (`AgentTokenRecord`) so the token
can be listed and revoked. `token_status` is a pure helper (unit-tested)."""

import uuid
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.core.security import create_access_token
from app.models.agent_token import AgentTokenRecord
from app.models.base import TokenScope, utcnow
from app.models.user import User
from app.schemas.auth import AgentToken, AgentTokenInfo

AGENT_TOKEN_DEFAULT_MINUTES = 7 * 24 * 60  # 7 days
AGENT_TOKEN_MAX_MINUTES = 30 * 24 * 60  # 30 days


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


async def mint_agent_token(
    session: AsyncSession, user: User, *, label: str | None, expires_minutes: int | None
) -> AgentToken:
    """Persist a token record + mint the matching JWT (carrying its `jti`). Returns the secret —
    the only time it is exposed."""
    assert user.id is not None  # set once loaded from the DB
    minutes = clamp_minutes(expires_minutes)
    jti = uuid.uuid4().hex
    expires_at = utcnow() + timedelta(minutes=minutes)
    record = AgentTokenRecord(
        user_id=user.id,
        jti=jti,
        label=_clean_label(label),
        scope=TokenScope.agent.value,
        expires_at=expires_at,
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


async def token_is_revoked(session: AsyncSession, jti: str) -> bool:
    """Whether the persisted token with this `jti` has been revoked — checked on every request that
    presents a token carrying a `jti` (i.e. agent tokens)."""
    result = await session.execute(
        select(AgentTokenRecord).where(AgentTokenRecord.jti == jti)
    )
    record = result.scalars().first()
    return record is not None and record.revoked_at is not None
