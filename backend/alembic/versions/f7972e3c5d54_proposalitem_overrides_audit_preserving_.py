"""proposalitem overrides: audit-preserving inline field override

Revision ID: f7972e3c5d54
Revises: f7946b688d63
Create Date: 2026-07-13 15:33:47.359860

Adds the reviewer's inline-override trail to `proposalitem` (§AA2/T17): `overrides` (JSON) layered
over the agent's original `payload` at apply time, plus `overridden_by_user_id` / `overridden_at`
audit stamps. All nullable, no default — existing items have no override, exactly as before.

Plain additive columns only (via batch_alter_table → native ADD COLUMN on every dialect). No DB
foreign key on `overridden_by_user_id` on purpose: adding an FK to an existing table would force a
SQLite table rebuild (portability-hostile per CLAUDE.md) for what is only audit metadata.
"""
import sqlalchemy as sa
from alembic import op

revision = "f7972e3c5d54"
down_revision = "f7946b688d63"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("proposalitem") as batch:
        batch.add_column(sa.Column("overrides", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("overridden_by_user_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("overridden_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("proposalitem") as batch:
        batch.drop_column("overridden_at")
        batch.drop_column("overridden_by_user_id")
        batch.drop_column("overrides")
