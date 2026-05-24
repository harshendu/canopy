import pytest

from app.connectors.gdrive import GoogleDriveConnector
from app.core.security import hash_password
from app.models.base import UserRole
from app.models.user import User


async def _seed_admin(session) -> None:
    session.add(
        User(
            email="architect@example.com",
            hashed_password=hash_password("secret123"),
            role=UserRole.admin,
        )
    )
    await session.commit()


async def _token(client) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "architect@example.com", "password": "secret123"},
    )
    return resp.json()["access_token"]


async def _project_with_work(client, headers) -> int:
    project_id = (
        await client.post(
            "/api/v1/projects", json={"key": "PLAT", "name": "Platform"}, headers=headers
        )
    ).json()["id"]
    await client.post(
        "/api/v1/tasks",
        json={
            "project_id": project_id,
            "name": "Ship token refresh",
            "duration": 4,
            "start": "2026-06-01",
            "end": "2026-06-05",
            "percent_complete": 50,
        },
        headers=headers,
    )
    await client.post(
        "/api/v1/milestones",
        json={"project_id": project_id, "name": "GA", "target_date": "2026-07-01"},
        headers=headers,
    )
    return project_id


@pytest.mark.asyncio
async def test_project_export_pdf_and_csv(client, db_session):
    await _seed_admin(db_session)
    headers = {"Authorization": f"Bearer {await _token(client)}"}
    project_id = await _project_with_work(client, headers)

    pdf = await client.get(f"/api/v1/projects/{project_id}/export?fmt=pdf", headers=headers)
    assert pdf.status_code == 200, pdf.text
    assert pdf.headers["content-type"].startswith("application/pdf")
    assert pdf.content[:4] == b"%PDF"
    assert "attachment" in pdf.headers["content-disposition"]

    csv_resp = await client.get(f"/api/v1/projects/{project_id}/export?fmt=csv", headers=headers)
    assert csv_resp.status_code == 200
    assert csv_resp.headers["content-type"].startswith("text/csv")
    body = csv_resp.text
    assert "Name,Type,Parent" in body or "Name" in body.splitlines()[0]
    assert "Ship token refresh" in body


@pytest.mark.asyncio
async def test_export_bad_format_is_400(client, db_session):
    await _seed_admin(db_session)
    headers = {"Authorization": f"Bearer {await _token(client)}"}
    project_id = await _project_with_work(client, headers)
    resp = await client.get(f"/api/v1/projects/{project_id}/export?fmt=xlsx", headers=headers)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_portfolio_and_initiative_export(client, db_session):
    await _seed_admin(db_session)
    headers = {"Authorization": f"Bearer {await _token(client)}"}
    init_id = (
        await client.post(
            "/api/v1/initiatives", json={"key": "Q3", "name": "Q3 Program"}, headers=headers
        )
    ).json()["id"]
    project_id = await _project_with_work(client, headers)
    await client.patch(
        f"/api/v1/projects/{project_id}", json={"initiative_id": init_id}, headers=headers
    )

    for url in (
        "/api/v1/portfolio/export?fmt=pdf",
        "/api/v1/portfolio/export?fmt=csv",
        f"/api/v1/initiatives/{init_id}/export?fmt=pdf",
        f"/api/v1/initiatives/{init_id}/export?fmt=csv",
    ):
        resp = await client.get(url, headers=headers)
        assert resp.status_code == 200, f"{url}: {resp.text}"
        assert resp.content  # non-empty
    portfolio_csv = (await client.get("/api/v1/portfolio/export?fmt=csv", headers=headers)).text
    assert "PLAT" in portfolio_csv


@pytest.mark.asyncio
async def test_export_to_drive(client, db_session, monkeypatch):
    await _seed_admin(db_session)
    headers = {"Authorization": f"Bearer {await _token(client)}"}
    project_id = await _project_with_work(client, headers)
    conn_id = (
        await client.post(
            "/api/v1/connectors/connections",
            json={"provider": "gdrive", "name": "drive", "token": "x", "config": {}},
            headers=headers,
        )
    ).json()["id"]

    captured: dict = {}

    async def fake_upload(self, *, name, content, mime_type):
        captured["name"] = name
        captured["mime_type"] = mime_type
        captured["bytes"] = content[:4]
        return {"id": "file-1", "name": name, "webViewLink": "https://drive/file-1"}

    monkeypatch.setattr(GoogleDriveConnector, "upload_file", fake_upload)

    resp = await client.post(
        f"/api/v1/projects/{project_id}/export/to-drive",
        json={"connection_id": conn_id, "fmt": "pdf"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["file_id"] == "file-1"
    assert resp.json()["link"] == "https://drive/file-1"
    assert captured["mime_type"] == "application/pdf"
    assert captured["bytes"] == b"%PDF"


@pytest.mark.asyncio
async def test_export_to_drive_rejects_non_drive_connection(client, db_session):
    await _seed_admin(db_session)
    headers = {"Authorization": f"Bearer {await _token(client)}"}
    project_id = await _project_with_work(client, headers)
    conn_id = (
        await client.post(
            "/api/v1/connectors/connections",
            json={
                "provider": "jira",
                "name": "jira",
                "token": "x",
                "config": {
                    "base_url": "https://x",
                    "project_id": project_id,
                    "jira_project_key": "P",
                },
            },
            headers=headers,
        )
    ).json()["id"]
    resp = await client.post(
        f"/api/v1/projects/{project_id}/export/to-drive",
        json={"connection_id": conn_id, "fmt": "pdf"},
        headers=headers,
    )
    assert resp.status_code == 400
