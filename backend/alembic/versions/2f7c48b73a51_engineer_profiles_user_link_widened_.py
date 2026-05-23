"""engineer profiles + user link + widened roles

Revision ID: 2f7c48b73a51
Revises: f6ee927e22bf
Create Date: 2026-05-23 20:26:59.079736
"""
from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = '2f7c48b73a51'
down_revision = 'f6ee927e22bf'
branch_labels = None
depends_on = None

_role_new = sa.Enum(
    'admin', 'architect', 'engineering_manager', 'engineer', 'viewer', 'member',
    name='userrole',
)
_role_old = sa.Enum('admin', 'member', name='userrole')


def upgrade() -> None:
    # Widen the role enum. batch (table recreate) is required on SQLite to alter the
    # CHECK constraint backing the enum.
    with op.batch_alter_table('app_user') as batch_op:
        batch_op.alter_column(
            'role',
            existing_type=_role_old,
            type_=_role_new,
            existing_nullable=False,
        )

    # New engineer profile columns + the user link. batch is required on SQLite to add
    # the foreign key to an existing table.
    with op.batch_alter_table('engineer', recreate='always') as batch_op:
        batch_op.add_column(sa.Column('user_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('skill_tags', sa.JSON(), nullable=True))
        batch_op.add_column(
            sa.Column('github_login', sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )
        batch_op.add_column(
            sa.Column('timezone', sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )
        batch_op.add_column(sa.Column('committed_hours_per_week', sa.Float(), nullable=True))
        batch_op.create_foreign_key('fk_engineer_user', 'app_user', ['user_id'], ['id'])


def downgrade() -> None:
    with op.batch_alter_table('engineer', recreate='always') as batch_op:
        batch_op.drop_constraint('fk_engineer_user', type_='foreignkey')
        batch_op.drop_column('committed_hours_per_week')
        batch_op.drop_column('timezone')
        batch_op.drop_column('github_login')
        batch_op.drop_column('skill_tags')
        batch_op.drop_column('user_id')

    with op.batch_alter_table('app_user') as batch_op:
        batch_op.alter_column(
            'role',
            existing_type=_role_new,
            type_=_role_old,
            existing_nullable=False,
        )
