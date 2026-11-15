"""agent work queue: claims, artifacts, gates, the work-event log, delegation and intake

Phase 1 of docs/AGENT_EXECUTION.md (§11.1, §11.2):

* new tables `workclaim`, `taskartifact`, `gate`, `workevent` and `taskcomponentlink`;
* `project.agent_intake` (off | on | paused, default off — nothing changes until a planner
  switches a project on);
* `task.delegation` / `delegated_by_user_id` / `delegated_at` / `active_claim_id` /
  `implements_adr_id` — plain integers, no FK (an FK on an existing table forces a SQLite
  rebuild; `active_claim_id` would also make a task <-> claim cycle).

Additive only. The NOT NULL column carries a server default so existing rows backfill;
`batch_alter_table` uses the default recreate='auto' (SQLite rebuilds, Postgres/MySQL ALTER).

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-11-15 07:15:00
"""

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision = "d2e3f4a5b6c7"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None

_STR = sqlmodel.sql.sqltypes.AutoString


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "taskcomponentlink",
        *_timestamps(),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("component_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["component_id"], ["architecturecomponent.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["task.id"]),
        sa.PrimaryKeyConstraint("task_id", "component_id"),
    )
    op.create_table(
        "workclaim",
        *_timestamps(),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("role", _STR(), nullable=False),
        sa.Column("stage", _STR(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("state", _STR(), nullable=False),
        sa.Column("outcome", _STR(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("agent_token_id", sa.Integer(), nullable=True),
        sa.Column("agent_label", _STR(), nullable=True),
        sa.Column("runner", _STR(), nullable=True),
        sa.Column("session_ref", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("claimed_at", sa.DateTime(), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=False),
        sa.Column("lease_minutes", sa.Integer(), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("end_reason", _STR(), nullable=True),
        sa.Column("progress_note", sa.Text(), nullable=True),
        sa.Column("branch", _STR(), nullable=True),
        sa.Column("pr_url", sa.Text(), nullable=True),
        sa.Column("usage", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["agent_token_id"], ["agent_token.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["task.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    for column in ("agent_token_id", "lease_expires_at", "state", "task_id", "user_id"):
        op.create_index(op.f(f"ix_workclaim_{column}"), "workclaim", [column], unique=False)
    op.create_table(
        "workevent",
        *_timestamps(),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.Column("kind", _STR(), nullable=False),
        sa.Column("actor_kind", _STR(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("agent_token_id", sa.Integer(), nullable=True),
        sa.Column("work_claim_id", sa.Integer(), nullable=True),
        sa.Column("gate_id", sa.Integer(), nullable=True),
        sa.Column("artifact_id", sa.Integer(), nullable=True),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["task.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("at", "gate_id", "kind", "project_id", "task_id", "work_claim_id"):
        op.create_index(op.f(f"ix_workevent_{column}"), "workevent", [column], unique=False)
    op.create_table(
        "taskartifact",
        *_timestamps(),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("kind", _STR(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("title", _STR(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("verdict", _STR(), nullable=True),
        sa.Column("head_sha", _STR(), nullable=True),
        sa.Column("author_kind", _STR(), nullable=False),
        sa.Column("author_user_id", sa.Integer(), nullable=True),
        sa.Column("work_claim_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["author_user_id"], ["app_user.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["task.id"]),
        sa.ForeignKeyConstraint(["work_claim_id"], ["workclaim.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "kind", "revision", name="uq_taskartifact_revision"),
    )
    for column in ("task_id", "work_claim_id"):
        op.create_index(op.f(f"ix_taskartifact_{column}"), "taskartifact", [column], unique=False)
    op.create_table(
        "gate",
        *_timestamps(),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("kind", _STR(), nullable=False),
        sa.Column("origin", _STR(), nullable=False),
        sa.Column("stage", _STR(), nullable=True),
        sa.Column("status", _STR(), nullable=False),
        sa.Column("title", _STR(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=True),
        sa.Column("options", sa.JSON(), nullable=True),
        sa.Column("allow_text", sa.Boolean(), nullable=False),
        sa.Column("allowed_decisions", sa.JSON(), nullable=True),
        sa.Column("reasons", sa.JSON(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("subject_artifact_id", sa.Integer(), nullable=True),
        sa.Column("requested_by_claim_id", sa.Integer(), nullable=True),
        sa.Column("requested_by_user_id", sa.Integer(), nullable=True),
        sa.Column("approvers", _STR(), nullable=False),
        sa.Column("approver_engineer_ids", sa.JSON(), nullable=True),
        sa.Column("exclude_requester", sa.Boolean(), nullable=False),
        sa.Column("satisfied_by", sa.JSON(), nullable=True),
        sa.Column("remind_at", sa.DateTime(), nullable=True),
        sa.Column("escalate_at", sa.DateTime(), nullable=True),
        sa.Column("escalation_level", sa.Integer(), nullable=False),
        sa.Column("on_approve", _STR(), nullable=True),
        sa.Column("on_changes", _STR(), nullable=True),
        sa.Column("on_reject", _STR(), nullable=True),
        sa.Column("decision", _STR(), nullable=True),
        sa.Column("decided_by_user_id", sa.Integer(), nullable=True),
        sa.Column("decided_by_label", _STR(), nullable=True),
        sa.Column("decided_via", _STR(), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("response_note", sa.Text(), nullable=True),
        sa.Column("response_data", sa.JSON(), nullable=True),
        sa.Column("routed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["decided_by_user_id"], ["app_user.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.ForeignKeyConstraint(["requested_by_claim_id"], ["workclaim.id"]),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["app_user.id"]),
        sa.ForeignKeyConstraint(["subject_artifact_id"], ["taskartifact.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["task.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("kind", "project_id", "status", "task_id"):
        op.create_index(op.f(f"ix_gate_{column}"), "gate", [column], unique=False)
    with op.batch_alter_table("project") as batch:
        batch.add_column(sa.Column("agent_intake", _STR(), nullable=False, server_default="off"))
    with op.batch_alter_table("task") as batch:
        batch.add_column(sa.Column("delegation", _STR(), nullable=True))
        batch.add_column(sa.Column("delegated_by_user_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("delegated_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("active_claim_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("implements_adr_id", sa.Integer(), nullable=True))
        batch.create_index(batch.f("ix_task_active_claim_id"), ["active_claim_id"], unique=False)
        batch.create_index(
            batch.f("ix_task_implements_adr_id"), ["implements_adr_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("task") as batch:
        batch.drop_index(batch.f("ix_task_implements_adr_id"))
        batch.drop_index(batch.f("ix_task_active_claim_id"))
        for name in (
            "implements_adr_id", "active_claim_id", "delegated_at", "delegated_by_user_id",
            "delegation",
        ):
            batch.drop_column(name)
    with op.batch_alter_table("project") as batch:
        batch.drop_column("agent_intake")
    # Dropping a table drops its indexes; dropping an FK-backing index first fails on MySQL.
    for table in ("gate", "taskartifact", "workevent", "workclaim", "taskcomponentlink"):
        op.drop_table(table)
