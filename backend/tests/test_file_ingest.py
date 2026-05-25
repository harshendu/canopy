"""File-drop ingest parser + upload endpoint (Phase 4)."""

import json

import pytest
from sqlmodel import select

from app.core.security import hash_password
from app.models.base import Provider, UserRole
from app.models.integration import Connection, PullRequest
from app.models.project import Project, Task
from app.models.user import User
from app.schemas.entities import IngestIssue
from app.services import file_ingest
from app.services.file_ingest import FileIngestError, _rows_from_bytes, _validate_rows


# --- parser ---
def test_rows_from_json_and_csv() -> None:
    assert _rows_from_bytes("x.json", b'[{"external_id": "1"}]') == [{"external_id": "1"}]
    csv_rows = _rows_from_bytes("x.csv", b"external_id,summary\n1,Hi\n")
    assert csv_rows == [{"external_id": "1", "summary": "Hi"}]
    # a blank CSV cell becomes None (so optional fields validate)
    assert _rows_from_bytes("x.csv", b"external_id,status\n1,\n") == [
        {"external_id": "1", "status": None}
    ]
    with pytest.raises(FileIngestError, match="unsupported"):
        _rows_from_bytes("x.txt", b"")
    with pytest.raises(FileIngestError, match="array"):
        _rows_from_bytes("x.json", b'{"not": "a list"}')


def test_validate_collects_bad_rows() -> None:
    parsed, errors = _validate_rows(
        [{"external_id": "1", "summary": "ok"}, {"summary": "no id"}], IngestIssue
    )
    assert len(parsed) == 1
    assert len(errors) == 1 and errors[0].startswith("row 1")


# --- ingest_file end to end ---
async def _jira(session) -> tuple[Project, Connection]:
    project = Project(key="PLAT", name="Platform")
    session.add(project)
    await session.flush()
    conn = Connection(provider=Provider.jira, name="j", config={"project_id": project.id})
    session.add(conn)
    await session.flush()
    return project, conn


@pytest.mark.asyncio
async def test_ingest_file_jira_csv(db_session) -> None:
    _, conn = await _jira(db_session)
    data = b"external_id,external_key,summary,issue_type\n1,PLAT-1,Build,Story\n2,PLAT-2,,Story\n"
    result = await file_ingest.ingest_file(db_session, conn, "issues.csv", data)
    assert result.created == 1  # row 2 has a blank summary → skipped as an error
    assert result.parsed == 1 and len(result.errors) == 1
    assert len((await db_session.execute(select(Task))).scalars().all()) == 1


@pytest.mark.asyncio
async def test_ingest_file_github_json(db_session) -> None:
    conn = Connection(
        provider=Provider.github, name="gh", config={"owner": "acme", "repo": "platform"}
    )
    db_session.add(conn)
    await db_session.flush()
    data = json.dumps([{"number": 7, "title": "Add auth", "state": "open"}]).encode()
    result = await file_ingest.ingest_file(db_session, conn, "prs.json", data)
    assert result.created == 1
    rows = (await db_session.execute(select(PullRequest))).scalars().all()
    assert len(rows) == 1 and rows[0].repo == "acme/platform"


# --- upload endpoint: gating + agent-allowed ---
async def _seed(session) -> None:
    session.add_all(
        [
            User(
                email="arch@e.com",
                hashed_password=hash_password("secret123"),
                role=UserRole.architect,
            ),
            User(
                email="eng@e.com",
                hashed_password=hash_password("secret123"),
                role=UserRole.engineer,
            ),
        ]
    )
    await session.commit()


async def _headers(client, email: str) -> dict[str, str]:
    resp = await client.post(
        "/api/v1/auth/login", data={"username": email, "password": "secret123"}
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.mark.asyncio
async def test_upload_endpoint_planner_gated_and_reports_errors(client, db_session) -> None:
    await _seed(db_session)
    _, conn = await _jira(db_session)
    await db_session.commit()

    url = f"/api/v1/connectors/connections/{conn.id}/ingest/file"
    payload = json.dumps(
        [
            {"external_id": "1", "external_key": "PLAT-1", "summary": "Build"},
            {"summary": "missing id"},
        ]
    )

    def files() -> dict:
        return {"file": ("issues.json", payload, "application/json")}

    eng = await _headers(client, "eng@e.com")
    assert (await client.post(url, files=files(), headers=eng)).status_code == 403

    arch = await _headers(client, "arch@e.com")
    ok = await client.post(url, files=files(), headers=arch)
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["created"] == 1 and body["parsed"] == 1 and len(body["errors"]) == 1

    # An agent-scope token may upload too (internal ingest, not human-only).
    agent_resp = await client.post("/api/v1/auth/agent-token", json={}, headers=arch)
    agent = {"Authorization": f"Bearer {agent_resp.json()['access_token']}"}
    assert (await client.post(url, files=files(), headers=agent)).status_code == 200


@pytest.mark.asyncio
async def test_upload_unsupported_type_is_400(client, db_session) -> None:
    await _seed(db_session)
    _, conn = await _jira(db_session)
    await db_session.commit()
    arch = await _headers(client, "arch@e.com")
    resp = await client.post(
        f"/api/v1/connectors/connections/{conn.id}/ingest/file",
        files={"file": ("data.txt", "nope", "text/plain")},
        headers=arch,
    )
    assert resp.status_code == 400
