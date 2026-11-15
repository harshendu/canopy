"""stage policy and delivery rules

Phase 2 of docs/AGENT_EXECUTION.md (§9.1, §10, §11.1): `stagepolicy` (one row per workflow column
that carries a policy, keyed by column name on its owner) and `deliveryrule` (team working
agreements and Definition-of-Done items, workspace → team → project). New tables only; the
unique keys rest on NOT NULL columns (the workspace's rules use scope_id 0).

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-11-15 13:00:00
"""

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision = "e3f4a5b6c7d8"
down_revision = "d2e3f4a5b6c7"
branch_labels = None
depends_on = None

_STR = sqlmodel.sql.sqltypes.AutoString


def upgrade() -> None:
    op.create_table(
        "deliveryrule",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scope_level", _STR(), nullable=False),
        sa.Column("scope_id", sa.Integer(), nullable=False),
        sa.Column("key", _STR(), nullable=False),
        sa.Column("title", _STR(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("kind", _STR(), nullable=False),
        sa.Column("roles", sa.JSON(), nullable=True),
        sa.Column("selector", sa.JSON(), nullable=True),
        sa.Column("enforcement", _STR(), nullable=False),
        sa.Column("locked", sa.Boolean(), nullable=False),
        sa.Column("disabled", sa.Boolean(), nullable=False),
        sa.Column("source_adr_id", sa.Integer(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scope_level", "scope_id", "key", name="uq_deliveryrule_key"),
    )
    for column in ("scope_id", "scope_level"):
        op.create_index(op.f(f"ix_deliveryrule_{column}"), "deliveryrule", [column],
                        unique=False)
    op.create_table(
        "stagepolicy",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_type", _STR(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("status_name", _STR(), nullable=False),
        sa.Column("worked_by", _STR(), nullable=True),
        sa.Column("artifact", _STR(), nullable=True),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("pulls_from", sa.JSON(), nullable=True),
        sa.Column("enter", sa.JSON(), nullable=True),
        sa.Column("on_changes", _STR(), nullable=True),
        sa.Column("decision", sa.JSON(), nullable=True),
        sa.Column("checkpoints", sa.JSON(), nullable=True),
        sa.Column("lease_minutes", sa.Integer(), nullable=True),
        sa.Column("max_attempts", sa.Integer(), nullable=True),
        sa.Column("max_rework", sa.Integer(), nullable=True),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_type", "owner_id", "status_name",
                            name="uq_stagepolicy_column"),
    )
    op.create_index(op.f("ix_stagepolicy_owner_id"), "stagepolicy", ["owner_id"], unique=False)


def downgrade() -> None:
    # Dropping a table drops its indexes (dropping an FK-backing index first fails on MySQL).
    op.drop_table("stagepolicy")
    op.drop_table("deliveryrule")
