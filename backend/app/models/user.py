from sqlmodel import Field

from app.models.base import TimestampMixin, UserFunction, UserRole


class User(TimestampMixin, table=True):
    __tablename__ = "app_user"

    id: int | None = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True)
    hashed_password: str
    full_name: str | None = None
    role: UserRole = Field(default=UserRole.member)  # access tier (gates writes)
    function: UserFunction = Field(default=UserFunction.engineering)  # cross-functional persona
    is_active: bool = True
    # Where this person keeps frozen copies of approved design docs: repo | drive
    # (`DocSnapshotStore`); each freeze can override it. NULL = not chosen yet.
    doc_snapshot_store: str | None = Field(default=None, max_length=16)
