from pydantic import BaseModel, ConfigDict, EmailStr

from app.models.base import UserFunction, UserRole


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class AgentTokenRequest(BaseModel):
    expires_minutes: int | None = None  # default 7 days, capped at 30


class AgentToken(BaseModel):
    access_token: str
    token_type: str = "bearer"
    scope: str = "agent"
    expires_minutes: int


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: str | None = None
    role: UserRole = UserRole.member
    function: UserFunction = UserFunction.engineering


class UserUpdate(BaseModel):
    full_name: str | None = None
    role: UserRole | None = None
    function: UserFunction | None = None
    is_active: bool | None = None


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: EmailStr
    full_name: str | None = None
    role: UserRole
    function: UserFunction = UserFunction.engineering
    is_active: bool


class SessionInfo(BaseModel):
    """The active session: the effective (possibly impersonated) user, plus the real admin behind
    it when an admin is impersonating someone else (``None`` for an ordinary session)."""

    user: UserRead
    impersonator: UserRead | None = None
