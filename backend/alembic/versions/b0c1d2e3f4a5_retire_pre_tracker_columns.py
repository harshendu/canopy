"""retire pre-tracker storage: jiralink, drafttask.jira_*, engineer.jira_account_id, task.sprint

Revision ID: b0c1d2e3f4a5
Revises: a9b0c1d2e3f4
Create Date: 2026-11-21 09:00:00

The tracker layer (USER_FLOWS §J0) has carried these for one release beside their replacements;
this revision retires them (Phase 6 of the pluggable-tracking plan):

- `jiralink` → subtree `trackerbinding` rows (tracker links);
- `drafttask.jira_issue_id` / `jira_key` → `drafttask.external_provider/_id/_key`;
- `engineer.jira_account_id` → `engineeridentity`;
- `task.sprint` (a sprint's name) → `task.sprint_id` (revision e7f8a9b0c1d2 turned every name a
  team could hold into a sprint row); the name a tracker's active sprint left on a team-less
  project's tasks goes with it — a team-less project runs Kanban, and the tracker still has it;
- a tracker connection's `config.project_id` (the pre-binding way to say which project it
  feeds, read through an in-memory fallback) → a project `trackerbinding`.

Nothing canopy owns is lost: before dropping anything, rows the earlier copy (a9b0c1d2e3f4) or the
deprecation window's dual writes didn't carry over are copied now — a link without a binding,
a pushed draft task without neutral ids, an account id without an identity, and a connection
that still binds a project only through its config (it gets a project binding when the project
exists and isn't bound already; the project is mirrored). `project_id` is then removed from every
tracker connection's config, since nothing reads it any more. The downgrade restores the columns
and table from their replacements.
"""

import json
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision = "b0c1d2e3f4a5"
down_revision = "a9b0c1d2e3f4"
branch_labels = None
depends_on = None

_TRACKERS = ("jira", "linear", "generic")


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)  # naive UTC, like `models/base.py:utcnow`


