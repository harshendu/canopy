"""outcomes: outcomes over output — measurable bets on projects / initiatives

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-05-25 14:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def _drop_pg_type(name: str) -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"DROP TYPE IF EXISTS {name}")


def upgrade() -> None:
    op.create_table(
        'outcome',
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column(
            'scope_level',
            sa.Enum('project', 'initiative', name='outcomescope'),
            nullable=False,
        ),
        sa.Column('scope_id', sa.Integer(), nullable=False),
        sa.Column('statement', sa.Text(), nullable=False),
        sa.Column('metric', sa.Text(), nullable=True),
        sa.Column('unit', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('baseline_value', sa.Float(), nullable=True),
        sa.Column('target_value', sa.Float(), nullable=True),
        sa.Column('current_value', sa.Float(), nullable=True),
        sa.Column(
            'status',
            sa.Enum(
                'pending', 'on_track', 'at_risk', 'validated', 'invalidated', name='outcomestatus'
            ),
            nullable=False,
        ),
        sa.Column('target_date', sa.Date(), nullable=True),
        sa.Column('owner_engineer_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['owner_engineer_id'], ['engineer.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_outcome_scope_id'), 'outcome', ['scope_id'], unique=False)
    op.create_index(op.f('ix_outcome_scope_level'), 'outcome', ['scope_level'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_outcome_scope_level'), table_name='outcome')
    op.drop_index(op.f('ix_outcome_scope_id'), table_name='outcome')
    op.drop_table('outcome')
    for _type in ('outcomescope', 'outcomestatus'):
        _drop_pg_type(_type)
