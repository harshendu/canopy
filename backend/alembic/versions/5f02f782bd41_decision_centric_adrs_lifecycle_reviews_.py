"""decision-centric ADRs: lifecycle, reviews, comments, queue

Revision ID: 5f02f782bd41
Revises: 3687cc28bfd9
Create Date: 2026-05-23 19:58:19.199540
"""
from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = '5f02f782bd41'
down_revision = '3687cc28bfd9'
branch_labels = None
depends_on = None

# Widened ADR lifecycle (was: proposed/accepted/superseded/deprecated).
_adr_status_new = (
    'proposed', 'under_discussion', 'accepted', 'rejected',
    'superseded', 'deprecated', 'deferred',
)
_adr_status_old = ('proposed', 'accepted', 'superseded', 'deprecated')
_reversibility = sa.Enum('one_way', 'two_way', name='reversibility')
_comment_kind = sa.Enum('comment', 'approve', 'request_changes', 'reject', name='adrcommentkind')
_decision_rule = sa.Enum('owner_decides', 'consensus', 'lazy_consensus', name='decisionrule')


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


def _drop_pg_type(name: str) -> None:
    """Drop a leftover native enum type (Postgres only; a no-op elsewhere)."""
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"DROP TYPE IF EXISTS {name}")


def upgrade() -> None:
    op.create_table(
        'adrcomment',
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('adr_id', sa.Integer(), nullable=False),
        sa.Column('engineer_id', sa.Integer(), nullable=True),
        sa.Column('author_name', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('body', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('kind', _comment_kind, nullable=False),
        sa.ForeignKeyConstraint(['adr_id'], ['architecturedecision.id'], ),
        sa.ForeignKeyConstraint(['engineer_id'], ['engineer.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_adrcomment_adr_id'), 'adrcomment', ['adr_id'], unique=False)
    op.create_table(
        'adrstakeholder',
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('adr_id', sa.Integer(), nullable=False),
        sa.Column('engineer_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['adr_id'], ['architecturedecision.id'], ),
        sa.ForeignKeyConstraint(['engineer_id'], ['engineer.id'], ),
        sa.PrimaryKeyConstraint('adr_id', 'engineer_id'),
    )

    # Widen the ADR status enum (dialect-aware: native TYPE on PG, MODIFY on MySQL, CHECK
    # swap on SQLite).
    _alter_enum_column(
        'architecturedecision', 'status', name='adrstatus',
        old_values=_adr_status_old, new_values=_adr_status_new, nullable=False,
    )

    # New columns + decision-owner / proposer FKs. batch lets SQLite recreate the table to
    # add the FKs; Postgres/MySQL get native ALTERs (default recreate='auto'). A native
    # ALTER ... ADD COLUMN won't auto-create the Postgres enum TYPE, so create it first
    # (a no-op on MySQL/SQLite, which store the enum inline / as a CHECK).
    _reversibility.create(op.get_bind(), checkfirst=True)
    with op.batch_alter_table('architecturedecision') as batch_op:
        batch_op.add_column(sa.Column('alternatives', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('reversibility', _reversibility, nullable=True))
        batch_op.add_column(sa.Column('decision_owner_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('proposed_by_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('decide_by', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('rfc_url', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
        batch_op.create_foreign_key(
            'fk_adr_decision_owner', 'engineer', ['decision_owner_id'], ['id']
        )
        batch_op.create_foreign_key(
            'fk_adr_proposed_by', 'engineer', ['proposed_by_id'], ['id']
        )

    _decision_rule.create(op.get_bind(), checkfirst=True)
    with op.batch_alter_table('project') as batch_op:
        batch_op.add_column(
            sa.Column('decision_rule', _decision_rule, nullable=False, server_default='owner_decides')
        )
        batch_op.add_column(
            sa.Column('decision_sla_hours', sa.Integer(), nullable=False, server_default='72')
        )


def downgrade() -> None:
    with op.batch_alter_table('project') as batch_op:
        batch_op.drop_column('decision_sla_hours')
        batch_op.drop_column('decision_rule')
    _drop_pg_type('decisionrule')

    with op.batch_alter_table('architecturedecision') as batch_op:
        batch_op.drop_constraint('fk_adr_proposed_by', type_='foreignkey')
        batch_op.drop_constraint('fk_adr_decision_owner', type_='foreignkey')
        batch_op.drop_column('rfc_url')
        batch_op.drop_column('decide_by')
        batch_op.drop_column('proposed_by_id')
        batch_op.drop_column('decision_owner_id')
        batch_op.drop_column('reversibility')
        batch_op.drop_column('alternatives')
    _drop_pg_type('reversibility')

    _alter_enum_column(
        'architecturedecision', 'status', name='adrstatus',
        old_values=_adr_status_new, new_values=_adr_status_old, nullable=False,
    )

    op.drop_table('adrstakeholder')
    op.drop_index(op.f('ix_adrcomment_adr_id'), table_name='adrcomment')
    op.drop_table('adrcomment')
    _drop_pg_type('adrcommentkind')
