"""component owner criticality tier

Revision ID: 45c951385141
Revises: 0a8e476ef984
Create Date: 2026-05-23 21:31:11.833906
"""
from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = '45c951385141'
down_revision = '0a8e476ef984'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # batch mode lets SQLite recreate the table to add the owner FK; Postgres/MySQL get a
    # native ALTER (recreate='auto', the default, never force-recreates a FK-referenced table).
    with op.batch_alter_table('architecturecomponent') as batch_op:
        batch_op.add_column(sa.Column('owner_engineer_id', sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column('criticality', sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )
        batch_op.add_column(sa.Column('tier', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
        batch_op.add_column(
            sa.Column('observability_url', sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )
        batch_op.create_foreign_key(
            'fk_component_owner', 'engineer', ['owner_engineer_id'], ['id']
        )


def downgrade() -> None:
    with op.batch_alter_table('architecturecomponent') as batch_op:
        batch_op.drop_constraint('fk_component_owner', type_='foreignkey')
        batch_op.drop_column('observability_url')
        batch_op.drop_column('tier')
        batch_op.drop_column('criticality')
        batch_op.drop_column('owner_engineer_id')
