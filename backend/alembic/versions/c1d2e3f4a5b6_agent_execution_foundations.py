"""agent execution foundations: PR signals, status attribution, agent token scope

Phase 0 of docs/AGENT_EXECUTION.md (§11.2, §11.3, §18.2):

* `pullrequest` gains the review / check / merge state stage checks and gates will read.
* `taskstatushistory` records who made a canopy move (`actor_kind`) and under which work claim.
* `agent_token` gains its role / project scope, a concurrent-claim limit and `last_used_at`.

Every column is additive; NOT NULL ones carry a server default so existing rows backfill.
`batch_alter_table` with the default recreate='auto' (SQLite rebuilds; Postgres/MySQL get a
native ALTER). `work_claim_id` is a plain integer (no FK) on purpose — see the model.

Revision ID: c1d2e3f4a5b6
Revises: 2d3e4f5a6b7c
Create Date: 2026-11-15 06:40:00
"""

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision = "c1d2e3f4a5b6"
down_revision = "2d3e4f5a6b7c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_token") as batch:
        batch.add_column(sa.Column("roles", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("project_ids", sa.JSON(), nullable=True))
        batch.add_column(
            sa.Column("max_active_claims", sa.Integer(), nullable=False, server_default="1")
        )
        batch.add_column(sa.Column("last_used_at", sa.DateTime(), nullable=True))
    with op.batch_alter_table("pullrequest") as batch:
        batch.add_column(
            sa.Column("draft", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch.add_column(
            sa.Column("merged", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch.add_column(sa.Column("merged_at", sa.DateTime(), nullable=True))
        batch.add_column(
            sa.Column("merged_by", sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )
        batch.add_column(
            sa.Column("head_branch", sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )
        batch.add_column(sa.Column("head_sha", sqlmodel.sql.sqltypes.AutoString(), nullable=True))
        batch.add_column(
            sa.Column("review_decision", sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )
        batch.add_column(sa.Column("reviews", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("approved_by", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("checks", sa.JSON(), nullable=True))
        batch.add_column(
            sa.Column("checks_state", sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )
        batch.add_column(sa.Column("additions", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("deletions", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("changed_files", sa.Integer(), nullable=True))
    with op.batch_alter_table("taskstatushistory") as batch:
        batch.add_column(
            sa.Column("actor_kind", sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )
        batch.add_column(sa.Column("work_claim_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("taskstatushistory") as batch:
        batch.drop_column("work_claim_id")
        batch.drop_column("actor_kind")
    with op.batch_alter_table("pullrequest") as batch:
        for name in (
            "changed_files",
            "deletions",
            "additions",
            "checks_state",
            "checks",
            "approved_by",
            "reviews",
            "review_decision",
            "head_sha",
            "head_branch",
            "merged_by",
            "merged_at",
            "merged",
            "draft",
        ):
            batch.drop_column(name)
    with op.batch_alter_table("agent_token") as batch:
        batch.drop_column("last_used_at")
        batch.drop_column("max_active_claims")
        batch.drop_column("project_ids")
        batch.drop_column("roles")
