"""user connection (per-user oauth credential)

Revision ID: d15bd4eb5e4e
Revises: dba4be383440
Create Date: 2026-05-25 15:44:25.717209
"""
from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = 'd15bd4eb5e4e'
down_revision = 'dba4be383440'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'userconnection',
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('connection_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('encrypted_token', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('encrypted_refresh_token', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('token_expires_at', sa.DateTime(), nullable=True),
        sa.Column('watermark', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['connection_id'], ['connection.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['app_user.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('connection_id', 'user_id', name='uq_user_connection'),
    )
    op.create_index(
        op.f('ix_userconnection_connection_id'), 'userconnection', ['connection_id'], unique=False
    )
    op.create_index(
        op.f('ix_userconnection_user_id'), 'userconnection', ['user_id'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_userconnection_user_id'), table_name='userconnection')
    op.drop_index(op.f('ix_userconnection_connection_id'), table_name='userconnection')
    op.drop_table('userconnection')
