"""design docs: the source's last change from the organization artifact sync

Revision ID: 2d3e4f5a6b7c
Revises: 1c2d3e4f5a6b
Create Date: 2026-11-15 21:00:00

USER_FLOWS §V11: `docreference.source_updated_at` — when the Claude artifact last changed, as
the Compliance API lists it. Claude Docs and Sheets carry no version ids, so this timestamp is
their change signal (a check is due, or the doc changed after approval). The new `claude`
connection provider needs no schema change (`provider` columns are VARCHAR(32)).
"""

import sqlalchemy as sa
from alembic import op

revision = "2d3e4f5a6b7c"
down_revision = "1c2d3e4f5a6b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("docreference") as batch:
        batch.add_column(sa.Column("source_updated_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("docreference") as batch:
        batch.drop_column("source_updated_at")
