from datetime import datetime

from sqlmodel import Field

from app.models.base import TimestampMixin, TokenScope


class AgentTokenRecord(TimestampMixin, table=True):
    """Metadata for a minted **agent** token (§A6). The access token itself is a stateless JWT and
    is **never stored** — only shown once at creation. This row lets the Agent Setup tab list a
    user's live tokens with their expiry, and lets the JWT be revoked before it expires: the token
    carries a matching `jti` claim, and `get_current_user` rejects it once `revoked_at` is set.

    `created_at` (from the mixin) is the issue time; `expires_at` mirrors the JWT's `exp`."""

    __tablename__ = "agent_token"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="app_user.id", index=True)  # the issuer the token acts as
    jti: str = Field(index=True, unique=True)  # correlates the JWT to this row (for revocation)
    label: str = Field(default="Agent token")  # human-friendly name (e.g. "My laptop")
    scope: str = Field(default=TokenScope.agent.value)  # always "agent" today
    expires_at: datetime  # absolute expiry (mirrors the JWT `exp`)
    revoked_at: datetime | None = Field(default=None)  # set → the JWT stops authenticating