def _json(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


def _tables() -> dict[str, sa.TableClause]:
    return {
        "connection": sa.table(
            "connection",
            sa.column("id", sa.Integer),
            sa.column("provider", sa.String),
            sa.column("config", sa.JSON),
            sa.column("watermark", sa.String),
        ),
        "project": sa.table(
            "project", sa.column("id", sa.Integer), sa.column("tracking_mode", sa.String)
        ),
        "binding": sa.table(
            "trackerbinding",
            sa.column("id", sa.Integer),
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
        ),
        "jiralink": sa.table(
            "jiralink",
            sa.column("created_at", sa.DateTime),
            sa.column("updated_at", sa.DateTime),
            sa.column("connection_id", sa.Integer),
            sa.column("jira_issue_id", sa.String),
            sa.column("jira_key", sa.String),
            sa.column("jira_issue_type", sa.String),
            sa.column("target_type", sa.String),
            sa.column("target_id", sa.Integer),
            sa.column("last_synced_at", sa.DateTime),
        ),
        "engineer": sa.table(
            "engineer",
            sa.column("id", sa.Integer),
            sa.column("name", sa.String),
            sa.column("jira_account_id", sa.String),
        ),
        "identity": sa.table(
            "engineeridentity",
            sa.column("created_at", sa.DateTime),
            sa.column("updated_at", sa.DateTime),
            sa.column("engineer_id", sa.Integer),
            sa.column("provider", sa.String),
            sa.column("external_account_id", sa.String),
            sa.column("display_name", sa.String),
        ),
        "task": sa.table(
            "task", sa.column("id", sa.Integer), sa.column("sprint", sa.String),
            sa.column("sprint_id", sa.Integer),
        ),
        "sprint": sa.table("sprint", sa.column("id", sa.Integer), sa.column("name", sa.String)),
        "drafttask": sa.table(
            "drafttask",
            sa.column("id", sa.Integer),
            sa.column("jira_issue_id", sa.String),
            sa.column("jira_key", sa.String),
            sa.column("external_provider", sa.String),
            sa.column("external_id", sa.String),
            sa.column("external_key", sa.String),
        ),
    }


def _config_scope(config: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    if config.get("jira_project_key"):
        values["project_key"] = str(config["jira_project_key"])
    for key in ("project_key", "team_key", "board_id", "jql"):
        if config.get(key) and key not in values:
            values[key] = config[key]
    return values


def _config_mapping(config: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if config.get("epic_issue_type"):
        out["epic_types"] = [str(config["epic_issue_type"])]
    if config.get("story_issue_type"):
        out["item_type"] = str(config["story_issue_type"])
    if config.get("story_point_field"):
        out["estimate_field"] = str(config["story_point_field"])
    return out


def _copy_stragglers() -> None:
    bind = op.get_bind()
    t = _tables()
    now = _now()
    binding, connection, project = t["binding"], t["connection"], t["project"]

    bindings = bind.execute(
        sa.select(
            binding.c.connection_id,
            binding.c.target_type,
            binding.c.target_id,
            binding.c.scope_kind,
            binding.c.scope,
            binding.c.active,
        )
    ).all()
    subtree_roots = {
        (int(cid), str(_json(scope).get("root_id")))
        for cid, _tt, _ti, kind, scope, _active in bindings
        if kind == "subtree"
    }

    # 1. Jira links without a subtree binding.
    for cid, issue_id, key, issue_type, target_type, target_id, synced in bind.execute(
        sa.select(
            t["jiralink"].c.connection_id,
            t["jiralink"].c.jira_issue_id,
            t["jiralink"].c.jira_key,
            t["jiralink"].c.jira_issue_type,
            t["jiralink"].c.target_type,
            t["jiralink"].c.target_id,
            t["jiralink"].c.last_synced_at,
        )
    ).all():
        if (int(cid), str(issue_id)) in subtree_roots:
            continue
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
                active=True,
                last_synced_at=synced,
            )
        )
        subtree_roots.add((int(cid), str(issue_id)))

    # 2. Pushed draft tasks without neutral ids.
    drafttask = t["drafttask"]
    bind.execute(
        drafttask.update()
        .where(drafttask.c.jira_issue_id.is_not(None))
        .where(drafttask.c.external_id.is_(None))
        .values(
            external_provider="jira",
            external_id=drafttask.c.jira_issue_id,
            external_key=drafttask.c.jira_key,
        )
    )

    # 3. Jira account ids without an identity (an account id belongs to one engineer).
    identity = t["identity"]
    known = {
        str(a)
        for (a,) in bind.execute(
            sa.select(identity.c.external_account_id).where(identity.c.provider == "jira")
        ).all()
    }
    for eid, name, account in bind.execute(
        sa.select(t["engineer"].c.id, t["engineer"].c.name, t["engineer"].c.jira_account_id)
        .where(t["engineer"].c.jira_account_id.is_not(None))
        .order_by(t["engineer"].c.id)
    ).all():
        if not account or str(account) in known:
            continue
        known.add(str(account))
        bind.execute(
            identity.insert().values(
                created_at=now,
                updated_at=now,
                engineer_id=eid,
                provider="jira",
                external_account_id=str(account),
                display_name=name,
            )
        )

    # 4. Connections that still bind a project only through `config.project_id`.
    with_rows = {int(cid) for cid, *_ in bindings}
    bound_projects = {
        int(ti)
        for _cid, tt, ti, kind, _scope, active in bindings
        if tt == "project" and kind != "subtree" and active
    }
    projects = {int(p) for (p,) in bind.execute(sa.select(project.c.id)).all()}
    for cid, provider, raw, watermark in bind.execute(
        sa.select(
            connection.c.id, connection.c.provider, connection.c.config, connection.c.watermark
        )
    ).all():
        if str(provider) not in _TRACKERS:
            continue
        config = _json(raw)
        if "project_id" not in config:
            continue
        try:
            target = int(config["project_id"])
        except (TypeError, ValueError):
            target = -1
        if int(cid) not in with_rows and target in projects and target not in bound_projects:
            bind.execute(
                binding.insert().values(
                    created_at=now,
                    updated_at=now,
                    connection_id=cid,
                    provider=str(provider),
                    target_type="project",
                    target_id=target,
                    scope_kind="project",
                    scope=_config_scope(config),
                    mapping=_config_mapping(config),
                    status_map=[],
                    sync_iterations=bool(config.get("board_id")),
                    # The fallback synced on the connection's cursor: the next sync continues.
                    watermark=watermark,
                    active=True,
                    last_synced_at=None,
                )
            )
            bound_projects.add(target)
            bind.execute(
                project.update().where(project.c.id == target).values(tracking_mode="mirrored")
            )
        # Nothing reads it any more.
        config.pop("project_id", None)
        bind.execute(connection.update().where(connection.c.id == cid).values(config=config))


def upgrade() -> None:
    _copy_stragglers()
    # drop_table takes its indexes with it (dropping an FK-backing index first fails on MySQL).
    op.drop_table("jiralink")
    with op.batch_alter_table("drafttask") as batch:
        batch.drop_column("jira_key")
        batch.drop_column("jira_issue_id")
    with op.batch_alter_table("engineer") as batch:
        batch.drop_index(batch.f("ix_engineer_jira_account_id"))
        batch.drop_column("jira_account_id")
    with op.batch_alter_table("task") as batch:
        batch.drop_column("sprint")


def _restore() -> None:
    bind = op.get_bind()
    t = _tables()
    now = _now()

    # Identities → engineer.jira_account_id (an engineer's first Jira identity).
    done: set[int] = set()
    for eid, account in bind.execute(
        sa.select(t["identity"].c.engineer_id, t["identity"].c.external_account_id)
        .where(t["identity"].c.provider == "jira")
        .order_by(t["identity"].c.engineer_id)
    ).all():
        if int(eid) in done:
            continue
        done.add(int(eid))
        bind.execute(
            t["engineer"].update()
            .where(t["engineer"].c.id == eid)
            .values(jira_account_id=account)
        )

    # Sprint membership → the task's sprint name.
    task, sprint = t["task"], t["sprint"]
    bind.execute(
        task.update()
        .where(task.c.sprint_id.is_not(None))
        .values(
            sprint=sa.select(sprint.c.name)
            .where(sprint.c.id == task.c.sprint_id)
            .scalar_subquery()
        )
    )

    # Neutral draft ids → drafttask.jira_* (Jira pushes).
    drafttask = t["drafttask"]
    bind.execute(
        drafttask.update()
        .where(drafttask.c.external_provider == "jira")
        .values(jira_issue_id=drafttask.c.external_id, jira_key=drafttask.c.external_key)
    )

    binding = t["binding"]
    rows = bind.execute(
        sa.select(
            binding.c.connection_id,
            binding.c.provider,
            binding.c.target_type,
            binding.c.target_id,
            binding.c.scope_kind,
            binding.c.scope,
            binding.c.active,
            binding.c.last_synced_at,
        ).order_by(binding.c.id)
    ).all()
    # Active Jira tracker links → jiralink.
    seen: set[tuple[int, str]] = set()
    for cid, provider, target_type, target_id, kind, scope, active, synced in rows:
        values = _json(scope)
        root = str(values.get("root_id") or "")
        if str(provider) != "jira" or kind != "subtree" or not active or not root:
            continue
        if (int(cid), root) in seen:
            continue
        seen.add((int(cid), root))
        bind.execute(
            t["jiralink"].insert().values(
                created_at=now,
                updated_at=now,
                connection_id=cid,
                jira_issue_id=root,
                jira_key=str(values.get("root_key") or root),
                jira_issue_type=values.get("root_type"),
                target_type=target_type,
                target_id=target_id,
                last_synced_at=synced,
            )
        )
    # An active project binding → the connection's `config.project_id` (the first one).
    connection = t["connection"]
    configs = {
        int(cid): _json(raw)
        for cid, raw in bind.execute(sa.select(connection.c.id, connection.c.config)).all()
    }
    for cid, _provider, target_type, target_id, kind, _scope, active, _synced in rows:
        config = configs.get(int(cid))
        if (
            config is None
            or target_type != "project"
            or kind == "subtree"
            or not active
            or "project_id" in config
        ):
            continue
        config["project_id"] = int(target_id)
        bind.execute(connection.update().where(connection.c.id == cid).values(config=config))


def downgrade() -> None:
    with op.batch_alter_table("task") as batch:
        batch.add_column(sa.Column("sprint", sqlmodel.sql.sqltypes.AutoString(), nullable=True))
    with op.batch_alter_table("engineer") as batch:
        batch.add_column(
            sa.Column("jira_account_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )
        batch.create_index(batch.f("ix_engineer_jira_account_id"), ["jira_account_id"])
    with op.batch_alter_table("drafttask") as batch:
        batch.add_column(
            sa.Column("jira_issue_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )
        batch.add_column(sa.Column("jira_key", sqlmodel.sql.sqltypes.AutoString(), nullable=True))
    op.create_table(
        "jiralink",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("connection_id", sa.Integer(), nullable=False),
        sa.Column("jira_issue_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("jira_key", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("jira_issue_type", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("target_type", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["connection_id"], ["connection.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("connection_id", "jira_issue_id", name="uq_jira_link"),
    )
    op.create_index(op.f("ix_jiralink_connection_id"), "jiralink", ["connection_id"])
    op.create_index(op.f("ix_jiralink_jira_issue_id"), "jiralink", ["jira_issue_id"])
    op.create_index(op.f("ix_jiralink_target_id"), "jiralink", ["target_id"])
    op.create_index(op.f("ix_jiralink_target_type"), "jiralink", ["target_type"])
    _restore()
