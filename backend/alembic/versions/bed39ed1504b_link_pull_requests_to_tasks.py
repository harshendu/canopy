"""link pull requests to tasks

Revision ID: bed39ed1504b
Revises: d15bd4eb5e4e
Create Date: 2026-05-25 21:59:20.015419
"""
from alembic import op
import sqlalchemy as sa


revision = 'bed39ed1504b'
down_revision = 'd15bd4eb5e4e'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Batch mode so the FK add works on SQLite (copy-and-move) as well as Postgres/MySQL.
    with op.batch_alter_table('pullrequest') as batch_op:
        batch_op.add_column(sa.Column('task_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_pullrequest_task_id'), ['task_id'], unique=False)
        batch_op.create_foreign_key('fk_pullrequest_task_id', 'task', ['task_id'], ['id'])


def downgrade() -> None:
    with op.batch_alter_table('pullrequest') as batch_op:
        batch_op.drop_constraint('fk_pullrequest_task_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_pullrequest_task_id'))
        batch_op.drop_column('task_id')
