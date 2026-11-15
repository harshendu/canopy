"""design docs in the lifecycle: doc_link proposal items, source docs on proposals and plans

Revision ID: 1c2d3e4f5a6b
Revises: 0b1c2d3e4f5a
Create Date: 2026-11-15 18:00:00

USER_FLOWS §V9:

- `proposalitem.entity_type` stops being a native enum (VARCHAR(32)) so `doc_link` — and any
  later stageable entity — is one enum member, the provider-column precedent (`f8a9b0c1d2e3`):
  Postgres `ALTER … TYPE VARCHAR(32) USING entity_type::text` then drops the TYPE; MySQL /
  MariaDB `MODIFY`; SQLite is already a VARCHAR with no CHECK.
- `proposal.source_doc_id` / `source_doc_version` and `draftplan.source_doc_id` /
  `source_doc_version`: the design doc (and the version read) staged changes or a draft plan
  were derived from.

Downgrade drops the new columns and restores the native enum (staged `doc_link` items are
removed first — the old enum cannot hold them).
"""

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision = "1c2d3e4f5a6b"
down_revision = "0b1c2d3e4f5a"
branch_labels = None
depends_on = None

_OLD_ENTITIES = (
    "task", "dependency", "milestone", "blocker", "risk", "outcome", "decision", "doc_reference",
)


def _old_enum() -> sa.Enum:
    return sa.Enum(*_OLD_ENTITIES, name="proposalentity")


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.alter_column(
            "proposalitem", "entity_type", existing_type=_old_enum(),
            type_=sa.String(length=32), existing_nullable=False,
            postgresql_using="entity_type::text",
        )
        op.execute("DROP TYPE IF EXISTS proposalentity")
    elif dialect in ("mysql", "mariadb"):
        op.alter_column(
            "proposalitem", "entity_type", existing_type=_old_enum(),
            type_=sa.String(length=32), existing_nullable=False,
        )
    # SQLite: already a VARCHAR without a CHECK; nothing to change.

    for table in ("proposal", "draftplan"):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("source_doc_id", sa.Integer(), nullable=True))
            batch.add_column(sa.Column(
                "source_doc_version", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True
            ))
            batch.create_foreign_key(
                f"fk_{table}_source_doc_id_docreference", "docreference",
                ["source_doc_id"], ["id"],
            )


def downgrade() -> None:
    for table in ("draftplan", "proposal"):
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(f"fk_{table}_source_doc_id_docreference", type_="foreignkey")
            batch.drop_column("source_doc_version")
            batch.drop_column("source_doc_id")

    item = sa.table("proposalitem", sa.column("entity_type", sa.String))
    op.get_bind().execute(item.delete().where(item.c.entity_type.not_in(_OLD_ENTITIES)))
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        _old_enum().create(op.get_bind(), checkfirst=True)
        op.alter_column(
            "proposalitem", "entity_type", existing_type=sa.String(length=32),
            type_=_old_enum(), existing_nullable=False,
            postgresql_using="entity_type::proposalentity",
        )
    elif dialect in ("mysql", "mariadb"):
        op.alter_column(
            "proposalitem", "entity_type", existing_type=sa.String(length=32),
            type_=_old_enum(), existing_nullable=False,
        )
