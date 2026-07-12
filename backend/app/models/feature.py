from sqlmodel import Field, UniqueConstraint

from app.models.base import TimestampMixin


class FeatureFlag(TimestampMixin, table=True):
    """An admin's on/off override for one feature gate.

    One row per feature key. The **absence** of a row means the catalog default (enabled), so
    a fresh install has everything on and behavior is unchanged until an admin opts out. Keys
    are two-level — a group (`planning`) or a feature within it (`planning.scenarios`) — and a
    disabled group turns off all of its children (see `app/services/features.py`).
    """

    __table_args__ = (UniqueConstraint("key", name="uq_feature_flag_key"),)

    id: int | None = Field(default=None, primary_key=True)
    key: str = Field(index=True)
    enabled: bool = True
