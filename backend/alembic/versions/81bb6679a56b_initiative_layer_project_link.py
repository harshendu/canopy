"""initiative layer + project link

Revision ID: 81bb6679a56b
Revises: cbed47b3c958
Create Date: 2026-05-23 22:30:56.141676
"""
from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = '81bb6679a56b'
down_revision = 'cbed47b3c958'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('initiative',
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('key', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('outcome_statement', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('start_date', sa.Date(), nullable=True),
    sa.Column('target_date', sa.Date(), nullable=True),
    sa.Column('owner_engineer_id', sa.Integer(), nullable=True),
    sa.Column('archived', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['owner_engineer_id'], ['engineer.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_initiative_key'), 'initiative', ['key'], unique=True)
    # Batch mode so the FK add works on SQLite (copy-and-move) as well as Postgres.
    with op.batch_alter_table('project') as batch_op:
        batch_op.add_column(sa.Column('initiative_id', sa.Integer(), nullable=True))
        batch_op.create_index(
            batch_op.f('ix_project_initiative_id'), ['initiative_id'], unique=False
        )
        batch_op.create_foreign_key(
            'fk_project_initiative_id', 'initiative', ['initiative_id'], ['id']
        )


def downgrade() -> None:
    with op.batch_alter_table('project') as batch_op:
        batch_op.drop_constraint('fk_project_initiative_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_project_initiative_id'))
        batch_op.drop_column('initiative_id')
    op.drop_index(op.f('ix_initiative_key'), table_name='initiative')
    op.drop_table('initiative')
