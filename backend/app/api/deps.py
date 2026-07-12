from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, HTTPException, params, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.config import settings
from app.core.db import get_session
from app.core.security import decode_access_token, decode_token_actor, decode_token_scope
from app.models.base import TokenScope, UserRole
from app.models.team import Engineer
from app.models.user import User

# Roles that may write across planning/capacity/risk/architecture (admin always included).
PLANNER_ROLES = {UserRole.admin, UserRole.architect, UserRole.engineering_manager}

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_PREFIX}/auth/login")

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_current_user(
    session: SessionDep, token: Annotated[str, Depends(oauth2_scheme)]
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    email = decode_access_token(token)
    if not email:
        raise credentials_error
    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise credentials_error
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_impersonator(
    session: SessionDep, token: Annotated[str, Depends(oauth2_scheme)]
) -> User | None:
    """The real admin behind an impersonation token (its `act` claim), or ``None`` for an ordinary
    session — drives the impersonation banner and the actor-gated account switcher."""
    actor_email = decode_token_actor(token)
    if not actor_email:
        return None
    result = await session.execute(select(User).where(User.email == actor_email))
    return result.scalar_one_or_none()


Impersonator = Annotated[User | None, Depends(get_impersonator)]


async def require_admin_actor(user: CurrentUser, impersonator: Impersonator) -> User:
    """The acting admin for account-switching: the impersonator when impersonating, else the
    current user. Gating on the actor (not the impersonated user) means an admin keeps the power
    to switch — to another user or back to themselves — even while acting as a non-admin."""
    actor = impersonator or user
    if not actor.is_active or actor.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required")
    return actor


AdminActor = Annotated[User, Depends(require_admin_actor)]


async def current_token_scope(token: Annotated[str, Depends(oauth2_scheme)]) -> TokenScope:
    """The bounded-agency scope of the caller's token."""
    return TokenScope.agent if decode_token_scope(token) == TokenScope.agent else TokenScope.full


TokenScopeDep = Annotated[TokenScope, Depends(current_token_scope)]


async def require_human(scope: TokenScopeDep) -> None:
    """Gate a one-way-door / external-write action: an `agent`-scoped token is rejected (these
    actions are reserved for a human). Two-way-door actions stay open to agents."""
    if scope == TokenScope.agent:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "This is a one-way-door or external-write action reserved for a human; the "
                "agent token is bounded to reversible (two-way-door) actions."
            ),
        )


HumanOnly = Annotated[None, Depends(require_human)]


async def require_admin(user: CurrentUser) -> User:
    if user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required")
    return user


AdminUser = Annotated[User, Depends(require_admin)]


async def require_demo_mode() -> None:
    """Gate the destructive demo seed/reset actions: they only exist when ``DEMO_MODE`` is on
    (a local/dev-only flag), so they can never wipe a production database."""
    if not settings.DEMO_MODE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Demo mode is disabled (set DEMO_MODE=true to enable seed/reset).",
        )


DemoModeGuard = Annotated[None, Depends(require_demo_mode)]


def require_feature(key: str) -> Callable[[AsyncSession], Awaitable[None]]:
    """Dependency factory: reject the request (403) when the feature gate `key` is off.

    Attached per-router (see `app/api/v1/__init__.py`) or per-endpoint for sub-features that
    live inside a core router. The detail is machine-readable so clients (React, MCP) can
    distinguish "admin turned this off" from a permissions problem.
    """

    async def _dependency(session: SessionDep) -> None:
        from app.services.features import FEATURES_BY_KEY, feature_enabled

        if await feature_enabled(session, key):
            return
        feature = FEATURES_BY_KEY.get(key)
        label = feature.label if feature is not None else key
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "feature_disabled",
                "feature": key,
                "message": f"'{label}' is disabled by the administrator.",
            },
        )

    return _dependency


def FeatureGate(key: str) -> params.Depends:  # noqa: N802 - reads as a marker at call sites
    """`Depends(require_feature(key))`, for `dependencies=[...]` lists."""
    return params.Depends(dependency=require_feature(key))


def _effective_role(role: UserRole) -> UserRole:
    """Legacy `member` accounts predate the role split; treat them as `architect`."""
    return UserRole.architect if role == UserRole.member else role


def is_planner(user: User) -> bool:
    return _effective_role(user.role) in PLANNER_ROLES


def require_roles(*roles: UserRole) -> Callable[[User], Awaitable[User]]:
    """Dependency factory: require the current user to hold one of `roles` (admin always
    allowed). `member` is treated as `architect` for back-compat. Reads stay open to any
    authenticated user — only mutating endpoints depend on these."""
    allowed = set(roles) | {UserRole.admin}

    async def _dependency(user: CurrentUser) -> User:
        if _effective_role(user.role) not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of: {', '.join(sorted(r.value for r in allowed))}",
            )
        return user

    return _dependency


async def current_engineer(session: AsyncSession, user: User) -> Engineer | None:
    """The Engineer record linked to this login, if any (see Engineer.user_id)."""
    result = await session.execute(select(Engineer).where(Engineer.user_id == user.id))
    return result.scalars().first()


# Write-access role groups, named for the v2 "Roles x flows" matrix. admin is always
# allowed (folded in by require_roles).
#   ArchitectWriter   — Project settings (B2/B4): admin, architect.
#   PlannerWriter     — Plan / Capacity / Risk / ADR transitions: + engineering_manager.
#   ContributorWriter — propose/comment ADRs, edit own work: + engineer (excludes viewer).
ArchitectWriter = Annotated[User, Depends(require_roles(UserRole.architect))]
PlannerWriter = Annotated[
    User, Depends(require_roles(UserRole.architect, UserRole.engineering_manager))
]
ContributorWriter = Annotated[
    User,
    Depends(
        require_roles(
            UserRole.architect, UserRole.engineering_manager, UserRole.engineer
        )
    ),
]
