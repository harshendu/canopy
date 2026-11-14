"""tracker bindings, engineer identities, connection-scoped external refs, neutral drafts

Revision ID: a9b0c1d2e3f4
Revises: f8a9b0c1d2e3
Create Date: 2026-11-16 10:00:00

The pluggable work-tracker layer (USER_FLOWS §J0):

- `trackerbinding`: what a connection feeds — a canopy project (or initiative) bound to a
  scope in the tracker (a whole tracker project, a subtree — a "tracker link" — or a query),
  owning its watermark, type/field mapping, status map and backfill cursor;
- `engineeridentity`: an engineer's account in one tracker (`Engineer.jira_account_id`
  generalised), so assignees from any tracker land on the same person;
- `externalref.connection_id` (two sites of one provider can share ids; the unique key now
  includes it) and `.detached_at` (a project stopped mirroring the tracker — kept as history);
- `drafttask.external_provider/_id/_key` + `.task_id`: a reviewed draft is finalised into any
  tracker, or into native canopy tasks.

Data copy (portable Core statements, no app imports), nothing removed — the legacy columns
(`connection.config.project_id`, `jiralink`, `engineer.jira_account_id`,
`drafttask.jira_*`) stay readable for one release:
1. each Jira connection's `config.project_id` becomes a project binding (scope = its Jira
   project key / board / JQL, mapping = its epic/story types and story-point field, the
   connection's watermark carried over so the next incremental sync continues);
2. each `jiralink` becomes a subtree binding;
3. each `engineer.jira_account_id` becomes a Jira identity;
4. refs of a provider with exactly one connection are stamped with it (others stay NULL and
   keep matching any connection, see `app/services/mapping.py`);
5. pushed draft tasks copy their Jira id/key into the neutral columns.
"""

