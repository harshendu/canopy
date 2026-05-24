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

_role_new = (
    'admin', 'architect', 'engineering_manager', 'engineer', 'viewer', 'member',
)
_role_old = ('admin', 'member')


def _alter_enum_column(
    table: str, column: str, *, name: str,
    old_values: tuple[str, ...], new_values: tuple[str, ...], nullable: bool,
) -> None:
    """Change an enum column's allowed values portably across dialects.

    Postgres backs an enum with a native TYPE (recreate it, then re-point the column);
    MySQL/MariaDB store the value set inline on the column (MODIFY it); SQLite uses a
    CHECK constraint (batch table-recreate). The forced full-table recreate that SQLite
    needs would break on Postgres/MySQL (it drops a PK/FKs other tables depend on), so we
    branch instead of using one batch path for all three.
    """
    bind = op.get_bind()
    dialect = bind.dialect.name
    values_sql = ", ".join(f"'{v}'" for v in new_values)
    if dialect == "postgresql":
        op.execute(f"ALTER TYPE {name} RENAME TO {name}_old")
        op.execute(f"CREATE TYPE {name} AS ENUM ({values_sql})")
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} TYPE {name} "
            f"USING {column}::text::{name}"
        )
        op.execute(f"DROP TYPE {name}_old")
    elif dialect in ("mysql", "mariadb"):
        null = "NULL" if nullable else "NOT NULL"
        op.execute(f"ALTER TABLE {table} MODIFY `{column}` ENUM({values_sql}) {null}")
    else:  # sqlite & others: swap the CHECK constraint via a table recreate
        with op.batch_alter_table(table) as batch_op:
            batch_op.alter_column(
                column,
                existing_type=sa.Enum(*old_values, name=name),
                type_=sa.Enum(*new_values, name=name),
                existing_nullable=nullable,
            )


def upgrade() -> None:
    _alter_enum_column(
        'app_user', 'role', name='userrole',
        old_values=_role_old, new_values=_role_new, nullable=False,
    )

    # New engineer profile columns + the user link. batch lets SQLite recreate the table to
    # add the FK; Postgres/MySQL get a native ALTER (default recreate='auto').
    with op.batch_alter_table('engineer') as batch_op:
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
    with op.batch_alter_table('engineer') as batch_op:
        batch_op.drop_constraint('fk_engineer_user', type_='foreignkey')
        batch_op.drop_column('committed_hours_per_week')
        batch_op.drop_column('timezone')
        batch_op.drop_column('github_login')
        batch_op.drop_column('skill_tags')
        batch_op.drop_column('user_id')

    _alter_enum_column(
        'app_user', 'role', name='userrole',
        old_values=_role_new, new_values=_role_old, nullable=False,
    )
