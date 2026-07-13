"""task constraint_start: user SNET pin, separate from computed start

Revision ID: f7946b688d63
Revises: a4b243068f52
Create Date: 2026-07-13 14:21:25.202378

Adds `task.constraint_start` — a user "start no earlier than" scheduling constraint, kept separate
from the CPM-computed `start` so a replan no longer reuses last run's output as this run's pin
(which made the schedule ratchet forward-only and left what-if inert). Nullable, no default — every
existing task starts with no explicit constraint, exactly as before.

Autogenerate also flagged a batch of VARCHAR→Text "changes" on existing columns; those are a
SQLite type-reflection artifact (the columns are already Text via revision d4e5f6a7b8c9) and are
deliberately omitted — only the new column is real.
"""
import sqlalchemy as sa
from alembic import op

revision = "f7946b688d63"
down_revision = "a4b243068f52"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("task") as batch:
        batch.add_column(sa.Column("constraint_start", sa.Date(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("task") as batch:
        batch.drop_column("constraint_start")
