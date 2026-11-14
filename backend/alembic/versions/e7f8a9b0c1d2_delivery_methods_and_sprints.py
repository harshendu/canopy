"""delivery methods + sprints: team.delivery_method, sprint, tasksprinthistory, task.sprint_id

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
Create Date: 2026-11-15 10:00:00

A team chooses how it runs work across all its projects — kanban | sprint | both
(`team.delivery_method`, with `sprint_length_days` and `estimate_unit`). Sprints belong to a
team (optionally a pod), are canopy-owned or mirrored from a tracker (`sprint.owner`), and
`tasksprinthistory` records every membership move (commitment, scope change and carry-over are
computed from it). `task.sprint_id` is the membership; `task.story_points` the estimate.

Plain VARCHAR for the new closed sets; server defaults on every NOT NULL add; additive columns
through `batch_alter_table` (recreate='auto').

Data: the legacy `task.sprint` name (set by the Jira active-sprint sync) becomes a real sprint
for each (team, name) — owned by the tracker when its tasks are, active, dates left for the next
sync — and its tasks join it with a recorded move. Teams that had such sprints start on `both`
(so their sprint data stays visible); every other team starts on `kanban`. Tasks of team-less
projects keep the name only (there is no team to hold a sprint).
"""

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision = "e7f8a9b0c1d2"
down_revision = "d6e7f8a9b0c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("team") as batch:
        batch.add_column(
            sa.Column(
                "delivery_method",
                sqlmodel.sql.sqltypes.AutoString(),
                nullable=False,
                server_default="kanban",
            )
        )
        batch.add_column(
            sa.Column("sprint_length_days", sa.Integer(), nullable=False, server_default="14")
        )
        batch.add_column(
            sa.Column(
                "estimate_unit",
                sqlmodel.sql.sqltypes.AutoString(),
                nullable=False,
                server_default="points",
            )
        )

    op.create_table(
        "sprint",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("pod_id", sa.Integer(), nullable=True),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("goal", sa.Text(), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("state", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("owner", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("estimate_unit", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("committed", sa.Float(), nullable=True),
        sa.Column("completed", sa.Float(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["pod_id"], ["pod.id"]),
        sa.ForeignKeyConstraint(["team_id"], ["team.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sprint_team_id"), "sprint", ["team_id"])
    op.create_index(op.f("ix_sprint_pod_id"), "sprint", ["pod_id"])
    op.create_table(
        "tasksprinthistory",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("from_sprint_id", sa.Integer(), nullable=True),
        sa.Column("to_sprint_id", sa.Integer(), nullable=True),
        sa.Column("changed_at", sa.DateTime(), nullable=False),
        sa.Column("author", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("source", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(["from_sprint_id"], ["sprint.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["task.id"]),
        sa.ForeignKeyConstraint(["to_sprint_id"], ["sprint.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tasksprinthistory_task_id"), "tasksprinthistory", ["task_id"])
    op.create_index(
        op.f("ix_tasksprinthistory_changed_at"), "tasksprinthistory", ["changed_at"]
    )
    with op.batch_alter_table("task") as batch:
        batch.add_column(sa.Column("sprint_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("story_points", sa.Float(), nullable=True))
        batch.create_index(batch.f("ix_task_sprint_id"), ["sprint_id"])
        batch.create_foreign_key("fk_task_sprint_id_sprint", "sprint", ["sprint_id"], ["id"])

    _backfill()


def _backfill() -> None:
    bind = op.get_bind()
    team = sa.table("team", sa.column("id", sa.Integer), sa.column("delivery_method", sa.String))
    pod = sa.table("pod", sa.column("id", sa.Integer), sa.column("team_id", sa.Integer))
    initiative = sa.table(
        "initiative", sa.column("id", sa.Integer), sa.column("team_id", sa.Integer)
    )
    project = sa.table(
        "project",
        sa.column("id", sa.Integer),
        sa.column("pod_id", sa.Integer),
        sa.column("initiative_id", sa.Integer),
    )
    task = sa.table(
        "task",
        sa.column("id", sa.Integer),
        sa.column("project_id", sa.Integer),
        sa.column("sprint", sa.String),
        sa.column("sprint_id", sa.Integer),
        sa.column("status_owner", sa.String),
    )
    sprint = sa.table(
        "sprint",
        sa.column("id", sa.Integer),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
        sa.column("team_id", sa.Integer),
        sa.column("name", sa.String),
        sa.column("state", sa.String),
        sa.column("owner", sa.String),
    )
    history = sa.table(
        "tasksprinthistory",
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
        sa.column("task_id", sa.Integer),
        sa.column("from_sprint_id", sa.Integer),
        sa.column("to_sprint_id", sa.Integer),
        sa.column("changed_at", sa.DateTime),
        sa.column("source", sa.String),
    )

    pod_team = {int(p): t for p, t in bind.execute(sa.select(pod.c.id, pod.c.team_id)).all()}
    initiative_team = {
        int(i): t for i, t in bind.execute(sa.select(initiative.c.id, initiative.c.team_id)).all()
    }
    project_team: dict[int, int] = {}
    for pid, pod_id, initiative_id in bind.execute(
        sa.select(project.c.id, project.c.pod_id, project.c.initiative_id)
    ).all():
        team_id = pod_team.get(int(pod_id)) if pod_id is not None else None
        if team_id is None and initiative_id is not None:
            team_id = initiative_team.get(int(initiative_id))
        if team_id is not None:
            project_team[int(pid)] = int(team_id)

    rows = bind.execute(
        sa.select(task.c.id, task.c.project_id, task.c.sprint, task.c.status_owner).where(
            task.c.sprint.is_not(None)
        )
    ).all()
    now = sa.func.now() if bind.dialect.name != "sqlite" else sa.func.current_timestamp()
    created: dict[tuple[int, str], int] = {}
    teams_with_sprints: set[int] = set()
    for tid, pid, name, owner in rows:
        team_id = project_team.get(int(pid))
        if team_id is None or not str(name).strip():
            continue
        key = (team_id, str(name))
        if key not in created:
            bind.execute(
                sprint.insert().values(
                    created_at=now,
                    updated_at=now,
                    team_id=team_id,
                    name=str(name),
                    state="active",
                    owner=owner if owner and owner != "canopy" else "canopy",
                )
            )
            created[key] = int(
                bind.execute(
                    sa.select(sa.func.max(sprint.c.id)).where(
                        sprint.c.team_id == team_id, sprint.c.name == str(name)
                    )
                ).scalar_one()
            )
        sprint_id = created[key]
        teams_with_sprints.add(team_id)
        bind.execute(task.update().where(task.c.id == tid).values(sprint_id=sprint_id))
        bind.execute(
            history.insert().values(
                created_at=now,
                updated_at=now,
                task_id=tid,
                from_sprint_id=None,
                to_sprint_id=sprint_id,
                changed_at=now,
                source="sync",
            )
        )
    if teams_with_sprints:
        bind.execute(
            team.update()
            .where(team.c.id.in_(sorted(teams_with_sprints)))
            .values(delivery_method="both")
        )


def downgrade() -> None:
    with op.batch_alter_table("task") as batch:
        batch.drop_constraint("fk_task_sprint_id_sprint", type_="foreignkey")
        batch.drop_index(batch.f("ix_task_sprint_id"))
        batch.drop_column("story_points")
        batch.drop_column("sprint_id")
    # drop_table takes its indexes with it (dropping an FK-backing index first fails on MySQL).
    op.drop_table("tasksprinthistory")
    op.drop_table("sprint")
    with op.batch_alter_table("team") as batch:
        batch.drop_column("estimate_unit")
        batch.drop_column("sprint_length_days")
        batch.drop_column("delivery_method")
