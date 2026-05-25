"""Admin user-impersonation: an admin can mint a token that acts as another user, switch again
or back from the same session, and the impersonated session is clearly attributable to the admin.
Switching is gated on the *acting admin*, never the impersonated user, and never touches status."""

import pytest

from app.core.security import hash_password
from app.models.base import UserRole
from app.models.user import User


async def _seed(session) -> None:
    session.add(
        User(
            email="admin@e.com",
            hashed_password=hash_password("secret123"),
            role=UserRole.admin,
            full_name="Ada Admin",
        )
    )
    session.add(
        User(
            email="eng@e.com",
            hashed_password=hash_password("secret123"),
            role=UserRole.engineer,
            full_name="Ed Eng",
        )
    )
    await session.commit()


async def _login(client, email: str) -> str:
    resp = await client.post(
        "/api/v1/auth/login", data={"username": email, "password": "secret123"}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _user_id(client, headers, email: str) -> int:
    users = (await client.get("/api/v1/auth/users", headers=headers)).json()
    return next(u["id"] for u in users if u["email"] == email)


@pytest.mark.asyncio
async def test_admin_impersonates_user(client, db_session) -> None:
    await _seed(db_session)
    admin = _bearer(await _login(client, "admin@e.com"))
    eng_id = await _user_id(client, admin, "eng@e.com")

    resp = await client.post(f"/api/v1/auth/impersonate/{eng_id}", headers=admin)
    assert resp.status_code == 200, resp.text
    imp = _bearer(resp.json()["access_token"])

    # the impersonation session *is* the engineer
    me = (await client.get("/api/v1/auth/me", headers=imp)).json()
    assert me["email"] == "eng@e.com"

    # ...but the session is clearly attributable to the admin behind it
    sess = (await client.get("/api/v1/auth/session", headers=imp)).json()
    assert sess["user"]["email"] == "eng@e.com"
    assert sess["impersonator"]["email"] == "admin@e.com"


@pytest.mark.asyncio
async def test_ordinary_session_has_no_impersonator(client, db_session) -> None:
    await _seed(db_session)
    admin = _bearer(await _login(client, "admin@e.com"))
    sess = (await client.get("/api/v1/auth/session", headers=admin)).json()
    assert sess["user"]["email"] == "admin@e.com"
    assert sess["impersonator"] is None


@pytest.mark.asyncio
async def test_impersonator_can_switch_again_and_back(client, db_session) -> None:
    await _seed(db_session)
    admin = _bearer(await _login(client, "admin@e.com"))
    eng_id = await _user_id(client, admin, "eng@e.com")
    admin_id = await _user_id(client, admin, "admin@e.com")

    tok = (await client.post(f"/api/v1/auth/impersonate/{eng_id}", headers=admin)).json()[
        "access_token"
    ]
    imp = _bearer(tok)

    # acting as a non-admin engineer, the admin actor can still read the switch list...
    listed = await client.get("/api/v1/auth/users", headers=imp)
    assert listed.status_code == 200

    # ...switch directly to themselves (drops impersonation)...
    self_tok = (await client.post(f"/api/v1/auth/impersonate/{admin_id}", headers=imp)).json()[
        "access_token"
    ]
    self_sess = (await client.get("/api/v1/auth/session", headers=_bearer(self_tok))).json()
    assert self_sess["user"]["email"] == "admin@e.com"
    assert self_sess["impersonator"] is None

    # ...or use the explicit stop endpoint
    back = await client.post("/api/v1/auth/impersonate/stop", headers=imp)
    assert back.status_code == 200
    back_h = _bearer(back.json()["access_token"])
    assert (await client.get("/api/v1/auth/me", headers=back_h)).json()["email"] == "admin@e.com"


@pytest.mark.asyncio
async def test_non_admin_cannot_impersonate_or_list(client, db_session) -> None:
    await _seed(db_session)
    eng = _bearer(await _login(client, "eng@e.com"))
    admin = _bearer(await _login(client, "admin@e.com"))
    admin_id = await _user_id(client, admin, "admin@e.com")

    blocked = await client.post(f"/api/v1/auth/impersonate/{admin_id}", headers=eng)
    assert blocked.status_code == 403
    assert (await client.post("/api/v1/auth/impersonate/stop", headers=eng)).status_code == 403
    # a non-admin can't even read the switch list
    assert (await client.get("/api/v1/auth/users", headers=eng)).status_code == 403


@pytest.mark.asyncio
async def test_impersonate_invalid_targets(client, db_session) -> None:
    await _seed(db_session)
    admin = _bearer(await _login(client, "admin@e.com"))
    eng_id = await _user_id(client, admin, "eng@e.com")

    await client.patch(f"/api/v1/auth/users/{eng_id}", json={"is_active": False}, headers=admin)
    deactivated = await client.post(f"/api/v1/auth/impersonate/{eng_id}", headers=admin)
    assert deactivated.status_code == 400
    missing = await client.post("/api/v1/auth/impersonate/999999", headers=admin)
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_agent_token_cannot_impersonate(client, db_session) -> None:
    """Impersonation is human-only — a bounded agent token is rejected even for an admin."""
    await _seed(db_session)
    admin = _bearer(await _login(client, "admin@e.com"))
    eng_id = await _user_id(client, admin, "eng@e.com")

    agent_tok = (await client.post("/api/v1/auth/agent-token", json={}, headers=admin)).json()[
        "access_token"
    ]
    agent = _bearer(agent_tok)
    blocked = await client.post(f"/api/v1/auth/impersonate/{eng_id}", headers=agent)
    assert blocked.status_code == 403
