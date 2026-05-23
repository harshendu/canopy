from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import col, select

from app.api.deps import AdminUser, CurrentUser, SessionDep
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.schemas.auth import Token, UserCreate, UserRead, UserUpdate

router = APIRouter()


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
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@router.get("/users", response_model=list[UserRead])
async def list_users(session: SessionDep, _: AdminUser) -> list[User]:
    result = await session.execute(select(User).order_by(col(User.email)))
    return list(result.scalars().all())


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
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(user, field, value)
    await session.commit()
    await session.refresh(user)
    return user
