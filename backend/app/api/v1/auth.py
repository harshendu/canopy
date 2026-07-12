from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import col, select

from app.api.deps import (
    AdminActor,
    AdminUser,
    CurrentUser,
    FeatureGate,
    HumanOnly,
    Impersonator,
    PlannerWriter,
    SessionDep,
    TokenScopeDep,
)
from app.core.security import create_access_token, hash_password, verify_password
from app.models.base import TokenScope, UserRole
from app.models.user import User
from app.schemas.auth import (
    AgentToken,
    AgentTokenRequest,
    PasswordChange,
    PasswordReset,
    SessionInfo,
    Token,
    UserCreate,
    UserRead,
    UserUpdate,
)

router = APIRouter()

_AGENT_TOKEN_DEFAULT_MINUTES = 7 * 24 * 60  # 7 days
_AGENT_TOKEN_MAX_MINUTES = 30 * 24 * 60  # 30 days


@router.post("/login", response_model=Token)
async def login(
    session: SessionDep, form: Annotated[OAuth2PasswordRequestForm, Depends()]
) -> Token:
    result = await session.execute(select(User).where(User.email == form.username))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(form.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password"
        )
    return Token(access_token=create_access_token(user.email))


@router.get("/me", response_model=UserRead)
async def me(user: CurrentUser) -> User:
    return user


@router.get("/session", response_model=SessionInfo)
async def session_info(
    user: CurrentUser, impersonator: Impersonator, scope: TokenScopeDep
) -> SessionInfo:
    """The effective user, plus the real admin when an admin is impersonating someone — drives the
    account switcher and the impersonation banner. Also reports the token's bounded-agency `scope`
    (§A6) so an agent session can see its own limits (proposals: stage yes, apply no)."""
    return SessionInfo(
        user=UserRead.model_validate(user),
        impersonator=UserRead.model_validate(impersonator) if impersonator is not None else None,
        scope=scope.value,
    )


@router.post("/impersonate/stop", response_model=Token)
async def stop_impersonating(actor: AdminActor, _: HumanOnly) -> Token:
    """Drop impersonation and return to the acting admin's own account."""
    return Token(access_token=create_access_token(actor.email))


@router.post("/impersonate/{user_id}", response_model=Token)
async def impersonate(
    session: SessionDep, actor: AdminActor, user_id: int, _: HumanOnly
) -> Token:
    """Admin-only: mint a token that acts **as** `user_id`. The acting admin rides along in the
    token's `act` claim, so they keep the power to switch again — to another user or back to
    themselves (selecting their own account drops impersonation). Status is never touched; this is
    a session-identity switch, not a data write."""
    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if not target.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot switch to a deactivated user"
        )
    if target.id == actor.id:
        return Token(access_token=create_access_token(actor.email))
    return Token(access_token=create_access_token(target.email, actor=actor.email))


@router.post(
    "/agent-token", response_model=AgentToken, dependencies=[FeatureGate("ai.agent_tokens")]
)
async def issue_agent_token(user: PlannerWriter, payload: AgentTokenRequest) -> AgentToken:
    """Mint a bounded **agent** token for the current planner to hand to Claude. It acts as the
    issuer but is restricted from one-way-door / external-write actions (accepting a one-way-door
    decision, pushing to Jira, applying a scenario) — those stay human-gated. Two-way-door actions
    run freely. Default 7-day expiry (max 30)."""
    minutes = min(payload.expires_minutes or _AGENT_TOKEN_DEFAULT_MINUTES, _AGENT_TOKEN_MAX_MINUTES)
    minutes = max(minutes, 1)
    token = create_access_token(user.email, expires_minutes=minutes, scope=TokenScope.agent.value)
    return AgentToken(access_token=token, expires_minutes=minutes)


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register(session: SessionDep, _: AdminUser, payload: UserCreate) -> User:
    existing = await session.execute(select(User).where(User.email == payload.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        role=payload.role,
        function=payload.function,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@router.get("/users", response_model=list[UserRead])
async def list_users(session: SessionDep, _: AdminActor) -> list[User]:
    # Actor-gated (not impersonated-user-gated) so the account switcher can list targets even
    # while the admin acts as a non-admin. Writes below stay on the impersonated identity.
    result = await session.execute(select(User).order_by(col(User.email)))
    return list(result.scalars().all())


async def _other_active_admins_exist(session: SessionDep, user: User) -> bool:
    result = await session.execute(
        select(User).where(
            User.role == UserRole.admin,
            col(User.is_active).is_(True),
            col(User.id) != user.id,
        )
    )
    return result.scalars().first() is not None


@router.patch("/users/{user_id}", response_model=UserRead)
async def update_user(
    session: SessionDep, admin: AdminUser, user_id: int, payload: UserUpdate
) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.id == admin.id and payload.is_active is False:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="You can't deactivate yourself"
        )
    changes = payload.model_dump(exclude_unset=True)
    # Lockout guard: never leave the install with zero active admins.
    loses_admin = user.role == UserRole.admin and user.is_active and (
        changes.get("role", user.role) != UserRole.admin
        or changes.get("is_active", user.is_active) is False
    )
    if loses_admin and not await _other_active_admins_exist(session, user):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This is the last active admin; promote another admin first",
        )
    for field, value in changes.items():
        setattr(user, field, value)
    await session.commit()
    await session.refresh(user)
    return user


@router.post("/users/{user_id}/password", response_model=UserRead)
async def reset_password(
    session: SessionDep, _: AdminUser, __: HumanOnly, user_id: int, payload: PasswordReset
) -> User:
    """Admin sets a new (temporary) password for a user — the recovery path when someone is
    locked out. Human-only: an agent token must not be able to rotate credentials."""
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    user.hashed_password = hash_password(payload.new_password)
    await session.commit()
    await session.refresh(user)
    return user


@router.post("/me/password", response_model=UserRead)
async def change_password(
    session: SessionDep, user: CurrentUser, _: HumanOnly, payload: PasswordChange
) -> User:
    """A signed-in user rotates their own password (e.g. after an admin-issued temporary one)."""
    if not verify_password(payload.current_password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect"
        )
    user.hashed_password = hash_password(payload.new_password)
    await session.commit()
    await session.refresh(user)
    return user
