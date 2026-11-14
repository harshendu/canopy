"""work tracking: status categories + ownership, board workflows, native task keys

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-11-15 09:00:00

The status model behind native tracking and the Kanban board (USER_FLOWS §C9):

- `task.status_category` (todo | in_progress | done | cancelled — what every metric reads),
  `task.status_owner` ("canopy" or the provider key of the tracker that owns the status),
  `task.board_rank` (card order; 0 = unranked) and `task.key` (a human key);
- `taskstatushistory.to_category` (stamped at write time) and `.source`
  (canopy | sync | backfill);
- `project.tracking_mode` (native | mirrored), `project.next_task_number` and
  `project.task_key_prefix` (native keys `<prefix>-<n>`);
- `workflow` + `workflowstatus`: a team's (or a team-less project's) ordered board columns.

All new closed sets are plain VARCHAR (no native enum type). Every NOT NULL add carries a
server default so it backfills on Postgres/MySQL. Additive columns go through
`batch_alter_table` with the default recreate='auto'.

Data backfill (portable Core statements, no app imports — the heuristic is copied here):
1. categories on existing statuses and history rows, from the status name;
2. tasks with a Jira `externalref` become Jira-owned and take the Jira key;
3. projects reached by Jira (a Jira-owned task, a `jiralink` target, a Jira `externalref`
   project, or a Jira connection's `config.project_id`) become `mirrored`, the rest `native`;
4. canopy-owned leaf tasks with no status get one from their progress (Done at 100%, In
   Progress when started, else To Do) so the board is meaningful from day one;
5. every task without a key gets a native `<project key>-<n>` key (skipping any in use).
"""

import json

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision = "d6e7f8a9b0c1"
down_revision = "c5d6e7f8a9b0"
branch_labels = None
depends_on = None

_DONE = {
    "done", "closed", "resolved", "complete", "completed", "shipped", "deployed", "released",
    "live", "merged", "accepted",
}
_CANCELLED = {
    "cancelled", "canceled", "won't do", "wont do", "won't fix", "wontfix", "duplicate",
    "rejected", "declined", "abandoned", "dropped", "obsolete",
}
_TODO = {
    "to do", "todo", "backlog", "open", "new", "triage", "ready", "ready for dev",
    "ready for development", "selected for development", "planned", "not started", "icebox",
    "unstarted", "reopened",
}


def _text(column: sa.ColumnElement) -> sa.ColumnElement:
    """`provider` is a native enum on Postgres: compare it as text (a VARCHAR bind against an
    enum column has no `=` operator there)."""
    return sa.cast(column, sa.String)


def _category(name: str | None) -> str | None:
    if name is None or not str(name).strip():
        return None
    key = str(name).strip().casefold()
    if key in _DONE:
        return "done"
    if key in _CANCELLED:
        return "cancelled"
    if key in _TODO:
        return "todo"
    return "in_progress"


