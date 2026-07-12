"""change proposals: agent-staged writes reviewed + applied by a human in the UI

Revision ID: b0a0b4c58fbe
Revises: 22ad48e0d5fb
Create Date: 2026-07-12 21:11:18.583384
"""
from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = 'b0a0b4c58fbe'
down_revision = '22ad48e0d5fb'
branch_labels = None
depends_on = None


def _drop_pg_type(name: str) -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"DROP TYPE IF EXISTS {name}")


def upgrade() -> None:
    op.create_table(
        'proposal',
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column(
            'scope_level',
            sa.Enum('project', 'initiative', name='proposalscope'),
            nullable=False,
        ),
        sa.Column('scope_id', sa.Integer(), nullable=False),
        sa.Column('title', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('origin', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column(
            'status',
            sa.Enum('open', 'applied', 'rejected', 'withdrawn', name='proposalstatus'),
            nullable=False,
        ),
        sa.Column('created_by_user_id', sa.Integer(), nullable=True),
        sa.Column('reviewed_by_user_id', sa.Integer(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('review_note', sa.Text(), nullable=True),
        sa.Column('applied_count', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['app_user.id'], ),
        sa.ForeignKeyConstraint(['reviewed_by_user_id'], ['app_user.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_proposal_scope_id'), 'proposal', ['scope_id'], unique=False)
    op.create_index(op.f('ix_proposal_scope_level'), 'proposal', ['scope_level'], unique=False)
    op.create_index(op.f('ix_proposal_status'), 'proposal', ['status'], unique=False)
    op.create_table(
        'proposalitem',
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('proposal_id', sa.Integer(), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.Column(
            'entity_type',
            sa.Enum(
                'task', 'dependency', 'milestone', 'blocker', 'risk', 'outcome',
                'decision', 'doc_reference', name='proposalentity',
            ),
            nullable=False,
        ),
        sa.Column(
            'action',
            sa.Enum('create', 'update', 'resolve', name='proposalaction'),
            nullable=False,
        ),
        sa.Column('entity_id', sa.Integer(), nullable=True),
        sa.Column('ref', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('payload', sa.JSON(), nullable=True),
        sa.Column('before', sa.JSON(), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('source_kind', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('source_label', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('source_url', sa.Text(), nullable=True),
        sa.Column('excluded', sa.Boolean(), nullable=False),
        sa.Column('applied_entity_id', sa.Integer(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['proposal_id'], ['proposal.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_proposalitem_proposal_id'), 'proposalitem', ['proposal_id'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_proposalitem_proposal_id'), table_name='proposalitem')
    op.drop_table('proposalitem')
    op.drop_index(op.f('ix_proposal_status'), table_name='proposal')
    op.drop_index(op.f('ix_proposal_scope_level'), table_name='proposal')
    op.drop_index(op.f('ix_proposal_scope_id'), table_name='proposal')
    op.drop_table('proposal')
    for _type in ('proposalscope', 'proposalstatus', 'proposalentity', 'proposalaction'):
        _drop_pg_type(_type)
