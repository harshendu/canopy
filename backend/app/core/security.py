from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.core.config import settings


def hash_password(password: str) -> str:
    # bcrypt operates on at most 72 bytes; longer inputs are truncated.
    return bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode()[:72], hashed.encode())


def create_access_token(
    subject: str,
    expires_minutes: int | None = None,
    scope: str = "full",
    actor: str | None = None,
) -> str:
    expire = datetime.now(UTC) + timedelta(
        minutes=expires_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {"sub": subject, "exp": expire, "scope": scope}
    if actor is not None:
        # RFC 8693-style delegation: an admin acts *as* `subject` while `act` records who they are.
        payload["act"] = actor
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        return payload.get("sub")
    except jwt.PyJWTError:
        return None


def decode_token_actor(token: str) -> str | None:
    """The impersonator's email (the `act` claim) when an admin minted this token to act as another
    user; ``None`` for an ordinary session. Account-switching is gated on this actor, so an admin
    keeps the power to switch even while acting as a non-admin."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        actor = payload.get("act")
        return str(actor) if actor is not None else None
    except jwt.PyJWTError:
        return None


def decode_token_scope(token: str) -> str:
    """The token's bounded-agency scope ('full' | 'agent'). Defaults to 'full' for tokens
    minted before scopes existed; an invalid token is treated as 'full' (the user dependency
    rejects it on its own)."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        return str(payload.get("scope", "full"))
    except jwt.PyJWTError:
        return "full"
