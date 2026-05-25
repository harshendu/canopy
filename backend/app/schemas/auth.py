from pydantic import BaseModel, ConfigDict, EmailStr

from app.models.base import UserRole


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


class UserUpdate(BaseModel):
    full_name: str | None = None
    role: UserRole | None = None
    is_active: bool | None = None


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: EmailStr
    full_name: str | None = None
    role: UserRole
    is_active: bool
