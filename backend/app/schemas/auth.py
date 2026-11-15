from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.base import DocSnapshotStore, UserFunction, UserRole

MIN_PASSWORD_LENGTH = 8


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class AgentTokenRequest(BaseModel):
    label: str | None = None  # human-friendly name shown in the token list
    expires_minutes: int | None = None  # default 7 days, capped at 30
    # Narrowing for agent work (docs/AGENT_EXECUTION.md §18.2): the roles it may claim work as and
    # the projects it may work in. Empty = whatever the issuer may do.
    roles: list[str] = []
    project_ids: list[int] = []
    max_active_claims: int | None = None  # default 1, at most 10


class AgentTokenScope(BaseModel):
    """What an agent token is narrowed to (empty lists = no narrowing)."""

    id: int
    label: str
    roles: list[str] = []
    project_ids: list[int] = []
    max_active_claims: int = 1


class AgentToken(BaseModel):
    """A freshly minted agent token — the only time `access_token` (the secret) is returned."""

    access_token: str
    token_type: str = "bearer"
    scope: str = "agent"
    id: int
    label: str
    expires_minutes: int
    expires_at: datetime
    roles: list[str] = []
    project_ids: list[int] = []
    max_active_claims: int = 1


class AgentTokenInfo(BaseModel):
    """A minted agent token as listed later — metadata only, never the secret."""

    id: int
    label: str
    scope: str
    issued_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    status: str  # active | expired | revoked
    roles: list[str] = []
    project_ids: list[int] = []
    max_active_claims: int = 1
    last_used_at: datetime | None = None


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=MIN_PASSWORD_LENGTH)
    full_name: str | None = None
    role: UserRole = UserRole.member
    function: UserFunction = UserFunction.engineering


class UserUpdate(BaseModel):
    full_name: str | None = None
    role: UserRole | None = None
    function: UserFunction | None = None
    is_active: bool | None = None


class PasswordReset(BaseModel):
    """Admin sets a new (temporary) password for a user."""

    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH)


class MyPreferences(BaseModel):
    """A signed-in user's own preferences. `doc_snapshot_store`: where they keep frozen copies of
    approved design docs — `repo` (a pull request) or `drive` (USER_FLOWS §V9)."""

    doc_snapshot_store: DocSnapshotStore | None = None


class PasswordChange(BaseModel):
    """A user rotates their own password (current one required)."""

    current_password: str
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: EmailStr
    full_name: str | None = None
    role: UserRole
    function: UserFunction = UserFunction.engineering
    is_active: bool
    # where this person keeps frozen copies of approved design docs (repo | drive), §V9
    doc_snapshot_store: str | None = None


class SessionInfo(BaseModel):
    """The active session: the effective (possibly impersonated) user, plus the real admin behind
    it when an admin is impersonating someone else (``None`` for an ordinary session). `scope`
    reports the token's bounded-agency tier (§A6) — an `agent` session can stage change
    proposals but cannot apply them (or take other one-way-door / external-write actions)."""

    user: UserRead
    impersonator: UserRead | None = None
    scope: str = "full"  # full | agent
    # For an agent token: what it is narrowed to (None for a person's own session).
    agent_token: AgentTokenScope | None = None
