"""user function: cross-functional persona (PM/UX/staff/director/exec), orthogonal to role

Revision ID: d4e5f6a7b8c0
Revises: c3d4e5f6a7b8
Create Date: 2026-05-25 15:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'd4e5f6a7b8c0'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None

# Adding an enum column via ALTER needs the Postgres TYPE created first (a no-op elsewhere).
_user_function = sa.Enum(
    'engineering', 'product', 'design', 'architecture', 'management', 'leadership',
    name='userfunction',
)


def upgrade() -> None:
    bind = op.get_bind()
    _user_function.create(bind, checkfirst=True)
    # batch lets SQLite recreate the table; Postgres/MySQL get a native ALTER. A server_default
    # backfills existing rows; new rows get the value from the ORM default.
    with op.batch_alter_table('app_user') as batch_op:
        batch_op.add_column(
            sa.Column('function', _user_function, nullable=False, server_default='engineering')
        )


def downgrade() -> None:
    with op.batch_alter_table('app_user') as batch_op:
        batch_op.drop_column('function')
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TYPE IF EXISTS userfunction")
