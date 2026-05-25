"""File-drop watched storage (Phase 4): local + S3 backends and the poll that ingests + moves."""

import json

import pytest
from sqlmodel import select

from app.models.base import Provider
from app.models.integration import Connection
from app.models.project import Project, Task
from app.services.file_drop import LocalDropStorage, S3DropStorage, process_drops


# --- local backend ---
def test_local_lists_only_data_files_in_digit_dirs(tmp_path) -> None:
    (tmp_path / "3").mkdir()
    (tmp_path / "3" / "issues.json").write_text("[]")
    (tmp_path / "3" / "notes.txt").write_text("ignore me")  # non-data extension
    (tmp_path / "misc").mkdir()  # non-digit dir → not a connection
    (tmp_path / "misc" / "x.json").write_text("[]")

    pending = LocalDropStorage(tmp_path).list_pending()
    assert [(p.connection_id, p.name) for p in pending] == [(3, "issues.json")]


def test_local_mark_processed_and_failed(tmp_path) -> None:
    conn_dir = tmp_path / "1"
    conn_dir.mkdir()
    (conn_dir / "a.json").write_text("[]")
    (conn_dir / "b.csv").write_text("x")
    storage = LocalDropStorage(tmp_path)

    a = next(p for p in storage.list_pending() if p.name == "a.json")
    storage.mark_processed(a)
    assert not (conn_dir / "a.json").exists()
    assert (conn_dir / "processed" / "a.json").exists()

    b = next(p for p in storage.list_pending() if p.name == "b.csv")
    storage.mark_failed(b, "boom")
    assert (conn_dir / "failed" / "b.csv").exists()
    assert (conn_dir / "failed" / "b.csv.error").read_text() == "boom"

    # processed/ and failed/ are not re-listed as pending
    assert storage.list_pending() == []


# --- S3 backend (logic tested against an in-memory fake client) ---
class _FakeS3:
    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}

    def list_objects(self, bucket: str, prefix: str) -> list[str]:
        return [k for k in self.store if k.startswith(prefix)]

    def get(self, bucket: str, key: str) -> bytes:
        return self.store[key]

    def move(self, bucket: str, src: str, dst: str) -> None:
        self.store[dst] = self.store.pop(src)

    def put(self, bucket: str, key: str, data: bytes) -> None:
        self.store[key] = data


def test_s3_lists_reads_and_moves() -> None:
    fake = _FakeS3()
    fake.store["drops/2/issues.json"] = b"[]"
    fake.store["drops/2/processed/old.json"] = b"[]"  # nested → not pending
    storage = S3DropStorage("bucket", "drops", fake)

    pending = storage.list_pending()
    assert [(p.connection_id, p.name) for p in pending] == [(2, "issues.json")]
    assert storage.read(pending[0]) == b"[]"

    storage.mark_processed(pending[0])
    assert "drops/2/issues.json" not in fake.store
    assert "drops/2/processed/issues.json" in fake.store


def test_s3_mark_failed_writes_error_object() -> None:
    fake = _FakeS3()
    fake.store["drops/5/bad.csv"] = b"x"
    storage = S3DropStorage("bucket", "drops", fake)
    storage.mark_failed(storage.list_pending()[0], "boom")
    assert fake.store["drops/5/failed/bad.csv"] == b"x"
    assert fake.store["drops/5/failed/bad.csv.error"] == b"boom"


# --- the poll ---
@pytest.mark.asyncio
async def test_process_drops_ingests_and_moves(db_session, tmp_path) -> None:
    project = Project(key="PLAT", name="Platform")
    db_session.add(project)
    await db_session.flush()
    conn = Connection(provider=Provider.jira, name="j", config={"project_id": project.id})
    db_session.add(conn)
    await db_session.flush()

    conn_dir = tmp_path / str(conn.id)
    conn_dir.mkdir()
    (conn_dir / "issues.json").write_text(
        json.dumps([{"external_id": "1", "external_key": "PLAT-1", "summary": "S"}])
    )
    storage = LocalDropStorage(tmp_path)

    summary = await process_drops(db_session, storage)
    assert summary["issues.json"]["created"] == 1
    count = len((await db_session.execute(select(Task))).scalars().all())
    assert count == 1
    assert (conn_dir / "processed" / "issues.json").exists()


@pytest.mark.asyncio
async def test_process_drops_unknown_connection_fails_file(db_session, tmp_path) -> None:
    conn_dir = tmp_path / "999"
    conn_dir.mkdir()
    (conn_dir / "x.json").write_text("[]")
    summary = await process_drops(db_session, LocalDropStorage(tmp_path))
    assert "error" in summary["x.json"]
    assert (conn_dir / "failed" / "x.json").exists()
