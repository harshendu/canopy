"""teams, pods, team members; initiative.team_id; project.pod_id + owner_engineer_id

Revision ID: b4c1d2e3f5a6
Revises: 0ecda3c02d48
Create Date: 2026-10-09 09:00:00
"""
import sqlalchemy as sa
import sqlmodel
from alembic import op

revision = "b4c1d2e3f5a6"
down_revision = "0ecda3c02d48"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "team",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_team_key"), "team", ["key"], unique=True)
    op.create_table(
        "pod",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(["team_id"], ["team.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_pod_team_id"), "pod", ["team_id"], unique=False)
    op.create_table(
        "teammember",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("engineer_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.Enum("director", "manager", name="teamrole"), nullable=False),
        sa.ForeignKeyConstraint(["engineer_id"], ["engineer.id"]),
        sa.ForeignKeyConstraint(["team_id"], ["team.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_teammember_engineer_id"), "teammember", ["engineer_id"])
    op.create_index(op.f("ix_teammember_team_id"), "teammember", ["team_id"])
    # New nullable FK columns — batch with the default recreate='auto' (SQLite rebuilds;
    # Postgres/MySQL get a native ALTER), per the portability rules.
    with op.batch_alter_table("initiative") as batch:
        batch.add_column(sa.Column("team_id", sa.Integer(), nullable=True))
        batch.create_index(batch.f("ix_initiative_team_id"), ["team_id"])
        batch.create_foreign_key("fk_initiative_team_id_team", "team", ["team_id"], ["id"])
    with op.batch_alter_table("project") as batch:
        batch.add_column(sa.Column("pod_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("owner_engineer_id", sa.Integer(), nullable=True))
        batch.create_index(batch.f("ix_project_pod_id"), ["pod_id"])
        batch.create_foreign_key("fk_project_pod_id_pod", "pod", ["pod_id"], ["id"])
        batch.create_foreign_key(
            "fk_project_owner_engineer_id_engineer", "engineer", ["owner_engineer_id"], ["id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("project") as batch:
        batch.drop_constraint("fk_project_owner_engineer_id_engineer", type_="foreignkey")
        batch.drop_constraint("fk_project_pod_id_pod", type_="foreignkey")
        batch.drop_index(batch.f("ix_project_pod_id"))
        batch.drop_column("owner_engineer_id")
        batch.drop_column("pod_id")
    with op.batch_alter_table("initiative") as batch:
        batch.drop_constraint("fk_initiative_team_id_team", type_="foreignkey")
        batch.drop_index(batch.f("ix_initiative_team_id"))
        batch.drop_column("team_id")
    op.drop_index(op.f("ix_teammember_team_id"), table_name="teammember")
    op.drop_index(op.f("ix_teammember_engineer_id"), table_name="teammember")
    op.drop_table("teammember")
    op.drop_index(op.f("ix_pod_team_id"), table_name="pod")
    op.drop_table("pod")
    op.drop_index(op.f("ix_team_key"), table_name="team")
    op.drop_table("team")
