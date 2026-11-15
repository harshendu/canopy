"""mirrored-project clearances and outbound notifications

Phase 3 of docs/AGENT_EXECUTION.md (§15, §17): `task.clearance_status` / `clearance_at` (the move
canopy cleared on a mirrored ticket, until its tracker shows it), `outboundwebhook` (webhooks a
team points at its runner or Slack) and `outboxmessage` (the transactional outbox the worker
drains). Additive only: two nullable columns through `batch_alter_table` (a native ALTER on the
server databases) and two new tables.

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-11-15 13:30:00
"""

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision = "f4a5b6c7d8e9"
down_revision = "e3f4a5b6c7d8"
branch_labels = None
depends_on = None

_STR = sqlmodel.sql.sqltypes.AutoString


def upgrade() -> None:
    with op.batch_alter_table("task") as batch:
        batch.add_column(sa.Column("clearance_status", _STR(), nullable=True))
        batch.add_column(sa.Column("clearance_at", sa.DateTime(), nullable=True))

    op.create_table(
        "outboundwebhook",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scope_level", _STR(), nullable=False),
        sa.Column("scope_id", sa.Integer(), nullable=False),
        sa.Column("name", _STR(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("format", _STR(), nullable=False),
        sa.Column("events", sa.JSON(), nullable=True),
        sa.Column("secret_encrypted", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("last_delivery_at", sa.DateTime(), nullable=True),
        sa.Column("last_status", _STR(), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_outboundwebhook_scope_id"), "outboundwebhook", ["scope_id"],
                    unique=False)

    op.create_table(
        "outboxmessage",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("channel", _STR(), nullable=False),
        sa.Column("event", _STR(), nullable=False),
        sa.Column("webhook_id", sa.Integer(), nullable=True),
        sa.Column("connection_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("recipient", _STR(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("dedupe_key", _STR(), nullable=True),
        sa.Column("status", _STR(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("channel", "dedupe_key", "next_attempt_at", "project_id", "status", "task_id",
                   "webhook_id"):
        op.create_index(op.f(f"ix_outboxmessage_{column}"), "outboxmessage", [column],
                        unique=False)


def downgrade() -> None:
    # Dropping a table drops its indexes (dropping an FK-backing index first fails on MySQL).
    op.drop_table("outboxmessage")
    op.drop_table("outboundwebhook")
    with op.batch_alter_table("task") as batch:
        batch.drop_column("clearance_at")
        batch.drop_column("clearance_status")
