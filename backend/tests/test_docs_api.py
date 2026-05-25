import pytest

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


async def _project(client, headers) -> int:
    return (
        await client.post(
            "/api/v1/projects", json={"key": "PLAT", "name": "Platform"}, headers=headers
        )
    ).json()["id"]


@pytest.mark.asyncio
async def test_doc_reference_crud_and_coverage(client, db_session) -> None:
    await _seed_admin(db_session)
    headers = {"Authorization": f"Bearer {await _token(client)}"}
    project_id = await _project(client, headers)

    created = await client.post(
        "/api/v1/docs",
        json={
            "scope_level": "project",
            "scope_id": project_id,
            "url": "https://docs.google.com/document/d/prd",
            "kind": "prd",
            "title": "Checkout PRD",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    doc_id = created.json()["id"]
    assert created.json()["source"] == "manual"

    listed = await client.get(
        "/api/v1/docs", params={"scope_level": "project", "scope_id": project_id}, headers=headers
    )
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    cov = await client.get(
        "/api/v1/docs/coverage",
        params={"scope_level": "project", "scope_id": project_id},
        headers=headers,
    )
    assert cov.status_code == 200, cov.text
    body = cov.json()
    assert "prd" in body["present"]
    assert "design" in body["missing"]
    assert body["total_references"] == 1

    patched = await client.patch(
        f"/api/v1/docs/{doc_id}", json={"kind": "tech_design"}, headers=headers
    )
    assert patched.status_code == 200
    assert patched.json()["kind"] == "tech_design"

    deleted = await client.delete(f"/api/v1/docs/{doc_id}", headers=headers)
    assert deleted.status_code == 204


@pytest.mark.asyncio
async def test_create_doc_rejects_missing_scope(client, db_session) -> None:
    await _seed_admin(db_session)
    headers = {"Authorization": f"Bearer {await _token(client)}"}
    resp = await client.post(
        "/api/v1/docs",
        json={"scope_level": "project", "scope_id": 999, "url": "https://x/y", "kind": "prd"},
        headers=headers,
    )
    assert resp.status_code == 404
