from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.config import settings
from app.core.db import get_session
from app.core.security import decode_access_token
from app.models.base import UserRole
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


async def require_admin(user: CurrentUser) -> User:
    if user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required")
    return user


AdminUser = Annotated[User, Depends(require_admin)]


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
