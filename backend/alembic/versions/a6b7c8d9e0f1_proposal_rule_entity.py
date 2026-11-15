"""proposals can stage a delivery rule

Phase 4 of docs/AGENT_EXECUTION.md (§21): a session that sees the same review note recurring
stages a `rule` proposal item for a person to accept. Adds `rule` to the `proposalentity` enum —
dialect-branched like every enum change (Postgres recreates the native TYPE, MySQL/MariaDB
MODIFY the column, SQLite swaps the CHECK through a batch rebuild).

Revision ID: a6b7c8d9e0f1
Revises: f4a5b6c7d8e9
Create Date: 2026-11-15 14:00:00
"""

import sqlalchemy as sa
from alembic import op

revision = "a6b7c8d9e0f1"
down_revision = "f4a5b6c7d8e9"
branch_labels = None
depends_on = None

_OLD = ("task", "dependency", "milestone", "blocker", "risk", "outcome", "decision",
        "doc_reference")
_NEW = (*_OLD, "rule")


def _alter_enum_column(
    table: str, column: str, *, name: str,
    old_values: tuple[str, ...], new_values: tuple[str, ...], nullable: bool,
) -> None:
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
    else:  # sqlite: swap the CHECK constraint via a table recreate
        with op.batch_alter_table(table) as batch_op:
            batch_op.alter_column(
                column,
                existing_type=sa.Enum(*old_values, name=name),
                type_=sa.Enum(*new_values, name=name),
                existing_nullable=nullable,
            )


def upgrade() -> None:
    _alter_enum_column("proposalitem", "entity_type", name="proposalentity",
                       old_values=_OLD, new_values=_NEW, nullable=False)


def downgrade() -> None:
    # Rule items can't survive the narrower enum: drop them (and nothing else) first.
    op.execute("DELETE FROM proposalitem WHERE entity_type = 'rule'")
    _alter_enum_column("proposalitem", "entity_type", name="proposalentity",
                       old_values=_NEW, new_values=_OLD, nullable=False)