def upgrade() -> None:
    with op.batch_alter_table("project") as batch:
        batch.add_column(
            sa.Column(
                "tracking_mode",
                sqlmodel.sql.sqltypes.AutoString(),
                nullable=False,
                server_default="native",
            )
        )
        batch.add_column(
            sa.Column("next_task_number", sa.Integer(), nullable=False, server_default="1")
        )
        batch.add_column(
            sa.Column("task_key_prefix", sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )
    with op.batch_alter_table("task") as batch:
        batch.add_column(
            sa.Column("status_category", sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )
        batch.add_column(
            sa.Column(
                "status_owner",
                sqlmodel.sql.sqltypes.AutoString(),
                nullable=False,
                server_default="canopy",
            )
        )
        batch.add_column(
            sa.Column("board_rank", sa.BigInteger(), nullable=False, server_default="0")
        )
        batch.add_column(sa.Column("key", sqlmodel.sql.sqltypes.AutoString(), nullable=True))
        batch.create_index(batch.f("ix_task_key"), ["key"])
    with op.batch_alter_table("taskstatushistory") as batch:
        batch.add_column(
            sa.Column("to_category", sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )
        batch.add_column(
            sa.Column(
                "source",
                sqlmodel.sql.sqltypes.AutoString(),
                nullable=False,
                server_default="sync",
            )
        )

    op.create_table(
        "workflow",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("wip_enforcement", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.ForeignKeyConstraint(["team_id"], ["team.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_workflow_team_id"), "workflow", ["team_id"])
    op.create_index(op.f("ix_workflow_project_id"), "workflow", ["project_id"])
    op.create_table(
        "workflowstatus",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("workflow_id", sa.Integer(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("category", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("wip_limit", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflow.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workflow_id", "name", name="uq_workflowstatus_name"),
    )
    op.create_index(op.f("ix_workflowstatus_workflow_id"), "workflowstatus", ["workflow_id"])

    _backfill()


def _backfill() -> None:
    bind = op.get_bind()
    project = sa.table(
        "project",
        sa.column("id", sa.Integer),
        sa.column("key", sa.String),
        sa.column("tracking_mode", sa.String),
        sa.column("next_task_number", sa.Integer),
    )
    task = sa.table(
        "task",
        sa.column("id", sa.Integer),
        sa.column("project_id", sa.Integer),
        sa.column("type", sa.String),
        sa.column("status", sa.String),
        sa.column("status_category", sa.String),
        sa.column("status_owner", sa.String),
        sa.column("percent_complete", sa.Float),
        sa.column("key", sa.String),
    )
    history = sa.table(
        "taskstatushistory",
        sa.column("id", sa.Integer),
        sa.column("to_status", sa.String),
        sa.column("to_category", sa.String),
    )
    externalref = sa.table(
        "externalref",
        sa.column("provider", sa.String),
        sa.column("external_key", sa.String),
        sa.column("external_id", sa.String),
        sa.column("entity_type", sa.String),
        sa.column("entity_id", sa.Integer),
    )
    jiralink = sa.table(
        "jiralink", sa.column("target_type", sa.String), sa.column("target_id", sa.Integer)
    )
    connection = sa.table(
        "connection", sa.column("provider", sa.String), sa.column("config", sa.JSON)
    )

    # 1. categories on history rows (grouped by status name)
    names = bind.execute(sa.select(history.c.to_status).distinct()).scalars().all()
    for name in names:
        category = _category(name)
        if category is not None:
            bind.execute(
                history.update()
                .where(history.c.to_status == name)
                .values(to_category=category)
            )

    # 2. Jira-owned tasks + their keys
    refs = bind.execute(
        sa.select(externalref.c.entity_id, externalref.c.external_key, externalref.c.external_id)
        .where(externalref.c.entity_type == "task")
        .where(_text(externalref.c.provider) == "jira")
    ).all()
    jira_tasks: set[int] = set()
    for entity_id, external_key, external_id in refs:
        jira_tasks.add(int(entity_id))
        bind.execute(
            task.update()
            .where(task.c.id == entity_id)
            .values(status_owner="jira", key=external_key or external_id)
        )

    # 3. mirrored projects
    rows = bind.execute(sa.select(task.c.id, task.c.project_id)).all()
    mirrored = {int(pid) for tid, pid in rows if int(tid) in jira_tasks}
    mirrored |= {
        int(t)
        for (t,) in bind.execute(
            sa.select(jiralink.c.target_id).where(jiralink.c.target_type == "project")
        ).all()
    }
    mirrored |= {
        int(e)
        for (e,) in bind.execute(
            sa.select(externalref.c.entity_id)
            .where(externalref.c.entity_type == "project")
            .where(_text(externalref.c.provider) == "jira")
        ).all()
    }
    for (config,) in bind.execute(
        sa.select(connection.c.config).where(_text(connection.c.provider) == "jira")
    ).all():
        data = json.loads(config) if isinstance(config, str) else (config or {})
        try:
            mirrored.add(int(data.get("project_id")))
        except (TypeError, ValueError):
            continue
    if mirrored:
        bind.execute(
            project.update()
            .where(project.c.id.in_(sorted(mirrored)))
            .values(tracking_mode="mirrored")
        )

    # 4 + categories on current statuses
    tasks = bind.execute(
        sa.select(
            task.c.id, task.c.type, task.c.status, task.c.status_owner, task.c.percent_complete
        )
    ).all()
    for tid, ttype, status, owner, percent in tasks:
        values: dict[str, object] = {}
        if status is None and owner == "canopy" and ttype != "summary":
            pct = float(percent or 0.0)
            status = "Done" if pct >= 100 else "In Progress" if pct > 0 else "To Do"
            values["status"] = status
        category = _category(status)
        if category is not None:
            values["status_category"] = category
        if values:
            bind.execute(task.update().where(task.c.id == tid).values(**values))

    # 5. native keys
    projects = bind.execute(sa.select(project.c.id, project.c.key)).all()
    for pid, pkey in projects:
        prows = bind.execute(
            sa.select(task.c.id, task.c.key).where(task.c.project_id == pid).order_by(task.c.id)
        ).all()
        in_use = {k for _, k in prows if k}
        number = 1
        for tid, key in prows:
            if key:
                continue
            while f"{pkey}-{number}" in in_use:
                number += 1
            new_key = f"{pkey}-{number}"
            in_use.add(new_key)
            number += 1
            bind.execute(task.update().where(task.c.id == tid).values(key=new_key))
        bind.execute(
            project.update().where(project.c.id == pid).values(next_task_number=number)
        )


def downgrade() -> None:
    # drop_table takes its indexes with it; dropping an FK-backing index first fails on MySQL.
    op.drop_table("workflowstatus")
    op.drop_table("workflow")
    with op.batch_alter_table("taskstatushistory") as batch:
        batch.drop_column("source")
        batch.drop_column("to_category")
    with op.batch_alter_table("task") as batch:
        batch.drop_index(batch.f("ix_task_key"))
        batch.drop_column("key")
        batch.drop_column("board_rank")
        batch.drop_column("status_owner")
        batch.drop_column("status_category")
    with op.batch_alter_table("project") as batch:
        batch.drop_column("task_key_prefix")
        batch.drop_column("next_task_number")
        batch.drop_column("tracking_mode")
