"""Revision a9b0c1d2e3f4 carries a pre-tracker install over (USER_FLOWS §J0): a Jira
connection's `config.project_id` becomes a project binding, a `jiralink` a subtree binding, an
`engineer.jira_account_id` an identity, refs are stamped with their (only) connection and pushed
drafts get the neutral columns — and the provider columns are plain VARCHAR afterwards.

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
    _alembic(db, "upgrade", "head")

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
