"""Per-provider integration policy: the resolver, the admin API, and write-guard enforcement.

Defaults must reproduce the pre-policy behavior (direct reads + direct writes), so existing
installs are unaffected until an admin opts in.
"""

import pytest
from sqlmodel import func, select

from app.core.security import hash_password
from app.models.base import Provider, ReadStrategy, UserRole, WriteStrategy
from app.models.integration import Connection, IntegrationSetting
from app.models.user import User
from app.services import integration_policy


# --- resolver unit tests ---
@pytest.mark.asyncio
async def test_get_setting_defaults_to_direct_without_persisting(db_session) -> None:
    setting = await integration_policy.get_setting(db_session, Provider.jira)
    assert setting.read_strategy == ReadStrategy.direct
    assert setting.write_strategy == WriteStrategy.direct
    assert setting.allow_user_connect is False
    # The default is in-memory only — reading must not write a row.
    count = (
        await db_session.execute(select(func.count()).select_from(IntegrationSetting))
    ).scalar()
    assert count == 0


@pytest.mark.asyncio
async def test_usable_direct_connections_requires_active_and_authorized(db_session) -> None:
    db_session.add_all(
        [
            Connection(provider=Provider.jira, name="ok", encrypted_token="tok", active=True),
            Connection(provider=Provider.jira, name="no-token", active=True),
            Connection(
                provider=Provider.jira, name="inactive", encrypted_token="tok", active=False
            ),
            Connection(provider=Provider.github, name="other", encrypted_token="tok", active=True),
        ]
    )
    await db_session.commit()

    usable = await integration_policy.usable_direct_connections(db_session, Provider.jira)
    assert [c.name for c in usable] == ["ok"]


@pytest.mark.asyncio
async def test_reads_direct_only_for_direct_strategy() -> None:
    assert integration_policy.reads_direct(
        IntegrationSetting(provider=Provider.jira, read_strategy=ReadStrategy.direct)
    )
    for strat in (ReadStrategy.mcp, ReadStrategy.file):
        assert not integration_policy.reads_direct(
            IntegrationSetting(provider=Provider.jira, read_strategy=strat)
        )


@pytest.mark.asyncio
async def test_resolve_write_blocks_mcp_and_disabled(db_session) -> None:
    assert (await integration_policy.resolve_write(db_session, Provider.jira)).allowed  # default

    db_session.add(
        IntegrationSetting(provider=Provider.jira, write_strategy=WriteStrategy.mcp)
    )
    db_session.add(
        IntegrationSetting(provider=Provider.gdrive, write_strategy=WriteStrategy.disabled)
    )
    await db_session.commit()

    jira = await integration_policy.resolve_write(db_session, Provider.jira)
    assert not jira.allowed and "MCP" in jira.reason

    drive = await integration_policy.resolve_write(db_session, Provider.gdrive)
    assert not drive.allowed and "disabled" in drive.reason


# --- admin API + enforcement ---
async def _seed(session) -> None:
    session.add_all(
        [
            User(
                email="admin@e.com",
                hashed_password=hash_password("secret123"),
                role=UserRole.admin,
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
async def test_admin_settings_requires_admin(client, db_session) -> None:
    await _seed(db_session)
    eng = await _headers(client, "eng@e.com")
    assert (await client.get("/api/v1/admin/integrations", headers=eng)).status_code == 403
    assert (
        await client.patch(
            "/api/v1/admin/integrations/jira", json={"write_strategy": "mcp"}, headers=eng
        )
    ).status_code == 403


@pytest.mark.asyncio
async def test_admin_lists_defaults_and_patches(client, db_session) -> None:
    await _seed(db_session)
    admin = await _headers(client, "admin@e.com")

    listed = (await client.get("/api/v1/admin/integrations", headers=admin)).json()
    assert {row["provider"] for row in listed} == {"jira", "github", "gdrive"}
    assert all(
        row["read_strategy"] == "direct" and row["write_strategy"] == "direct" for row in listed
    )

    patched = await client.patch(
        "/api/v1/admin/integrations/jira", json={"write_strategy": "mcp"}, headers=admin
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["write_strategy"] == "mcp"

    again = (await client.get("/api/v1/admin/integrations", headers=admin)).json()
    jira = next(row for row in again if row["provider"] == "jira")
    assert jira["write_strategy"] == "mcp"


@pytest.mark.asyncio
async def test_push_to_jira_blocked_when_write_is_mcp(client, db_session) -> None:
    await _seed(db_session)
    admin = await _headers(client, "admin@e.com")

    # Default policy (direct): the guard lets the request through to the plan lookup (404/400).
    direct = await client.post("/api/v1/draft-plans/999/push-to-jira", json={}, headers=admin)
    assert direct.status_code == 400

    await client.patch(
        "/api/v1/admin/integrations/jira", json={"write_strategy": "mcp"}, headers=admin
    )
    blocked = await client.post("/api/v1/draft-plans/999/push-to-jira", json={}, headers=admin)
    assert blocked.status_code == 403
    assert "MCP" in blocked.json()["detail"]
