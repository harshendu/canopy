"""initiative leads + leadership notes

Revision ID: 0ecda3c02d48
Revises: f7972e3c5d54
Create Date: 2026-10-09 07:08:56.708154
"""
from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = '0ecda3c02d48'
down_revision = 'f7972e3c5d54'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('leadershipnote',
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('scope_level', sa.Enum('initiative', 'project', name='leadershipscope'), nullable=False),
    sa.Column('scope_id', sa.Integer(), nullable=False),
    sa.Column('target_kind', sa.Enum('decision', 'risk', 'outcome', 'milestone', name='leadershiptargetkind'), nullable=True),
    sa.Column('target_id', sa.Integer(), nullable=True),
    sa.Column('target_label', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('kind', sa.Enum('watch', 'priority', 'feedback', name='leadershipnotekind'), nullable=False),
    sa.Column('priority', sa.Integer(), nullable=True),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('author_user_id', sa.Integer(), nullable=False),
    sa.Column('status', sa.Enum('open', 'acknowledged', 'resolved', name='leadershipnotestatus'), nullable=False),
    sa.Column('response', sa.Text(), nullable=True),
    sa.Column('responded_by_user_id', sa.Integer(), nullable=True),
    sa.Column('responded_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['author_user_id'], ['app_user.id'], ),
    sa.ForeignKeyConstraint(['responded_by_user_id'], ['app_user.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_leadershipnote_author_user_id'), 'leadershipnote', ['author_user_id'], unique=False)
    op.create_index(op.f('ix_leadershipnote_scope_id'), 'leadershipnote', ['scope_id'], unique=False)
    op.create_index(op.f('ix_leadershipnote_scope_level'), 'leadershipnote', ['scope_level'], unique=False)
    op.create_index(op.f('ix_leadershipnote_status'), 'leadershipnote', ['status'], unique=False)
    op.create_table('initiativelead',
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('initiative_id', sa.Integer(), nullable=False),
    sa.Column('engineer_id', sa.Integer(), nullable=False),
    sa.Column('lead_role', sa.Enum('technical', 'product', 'design', 'manager', name='leadrole'), nullable=False),
    sa.ForeignKeyConstraint(['engineer_id'], ['engineer.id'], ),
    sa.ForeignKeyConstraint(['initiative_id'], ['initiative.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_initiativelead_engineer_id'), 'initiativelead', ['engineer_id'], unique=False)
    op.create_index(op.f('ix_initiativelead_initiative_id'), 'initiativelead', ['initiative_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_initiativelead_initiative_id'), table_name='initiativelead')
    op.drop_index(op.f('ix_initiativelead_engineer_id'), table_name='initiativelead')
    op.drop_table('initiativelead')
    op.drop_index(op.f('ix_leadershipnote_status'), table_name='leadershipnote')
    op.drop_index(op.f('ix_leadershipnote_scope_level'), table_name='leadershipnote')
    op.drop_index(op.f('ix_leadershipnote_scope_id'), table_name='leadershipnote')
    op.drop_index(op.f('ix_leadershipnote_author_user_id'), table_name='leadershipnote')
    op.drop_table('leadershipnote')
