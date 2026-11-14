"""provider columns: native enum → VARCHAR(32)

Revision ID: f8a9b0c1d2e3
Revises: e7f8a9b0c1d2
Create Date: 2026-11-16 09:00:00

Adding a work tracker (USER_FLOWS §J0) must be one enum member + one module, with no
dialect-branched enum migration each time. So the `provider` columns of `connection`,
`externalref` and `integrationsetting` stop being a native enum:

- Postgres: `ALTER COLUMN … TYPE VARCHAR(32) USING provider::text`, then drop the `provider`
  TYPE (nothing else uses it);
- MySQL/MariaDB: `MODIFY` the ENUM column to VARCHAR(32) (indexes and the unique constraint on
  `integrationsetting.provider` are kept as they are);
- SQLite: already VARCHAR (a non-native enum) and lengths are not enforced — nothing to do.

Values are unchanged (`jira` | `github` | `gdrive`); the model maps the column with a
non-native `sa.Enum(..., length=32)`, so validation stays in Python.
"""

import sqlalchemy as sa
from alembic import op

revision = "f8a9b0c1d2e3"
down_revision = "e7f8a9b0c1d2"
branch_labels = None
depends_on = None

_TABLES = ("connection", "externalref", "integrationsetting")
_OLD_VALUES = ("jira", "github", "gdrive")


def _old_enum(create_type: bool = False) -> sa.Enum:
    return sa.Enum(*_OLD_VALUES, name="provider", create_type=create_type)


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        for table in _TABLES:
            op.alter_column(
                table,
                "provider",
                existing_type=_old_enum(),
                type_=sa.String(length=32),
                existing_nullable=False,
                postgresql_using="provider::text",
            )
        op.execute("DROP TYPE IF EXISTS provider")
    elif dialect in ("mysql", "mariadb"):
        for table in _TABLES:
            op.alter_column(
                table,
                "provider",
                existing_type=_old_enum(),
                type_=sa.String(length=32),
                existing_nullable=False,
            )
    # SQLite: the column is already VARCHAR; nothing to change.


def downgrade() -> None:
    """Back to the native enum. Rows for a provider outside the old set (a tracker added
    since) must be removed first, or the cast fails — by design, nothing is dropped here."""
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        _old_enum(create_type=True).create(op.get_bind(), checkfirst=True)
        for table in _TABLES:
            op.alter_column(
                table,
                "provider",
                existing_type=sa.String(length=32),
                type_=_old_enum(),
                existing_nullable=False,
                postgresql_using="provider::provider",
            )
    elif dialect in ("mysql", "mariadb"):
        for table in _TABLES:
            op.alter_column(
                table,
                "provider",
                existing_type=sa.String(length=32),
                type_=_old_enum(),
                existing_nullable=False,
            )
