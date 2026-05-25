"""integration policy per provider

Revision ID: dba4be383440
Revises: d4e5f6a7b8c0
Create Date: 2026-05-25 15:16:08.247868
"""
from alembic import op
import sqlalchemy as sa


revision = 'dba4be383440'
down_revision = 'd4e5f6a7b8c0'
branch_labels = None
depends_on = None


def _drop_pg_type(name: str) -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"DROP TYPE IF EXISTS {name}")


def upgrade() -> None:
    op.create_table(
        'integrationsetting',
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('id', sa.Integer(), nullable=False),
        # Reuse the existing `provider` enum (created for the connection table); don't re-CREATE TYPE.
        sa.Column(
            'provider',
            sa.Enum('jira', 'github', 'gdrive', name='provider', create_type=False),
            nullable=False,
        ),
        sa.Column(
            'read_strategy',
            sa.Enum('direct', 'mcp', 'file', name='readstrategy'),
            nullable=False,
        ),
        sa.Column(
            'write_strategy',
            sa.Enum('direct', 'mcp', 'disabled', name='writestrategy'),
            nullable=False,
        ),
        sa.Column('allow_user_connect', sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('provider', name='uq_integration_setting_provider'),
    )
    op.create_index(
        op.f('ix_integrationsetting_provider'), 'integrationsetting', ['provider'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_integrationsetting_provider'), table_name='integrationsetting')
    op.drop_table('integrationsetting')
    # `provider` is shared with the connection table — only drop the enum types this table introduced.
    for _type in ('readstrategy', 'writestrategy'):
        _drop_pg_type(_type)
