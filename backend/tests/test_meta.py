"""GET /api/v1/meta — non-secret instance metadata that drives the Agent Setup snippets."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.base import UserRole
from app.models.user import User


async def _headers(client, email: str) -> dict[str, str]:
    resp = await client.post(
        "/api/v1/auth/login", data={"username": email, "password": "secret123"}
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _seed(session: AsyncSession) -> None:
    session.add(
        User(
            email="arch@e.com",
            hashed_password=hash_password("secret123"),
            role=UserRole.architect,
        )
    )
    await session.commit()


@pytest.mark.asyncio
async def test_meta_requires_auth(client) -> None:
    assert (await client.get("/api/v1/meta")).status_code == 401


@pytest.mark.asyncio
async def test_meta_returns_configured_setup_values(client, db_session) -> None:
    await _seed(db_session)
    headers = await _headers(client, "arch@e.com")
    resp = await client.get("/api/v1/meta", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    # Defaults from Settings; a fork overrides them via env. Shape is what the frontend consumes.
    assert set(body) == {
        "project_name",
        "plugin_marketplace_ref",
        "plugin_repo_url",
        "plugin_mcp_server_path",
    }
    assert body["plugin_mcp_server_path"] == "plugin/mcp_server/server.py"
    assert "/" in body["plugin_marketplace_ref"]  # owner/repo form
