"""feature gates + engineer jira account id

Feature gates: one `featureflag` row per admin override (missing row = enabled; see
`app/services/features.py` for the catalog and group/child resolution).
Engineer: `jira_account_id` so synced Jira assignees map onto the same Engineer.

Both changes are plain portable DDL (new table / nullable column add) — no table rebuilds,
no enum work — so they run forward unchanged on Postgres, MySQL/MariaDB, and SQLite.

Revision ID: 22ad48e0d5fb
Revises: bed39ed1504b
Create Date: 2026-07-12 19:52:30.220262
"""
from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = '22ad48e0d5fb'
down_revision = 'bed39ed1504b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'featureflag',
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('key', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key', name='uq_feature_flag_key'),
    )
    op.create_index(op.f('ix_featureflag_key'), 'featureflag', ['key'], unique=False)
    op.add_column(
        'engineer',
        sa.Column('jira_account_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    )
    # Unique index (NULLs exempt on all three dialects): one Engineer per Jira account.
    op.create_index(
        op.f('ix_engineer_jira_account_id'), 'engineer', ['jira_account_id'], unique=True
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_engineer_jira_account_id'), table_name='engineer')
    op.drop_column('engineer', 'jira_account_id')
    op.drop_index(op.f('ix_featureflag_key'), table_name='featureflag')
    op.drop_table('featureflag')
