"""agent token records: persist minted agent-token metadata so it can be listed + revoked

Revision ID: a4b243068f52
Revises: b0a0b4c58fbe
Create Date: 2026-07-13 00:43:08.548101
"""
from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = 'a4b243068f52'
down_revision = 'b0a0b4c58fbe'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # New table only — a plain CREATE is portable across Postgres / MySQL / SQLite (no batch needed).
    op.create_table(
        'agent_token',
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('jti', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('label', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('scope', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['app_user.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_agent_token_jti'), 'agent_token', ['jti'], unique=True)
    op.create_index(op.f('ix_agent_token_user_id'), 'agent_token', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_agent_token_user_id'), table_name='agent_token')
    op.drop_index(op.f('ix_agent_token_jti'), table_name='agent_token')
    op.drop_table('agent_token')
