"""Revision a9b0c1d2e3f4 carries a pre-tracker install over (USER_FLOWS §J0): a Jira
connection's `config.project_id` becomes a project binding, a `jiralink` a subtree binding, an
`engineer.jira_account_id` an identity, refs are stamped with their (only) connection and pushed
drafts get the neutral columns — and the provider columns are plain VARCHAR afterwards.

Revision b0c1d2e3f4a5 then retires that legacy storage: whatever the deprecation window left
uncopied is copied first (nothing canopy owns is lost), `config.project_id` leaves tracker
connections, `task.sprint` gives way to `task.sprint_id`, and the downgrade restores the columns
from their replacements.

Runs the real migrations on a temp SQLite file; CI also runs `alembic upgrade head` +
`alembic check` on Postgres and MySQL/MariaDB.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
BEFORE = "e7f8a9b0c1d2"  # the last revision before the tracker layer
TRACKER_LAYER = "a9b0c1d2e3f4"  # the tracker layer, legacy storage still beside it


def _alembic(db: Path, *args: str) -> None:
    env = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{db}"}
    done = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr[-3000:]


def _seed_legacy(db: Path) -> dict[str, int]:
    now = "2026-11-01 12:00:00.000000"
    con = sqlite3.connect(db)
    cur = con.cursor()
    cur.execute(
        "INSERT INTO project (created_at, updated_at, key, name, archived, skip_weekends, "
        "tracking_mode, next_task_number) VALUES (?, ?, 'SHOP', 'Shop', 0, 1, 'mirrored', 1)",
        (now, now),
    )
    project = int(cur.lastrowid or 0)
    config = {
        "base_url": "https://jira.example.com",
        "project_id": project,
        "jira_project_key": "SHOP",
        "board_id": 7,
        "epic_issue_type": "Initiative Epic",
        "story_point_field": "customfield_10016",
    }
    cur.execute(
        "INSERT INTO connection (created_at, updated_at, provider, name, config, watermark, "
        "active) VALUES (?, ?, 'jira', 'jira', ?, '2026-10-01 10:00', 1)",
        (now, now, json.dumps(config)),
    )
    connection = int(cur.lastrowid or 0)
    cur.execute(
        "INSERT INTO jiralink (created_at, updated_at, connection_id, jira_issue_id, jira_key, "
        "jira_issue_type, target_type, target_id) VALUES (?, ?, ?, '9001', 'SHOP-1', 'Epic', "
        "'project', ?)",
        (now, now, connection, project),
    )
    for name, account in (("Ada", "acc-1"), ("Ada again", "acc-1"), ("Bob", None)):
        cur.execute(
            "INSERT INTO engineer (created_at, updated_at, name, active, jira_account_id) "
            "VALUES (?, ?, ?, 1, ?)",
            (now, now, name, account),
        )
    cur.execute(
        "INSERT INTO externalref (created_at, updated_at, provider, external_id, external_key, "
        "entity_type, entity_id) VALUES (?, ?, 'jira', '9002', 'SHOP-2', 'task', 1)",
        (now, now),
    )
    cur.execute(
        "INSERT INTO draftplan (created_at, updated_at, project_id, title, status) "
        "VALUES (?, ?, ?, 'Plan', 'synced')",
        (now, now, project),
    )
    plan = int(cur.lastrowid or 0)
    cur.execute(
        "INSERT INTO drafttask (created_at, updated_at, plan_id, name, type, estimate_days, "
        "sort_order, jira_issue_id, jira_key) VALUES (?, ?, ?, 'Story', 'task', 1, 0, '9003', "
        "'SHOP-3')",
        (now, now, plan),
    )
    con.commit()
    con.close()
    return {"project": project, "connection": connection}


def test_legacy_jira_config_becomes_bindings_and_identities(tmp_path: Path) -> None:
    db = tmp_path / "legacy.db"
    _alembic(db, "upgrade", BEFORE)
    ids = _seed_legacy(db)
    _alembic(db, "upgrade", TRACKER_LAYER)

    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    bindings = con.execute("SELECT * FROM trackerbinding ORDER BY id").fetchall()
    assert len(bindings) == 2
    project, subtree = bindings
    assert (project["provider"], project["target_type"], project["target_id"]) == (
        "jira",
        "project",
        ids["project"],
    )
    assert project["connection_id"] == ids["connection"]
    assert project["scope_kind"] == "project"
    assert json.loads(project["scope"]) == {"project_key": "SHOP", "board_id": 7}
    assert json.loads(project["mapping"]) == {
        "epic_types": ["Initiative Epic"],
        "estimate_field": "customfield_10016",
    }
    assert project["sync_iterations"] == 1 and project["active"] == 1
    assert project["watermark"] == "2026-10-01 10:00"  # the next incremental sync continues
    assert subtree["scope_kind"] == "subtree"
    assert json.loads(subtree["scope"]) == {
        "root_id": "9001",
        "root_key": "SHOP-1",
        "root_type": "Epic",
    }

    identities = con.execute(
        "SELECT provider, external_account_id, display_name FROM engineeridentity"
    ).fetchall()
    assert [tuple(r) for r in identities] == [("jira", "acc-1", "Ada")]  # first engineer wins

    ref = con.execute("SELECT connection_id, detached_at FROM externalref").fetchone()
    assert (ref["connection_id"], ref["detached_at"]) == (ids["connection"], None)
    draft = con.execute(
        "SELECT external_provider, external_id, external_key, task_id FROM drafttask"
    ).fetchone()
    assert tuple(draft) == ("jira", "9003", "SHOP-3", None)
    # The legacy columns are still there for the deprecation window.
    assert con.execute("SELECT jira_key FROM drafttask").fetchone()[0] == "SHOP-3"
    con.close()

    # And back down past both revisions, then up again.
    _alembic(db, "downgrade", BEFORE)
    _alembic(db, "upgrade", "head")


def _seed_stragglers(db: Path) -> dict[str, int]:
    """Legacy-shaped rows the tracker-layer copy (or the window's dual writes) didn't carry."""
    now = "2026-11-10 12:00:00.000000"
    con = sqlite3.connect(db)
    cur = con.cursor()
    ids: dict[str, int] = {}
    for key, mode in (("NAT", "native"), ("MIR", "mirrored")):
        cur.execute(
            "INSERT INTO project (created_at, updated_at, key, name, archived, skip_weekends, "
            "tracking_mode, next_task_number) VALUES (?, ?, ?, ?, 0, 1, ?, 1)",
            (now, now, key, key, mode),
        )
        ids[key] = int(cur.lastrowid or 0)

    def connection(name: str, config: dict[str, object], watermark: str | None) -> int:
        cur.execute(
            "INSERT INTO connection (created_at, updated_at, provider, name, config, watermark, "
            "active) VALUES (?, ?, 'jira', ?, ?, ?, 1)",
            (now, now, name, json.dumps(config), watermark),
        )
        return int(cur.lastrowid or 0)

    # Binds NAT only through its config: the fallback read it, no binding row exists.
    ids["config_only"] = connection(
        "config-only",
        {"base_url": "https://a.example.com", "project_id": ids["NAT"], "jira_project_key": "A"},
        "2026-11-09 08:00",
    )
    # Already bound by a row: only the config key goes.
    ids["bound"] = connection(
        "bound", {"base_url": "https://b.example.com", "project_id": ids["MIR"]}, None
    )
    cur.execute(
        "INSERT INTO trackerbinding (created_at, updated_at, connection_id, provider, "
        "target_type, target_id, scope_kind, scope, mapping, status_map, sync_iterations, "
        "active) VALUES (?, ?, ?, 'jira', 'project', ?, 'project', '{}', '{}', '[]', 0, 1)",
        (now, now, ids["bound"], ids["MIR"]),
    )
    cur.execute(
        "INSERT INTO jiralink (created_at, updated_at, connection_id, jira_issue_id, jira_key, "
        "jira_issue_type, target_type, target_id) VALUES (?, ?, ?, '502', 'B-2', 'Epic', "
        "'project', ?)",
        (now, now, ids["bound"], ids["MIR"]),
    )
    cur.execute(
        "INSERT INTO engineer (created_at, updated_at, name, active, jira_account_id) "
        "VALUES (?, ?, 'Cy', 1, 'acc-9')",
        (now, now),
    )
    ids["engineer"] = int(cur.lastrowid or 0)
    cur.execute(
        "INSERT INTO draftplan (created_at, updated_at, project_id, title, status) "
        "VALUES (?, ?, ?, 'Plan', 'synced')",
        (now, now, ids["MIR"]),
    )
    plan = int(cur.lastrowid or 0)
    cur.execute(
        "INSERT INTO drafttask (created_at, updated_at, plan_id, name, type, estimate_days, "
        "sort_order, jira_issue_id, jira_key) VALUES (?, ?, ?, 'Story', 'task', 1, 0, '703', "
        "'B-3')",
        (now, now, plan),
    )
    # One task in a team sprint (its name kept in step), one with a team-less sprint name only.
    cur.execute(
        "INSERT INTO team (created_at, updated_at, key, name) VALUES (?, ?, 'T', 'Team')",
        (now, now),
    )
    cur.execute(
        "INSERT INTO sprint (created_at, updated_at, team_id, name, state, owner) "
        "VALUES (?, ?, ?, 'Sprint 7', 'active', 'canopy')",
        (now, now, int(cur.lastrowid or 0)),
    )
    sprint = int(cur.lastrowid or 0)
    for name, sprint_name, sprint_id in (("in-sprint", "Sprint 7", sprint), ("loose", "S3", None)):
        cur.execute(
            "INSERT INTO task (created_at, updated_at, project_id, name, type, duration, "
            "percent_complete, is_critical, total_float, sprint, sprint_id) "
            "VALUES (?, ?, ?, ?, 'task', 1, 0, 0, 0, ?, ?)",
            (now, now, ids["MIR"], name, sprint_name, sprint_id),
        )
    con.commit()
    con.close()
    return ids


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {str(r[1]) for r in con.execute(f"PRAGMA table_info({table})").fetchall()}


def test_retiring_legacy_storage_copies_stragglers_first(tmp_path: Path) -> None:
    db = tmp_path / "stragglers.db"
    _alembic(db, "upgrade", TRACKER_LAYER)
    ids = _seed_stragglers(db)
    _alembic(db, "upgrade", "head")

    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    tables = {str(r[0]) for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "jiralink" not in tables
    assert "jira_account_id" not in _columns(con, "engineer")
    assert not {"jira_issue_id", "jira_key"} & _columns(con, "drafttask")
    assert "sprint" not in _columns(con, "task")

    configs = {
        int(r["id"]): json.loads(r["config"])
        for r in con.execute("SELECT id, config FROM connection").fetchall()
    }
    assert all("project_id" not in c for c in configs.values()), configs
    assert configs[ids["config_only"]]["jira_project_key"] == "A"  # the rest stays

    (straggler,) = con.execute(
        "SELECT * FROM trackerbinding WHERE connection_id = ?", (ids["config_only"],)
    ).fetchall()
    assert (straggler["target_type"], straggler["target_id"], straggler["scope_kind"]) == (
        "project",
        ids["NAT"],
        "project",
    )
    assert json.loads(straggler["scope"]) == {"project_key": "A"}
    assert straggler["watermark"] == "2026-11-09 08:00"  # the next incremental sync continues
    mode = con.execute("SELECT tracking_mode FROM project WHERE id = ?", (ids["NAT"],))
    assert mode.fetchone()[0] == "mirrored"

    bound = con.execute(
        "SELECT scope_kind, scope FROM trackerbinding WHERE connection_id = ? ORDER BY id",
        (ids["bound"],),
    ).fetchall()
    assert [r["scope_kind"] for r in bound] == ["project", "subtree"]  # nothing duplicated
    assert json.loads(bound[1]["scope"])["root_key"] == "B-2"

    identity = con.execute(
        "SELECT engineer_id, provider, external_account_id FROM engineeridentity"
    ).fetchall()
    assert [tuple(r) for r in identity] == [(ids["engineer"], "jira", "acc-9")]
    draft = con.execute("SELECT external_provider, external_id, external_key FROM drafttask")
    assert tuple(draft.fetchone()) == ("jira", "703", "B-3")
    con.close()

    # The downgrade restores the legacy storage from its replacements.
    _alembic(db, "downgrade", TRACKER_LAYER)
    con = sqlite3.connect(db)
    links = con.execute("SELECT connection_id, jira_issue_id, jira_key FROM jiralink").fetchall()
    assert links == [(ids["bound"], "502", "B-2")]
    account = con.execute("SELECT jira_account_id FROM engineer WHERE id = ?", (ids["engineer"],))
    assert account.fetchone()[0] == "acc-9"
    assert con.execute("SELECT jira_issue_id, jira_key FROM drafttask").fetchone() == (
        "703",
        "B-3",
    )
    restored = {
        int(r[0]): json.loads(r[1])
        for r in con.execute("SELECT id, config FROM connection").fetchall()
    }
    assert restored[ids["config_only"]]["project_id"] == ids["NAT"]
    assert restored[ids["bound"]]["project_id"] == ids["MIR"]
    sprints = dict(con.execute("SELECT name, sprint FROM task").fetchall())
    assert sprints == {"in-sprint": "Sprint 7", "loose": None}  # restored from the membership
    con.close()
    _alembic(db, "upgrade", "head")
