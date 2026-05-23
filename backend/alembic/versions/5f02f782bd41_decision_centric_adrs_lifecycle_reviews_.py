"""decision-centric ADRs: lifecycle, reviews, comments, queue

Revision ID: 5f02f782bd41
Revises: 3687cc28bfd9
Create Date: 2026-05-23 19:58:19.199540
"""
from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = '5f02f782bd41'
down_revision = '3687cc28bfd9'
branch_labels = None
depends_on = None

# Widened ADR lifecycle (was: proposed/accepted/superseded/deprecated).
_adr_status_new = sa.Enum(
    'proposed', 'under_discussion', 'accepted', 'rejected',
    'superseded', 'deprecated', 'deferred', name='adrstatus',
)
_adr_status_old = sa.Enum(
    'proposed', 'accepted', 'superseded', 'deprecated', name='adrstatus',
)
_reversibility = sa.Enum('one_way', 'two_way', name='reversibility')
_comment_kind = sa.Enum('comment', 'approve', 'request_changes', 'reject', name='adrcommentkind')
_decision_rule = sa.Enum('owner_decides', 'consensus', 'lazy_consensus', name='decisionrule')


def upgrade() -> None:
    op.create_table(
        'adrcomment',
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('adr_id', sa.Integer(), nullable=False),
        sa.Column('engineer_id', sa.Integer(), nullable=True),
        sa.Column('author_name', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('body', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('kind', _comment_kind, nullable=False),
        sa.ForeignKeyConstraint(['adr_id'], ['architecturedecision.id'], ),
        sa.ForeignKeyConstraint(['engineer_id'], ['engineer.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_adrcomment_adr_id'), 'adrcomment', ['adr_id'], unique=False)
    op.create_table(
        'adrstakeholder',
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('adr_id', sa.Integer(), nullable=False),
        sa.Column('engineer_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['adr_id'], ['architecturedecision.id'], ),
        sa.ForeignKeyConstraint(['engineer_id'], ['engineer.id'], ),
        sa.PrimaryKeyConstraint('adr_id', 'engineer_id'),
    )

    # New columns, widened status enum, and decision-owner / proposer FKs.
    # batch (table recreate) is required on SQLite to alter the status CHECK
    # constraint and to add foreign keys to an existing table.
    with op.batch_alter_table('architecturedecision', recreate='always') as batch_op:
        batch_op.add_column(sa.Column('alternatives', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('reversibility', _reversibility, nullable=True))
        batch_op.add_column(sa.Column('decision_owner_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('proposed_by_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('decide_by', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('rfc_url', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
        batch_op.alter_column(
            'status',
            existing_type=_adr_status_old,
            type_=_adr_status_new,
            existing_nullable=False,
        )
        batch_op.create_foreign_key(
            'fk_adr_decision_owner', 'engineer', ['decision_owner_id'], ['id']
        )
        batch_op.create_foreign_key(
            'fk_adr_proposed_by', 'engineer', ['proposed_by_id'], ['id']
        )

    with op.batch_alter_table('project') as batch_op:
        batch_op.add_column(
            sa.Column('decision_rule', _decision_rule, nullable=False, server_default='owner_decides')
        )
        batch_op.add_column(
            sa.Column('decision_sla_hours', sa.Integer(), nullable=False, server_default='72')
        )


def downgrade() -> None:
    with op.batch_alter_table('project') as batch_op:
        batch_op.drop_column('decision_sla_hours')
        batch_op.drop_column('decision_rule')

    with op.batch_alter_table('architecturedecision', recreate='always') as batch_op:
        batch_op.drop_constraint('fk_adr_proposed_by', type_='foreignkey')
        batch_op.drop_constraint('fk_adr_decision_owner', type_='foreignkey')
        batch_op.alter_column(
            'status',
            existing_type=_adr_status_new,
            type_=_adr_status_old,
            existing_nullable=False,
        )
        batch_op.drop_column('rfc_url')
        batch_op.drop_column('decide_by')
        batch_op.drop_column('proposed_by_id')
        batch_op.drop_column('decision_owner_id')
        batch_op.drop_column('reversibility')
        batch_op.drop_column('alternatives')

    op.drop_table('adrstakeholder')
    op.drop_index(op.f('ix_adrcomment_adr_id'), table_name='adrcomment')
    op.drop_table('adrcomment')
