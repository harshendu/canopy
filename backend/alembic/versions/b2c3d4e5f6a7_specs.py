"""specs: spec-driven development (intent + acceptance criteria, task linkage)

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-25 13:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = 'b2c3d4e5f6a7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def _drop_pg_type(name: str) -> None:
    """Drop a leftover native enum type (Postgres only; a no-op elsewhere)."""
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"DROP TYPE IF EXISTS {name}")


def upgrade() -> None:
    # CREATE TABLE auto-creates the native enum TYPEs on Postgres; MySQL stores them inline,
    # SQLite as a CHECK. Long free-text (problem/context/source_url) is TEXT for MySQL portability.
    op.create_table(
        'spec',
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('title', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('problem', sa.Text(), nullable=False),
        sa.Column('context', sa.Text(), nullable=True),
        sa.Column('out_of_scope', sa.Text(), nullable=True),
        sa.Column(
            'status',
            sa.Enum('draft', 'approved', 'in_progress', 'verified', 'archived', name='specstatus'),
            nullable=False,
        ),
        sa.Column('owner_engineer_id', sa.Integer(), nullable=True),
        sa.Column('adr_id', sa.Integer(), nullable=True),
        sa.Column('source_url', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['project.id'], ),
        sa.ForeignKeyConstraint(['owner_engineer_id'], ['engineer.id'], ),
        sa.ForeignKeyConstraint(['adr_id'], ['architecturedecision.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_spec_project_id'), 'spec', ['project_id'], unique=False)
    op.create_index(op.f('ix_spec_status'), 'spec', ['status'], unique=False)

    op.create_table(
        'speccriterion',
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('spec_id', sa.Integer(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column(
            'status',
            sa.Enum('open', 'met', 'unmet', 'waived', name='criterionstatus'),
            nullable=False,
        ),
        sa.Column('verification', sa.Text(), nullable=True),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['spec_id'], ['spec.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_speccriterion_spec_id'), 'speccriterion', ['spec_id'], unique=False)

    # task.spec_id — the task → spec link. batch lets SQLite recreate; PG/MySQL get a native ALTER.
    with op.batch_alter_table('task') as batch_op:
        batch_op.add_column(sa.Column('spec_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_task_spec', 'spec', ['spec_id'], ['id'])
    op.create_index(op.f('ix_task_spec_id'), 'task', ['spec_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_task_spec_id'), table_name='task')
    with op.batch_alter_table('task') as batch_op:
        batch_op.drop_constraint('fk_task_spec', type_='foreignkey')
        batch_op.drop_column('spec_id')
    op.drop_index(op.f('ix_speccriterion_spec_id'), table_name='speccriterion')
    op.drop_table('speccriterion')
    op.drop_index(op.f('ix_spec_status'), table_name='spec')
    op.drop_index(op.f('ix_spec_project_id'), table_name='spec')
    op.drop_table('spec')
    for _type in ('specstatus', 'criterionstatus'):
        _drop_pg_type(_type)
