"""Admin user provisioning: password reset, self-service password change, and the
last-active-admin lockout guard."""

import pytest

from app.core.security import hash_password
from app.models.base import TokenScope, UserRole
from app.models.user import User
from app.schemas.auth import MIN_PASSWORD_LENGTH


async def _seed(session, *, second_admin: bool = False) -> None:
    users = [
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
    if second_admin:
        users.append(
            User(
                email="admin2@e.com",
                hashed_password=hash_password("secret123"),
                role=UserRole.admin,
            )
        )
    session.add_all(users)
    await session.commit()


async def _login(client, email: str, password: str = "secret123"):
    return await client.post("/api/v1/auth/login", data={"username": email, "password": password})


async def _headers(client, email: str, password: str = "secret123") -> dict[str, str]:
    resp = await _login(client, email, password)
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _user_id(client, admin: dict[str, str], email: str) -> int:
    users = (await client.get("/api/v1/auth/users", headers=admin)).json()
    return next(u["id"] for u in users if u["email"] == email)


@pytest.mark.asyncio
async def test_admin_resets_password_and_user_logs_in_with_it(client, db_session) -> None:
    await _seed(db_session)
    admin = await _headers(client, "admin@e.com")
    eng_id = await _user_id(client, admin, "eng@e.com")

    resp = await client.post(
        f"/api/v1/auth/users/{eng_id}/password",
        json={"new_password": "temp-password-1"},
        headers=admin,
    )
    assert resp.status_code == 200, resp.text

    assert (await _login(client, "eng@e.com", "secret123")).status_code == 401
    assert (await _login(client, "eng@e.com", "temp-password-1")).status_code == 200

    too_short = await client.post(
        f"/api/v1/auth/users/{eng_id}/password",
        json={"new_password": "x" * (MIN_PASSWORD_LENGTH - 1)},
        headers=admin,
    )
    assert too_short.status_code == 422


@pytest.mark.asyncio
async def test_password_reset_requires_admin_and_human(client, db_session) -> None:
    await _seed(db_session)
    eng = await _headers(client, "eng@e.com")
    admin = await _headers(client, "admin@e.com")
    eng_id = await _user_id(client, admin, "eng@e.com")

    denied = await client.post(
        f"/api/v1/auth/users/{eng_id}/password",
        json={"new_password": "temp-password-1"},
        headers=eng,
    )
    assert denied.status_code == 403

    # An agent-scoped token (bounded agency) must not be able to rotate credentials.
    agent = (
        await client.post("/api/v1/auth/agent-token", json={}, headers=admin)
    ).json()["access_token"]
    blocked = await client.post(
        f"/api/v1/auth/users/{eng_id}/password",
        json={"new_password": "temp-password-1"},
        headers={"Authorization": f"Bearer {agent}"},
    )
    assert blocked.status_code == 403
    assert TokenScope.agent.value in blocked.text or "agent" in blocked.text


@pytest.mark.asyncio
async def test_user_changes_own_password(client, db_session) -> None:
    await _seed(db_session)
    eng = await _headers(client, "eng@e.com")

    wrong = await client.post(
        "/api/v1/auth/me/password",
        json={"current_password": "nope", "new_password": "brand-new-pass"},
        headers=eng,
    )
    assert wrong.status_code == 400

    ok = await client.post(
        "/api/v1/auth/me/password",
        json={"current_password": "secret123", "new_password": "brand-new-pass"},
        headers=eng,
    )
    assert ok.status_code == 200, ok.text
    assert (await _login(client, "eng@e.com", "brand-new-pass")).status_code == 200


@pytest.mark.asyncio
async def test_last_active_admin_cannot_be_demoted_or_deactivated(client, db_session) -> None:
    await _seed(db_session)
    admin = await _headers(client, "admin@e.com")
    admin_id = await _user_id(client, admin, "admin@e.com")

    demote = await client.patch(
        f"/api/v1/auth/users/{admin_id}", json={"role": "engineer"}, headers=admin
    )
    assert demote.status_code == 400
    assert "last active admin" in demote.json()["detail"]

    deactivate = await client.patch(
        f"/api/v1/auth/users/{admin_id}", json={"is_active": False}, headers=admin
    )
    assert deactivate.status_code == 400  # self-deactivation guard fires first


@pytest.mark.asyncio
async def test_admin_demotion_allowed_when_another_admin_exists(client, db_session) -> None:
    await _seed(db_session, second_admin=True)
    admin2 = await _headers(client, "admin2@e.com")
    admin_id = await _user_id(client, admin2, "admin@e.com")

    demote = await client.patch(
        f"/api/v1/auth/users/{admin_id}", json={"role": "architect"}, headers=admin2
    )
    assert demote.status_code == 200, demote.text
    assert demote.json()["role"] == "architect"
