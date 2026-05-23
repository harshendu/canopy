from sqlmodel import Field

from app.models.base import TimestampMixin, UserRole


class User(TimestampMixin, table=True):
    __tablename__ = "app_user"

    id: int | None = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True)
    hashed_password: str
    full_name: str | None = None
    role: UserRole = Field(default=UserRole.member)
    is_active: bool = True