import json
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision = "a9b0c1d2e3f4"
down_revision = "f8a9b0c1d2e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trackerbinding",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("connection_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("target_type", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("scope_kind", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("scope", sa.JSON(), nullable=True),
        sa.Column("mapping", sa.JSON(), nullable=True),
        sa.Column("status_map", sa.JSON(), nullable=True),
        sa.Column("sync_iterations", sa.Boolean(), nullable=False),
        sa.Column("watermark", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("backfill_cursor", sa.Integer(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("detached_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["connection_id"], ["connection.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_trackerbinding_connection_id"), "trackerbinding", ["connection_id"]
    )
    op.create_index(op.f("ix_trackerbinding_provider"), "trackerbinding", ["provider"])
    op.create_index(op.f("ix_trackerbinding_target_type"), "trackerbinding", ["target_type"])
    op.create_index(op.f("ix_trackerbinding_target_id"), "trackerbinding", ["target_id"])

    op.create_table(
        "engineeridentity",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("engineer_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("external_account_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("display_name", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.ForeignKeyConstraint(["engineer_id"], ["engineer.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "external_account_id", name="uq_engineer_identity"),
    )
    op.create_index(
        op.f("ix_engineeridentity_engineer_id"), "engineeridentity", ["engineer_id"]
    )

    with op.batch_alter_table("externalref") as batch:
        batch.add_column(sa.Column("connection_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("detached_at", sa.DateTime(), nullable=True))
        batch.drop_constraint("uq_external_ref", type_="unique")
        batch.create_unique_constraint(
            "uq_external_ref", ["provider", "external_id", "entity_type", "connection_id"]
        )
        batch.create_foreign_key(
            "fk_externalref_connection_id_connection", "connection", ["connection_id"], ["id"]
        )

    with op.batch_alter_table("drafttask") as batch:
        batch.add_column(
            sa.Column("external_provider", sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )
        batch.add_column(
            sa.Column("external_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )
        batch.add_column(
            sa.Column("external_key", sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )
        batch.add_column(sa.Column("task_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_drafttask_task_id_task", "task", ["task_id"], ["id"])

    _copy_legacy()


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)  # naive UTC, like `models/base.py:utcnow`


def _json(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


def _legacy_mapping(config: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if config.get("epic_issue_type"):
        out["epic_types"] = [str(config["epic_issue_type"])]
    if config.get("story_issue_type"):
        out["item_type"] = str(config["story_issue_type"])
    if config.get("story_point_field"):
        out["estimate_field"] = str(config["story_point_field"])
    return out


def _copy_legacy() -> None:
    bind = op.get_bind()
    now = _now()
    connection = sa.table(
        "connection",
        sa.column("id", sa.Integer),
        sa.column("provider", sa.String),
        sa.column("config", sa.JSON),
        sa.column("watermark", sa.String),
        sa.column("active", sa.Boolean),
    )
    project = sa.table("project", sa.column("id", sa.Integer))
    binding = sa.table(
        "trackerbinding",
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
        sa.column("connection_id", sa.Integer),
        sa.column("provider", sa.String),
        sa.column("target_type", sa.String),
        sa.column("target_id", sa.Integer),
        sa.column("scope_kind", sa.String),
        sa.column("scope", sa.JSON),
        sa.column("mapping", sa.JSON),
        sa.column("status_map", sa.JSON),
        sa.column("sync_iterations", sa.Boolean),
        sa.column("watermark", sa.String),
        sa.column("active", sa.Boolean),
        sa.column("last_synced_at", sa.DateTime),
    )
    jiralink = sa.table(
        "jiralink",
        sa.column("connection_id", sa.Integer),
        sa.column("jira_issue_id", sa.String),
        sa.column("jira_key", sa.String),
        sa.column("jira_issue_type", sa.String),
        sa.column("target_type", sa.String),
        sa.column("target_id", sa.Integer),
        sa.column("last_synced_at", sa.DateTime),
    )
    engineer = sa.table(
        "engineer",
        sa.column("id", sa.Integer),
        sa.column("name", sa.String),
        sa.column("jira_account_id", sa.String),
    )
    identity = sa.table(
        "engineeridentity",
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
        sa.column("engineer_id", sa.Integer),
        sa.column("provider", sa.String),
        sa.column("external_account_id", sa.String),
        sa.column("display_name", sa.String),
    )
    externalref = sa.table(
        "externalref",
        sa.column("provider", sa.String),
        sa.column("connection_id", sa.Integer),
    )
    drafttask = sa.table(
        "drafttask",
        sa.column("id", sa.Integer),
        sa.column("jira_issue_id", sa.String),
        sa.column("jira_key", sa.String),
        sa.column("external_provider", sa.String),
        sa.column("external_id", sa.String),
        sa.column("external_key", sa.String),
    )

    connections = bind.execute(
        sa.select(
            connection.c.id,
            connection.c.provider,
            connection.c.config,
            connection.c.watermark,
            connection.c.active,
        )
    ).all()
    project_ids = {int(p) for (p,) in bind.execute(sa.select(project.c.id)).all()}

    # 1. legacy `config.project_id` → a project binding (Jira was the only tracker)
    for cid, provider, raw_config, watermark, active in connections:
        if str(provider) != "jira":
            continue
        config = _json(raw_config)
        try:
            target = int(config.get("project_id"))
        except (TypeError, ValueError):
            continue
        if target not in project_ids:
            continue
        scope: dict[str, Any] = {}
        if config.get("jira_project_key"):
            scope["project_key"] = str(config["jira_project_key"])
        for key in ("board_id", "jql"):
            if config.get(key):
                scope[key] = config[key]
        bind.execute(
            binding.insert().values(
                created_at=now,
                updated_at=now,
                connection_id=cid,
                provider="jira",
                target_type="project",
                target_id=target,
                scope_kind="project",
                scope=scope,
                mapping=_legacy_mapping(config),
                status_map=[],
                sync_iterations=bool(config.get("board_id")),
                watermark=watermark,
                active=bool(active),
                last_synced_at=None,
            )
        )

    # 2. jira links → subtree bindings
    for cid, issue_id, key, issue_type, target_type, target_id, synced in bind.execute(
        sa.select(
            jiralink.c.connection_id,
            jiralink.c.jira_issue_id,
            jiralink.c.jira_key,
            jiralink.c.jira_issue_type,
            jiralink.c.target_type,
            jiralink.c.target_id,
            jiralink.c.last_synced_at,
        )
    ).all():
        bind.execute(
            binding.insert().values(
                created_at=now,
                updated_at=now,
                connection_id=cid,
                provider="jira",
                target_type=target_type,
                target_id=target_id,
                scope_kind="subtree",
                scope={"root_id": str(issue_id), "root_key": key, "root_type": issue_type},
                mapping={},
                status_map=[],
                sync_iterations=False,
                watermark=None,
                active=True,
                last_synced_at=synced,
            )
        )

    # 3. engineer Jira accounts → identities (first engineer wins a shared account id)
    seen: set[str] = set()
    for eid, name, account in bind.execute(
        sa.select(engineer.c.id, engineer.c.name, engineer.c.jira_account_id)
        .where(engineer.c.jira_account_id.is_not(None))
        .order_by(engineer.c.id)
    ).all():
        if not account or account in seen:
            continue
        seen.add(account)
        bind.execute(
            identity.insert().values(
                created_at=now,
                updated_at=now,
                engineer_id=eid,
                provider="jira",
                external_account_id=account,
                display_name=name,
            )
        )

    # 4. refs of a provider with exactly one connection name it
    by_provider: dict[str, list[int]] = {}
    for cid, provider, _config, _watermark, _active in connections:
        by_provider.setdefault(str(provider), []).append(int(cid))
    for provider, ids in by_provider.items():
        if len(ids) == 1:
            bind.execute(
                externalref.update()
                .where(externalref.c.provider == provider)
                .where(externalref.c.connection_id.is_(None))
                .values(connection_id=ids[0])
            )

    # 5. pushed drafts → neutral columns
    bind.execute(
        drafttask.update()
        .where(drafttask.c.jira_issue_id.is_not(None))
        .values(
            external_provider="jira",
            external_id=drafttask.c.jira_issue_id,
            external_key=drafttask.c.jira_key,
        )
    )


def downgrade() -> None:
    """Drops the new tables/columns (the legacy columns were kept, so nothing is lost that the
    previous release reads). Restoring the narrower `uq_external_ref` fails if two connections
    now hold the same external id — remove those refs first."""
    with op.batch_alter_table("drafttask") as batch:
        batch.drop_constraint("fk_drafttask_task_id_task", type_="foreignkey")
        batch.drop_column("task_id")
        batch.drop_column("external_key")
        batch.drop_column("external_id")
        batch.drop_column("external_provider")
    with op.batch_alter_table("externalref") as batch:
        batch.drop_constraint("fk_externalref_connection_id_connection", type_="foreignkey")
        batch.drop_constraint("uq_external_ref", type_="unique")
        batch.create_unique_constraint(
            "uq_external_ref", ["provider", "external_id", "entity_type"]
        )
        batch.drop_column("detached_at")
        batch.drop_column("connection_id")
    # drop_table takes its indexes with it (dropping an FK-backing index first fails on MySQL).
    op.drop_table("engineeridentity")
    op.drop_table("trackerbinding")
