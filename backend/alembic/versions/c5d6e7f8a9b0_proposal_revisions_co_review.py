"""proposal revisions: revise an open proposal in place while it is reviewed

Revision ID: c5d6e7f8a9b0
Revises: b4c1d2e3f5a6
Create Date: 2026-11-14 09:00:00.000000

Adds the co-review trail (§AA5): `proposal.revision` (starts at 1, bumps on every revise),
`proposal.revised_at`, `proposal.revision_note` (the author's "what changed" line for the
reviewer), and `proposalitem.revision` (the proposal revision that added or last rewrote the
item, so the UI can mark what is new).

Plain additive columns only (via batch_alter_table → native ADD COLUMN on every dialect). The
NOT NULL counters carry a server_default so existing rows backfill to revision 1.
"""
import sqlalchemy as sa
from alembic import op

revision = "c5d6e7f8a9b0"
down_revision = "b4c1d2e3f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("proposal") as batch:
        batch.add_column(sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("revised_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("revision_note", sa.Text(), nullable=True))
    with op.batch_alter_table("proposalitem") as batch:
        batch.add_column(sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))


def downgrade() -> None:
    with op.batch_alter_table("proposalitem") as batch:
        batch.drop_column("revision")
    with op.batch_alter_table("proposal") as batch:
        batch.drop_column("revision_note")
        batch.drop_column("revised_at")
        batch.drop_column("revision")
