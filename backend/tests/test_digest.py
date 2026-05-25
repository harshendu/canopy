from datetime import date

import pytest

from app.core.security import hash_password
from app.models.base import UserFunction
from app.models.user import User
from app.services import digest as digest_service

# --- pure: attention (manage by exception) --------------------------------------

def _inputs(**over: object) -> digest_service.DigestInputs:
    base: dict = {
        "name": "Q3",
        "generated_on": date(2026, 5, 25),
        "on_track": True,
        "target_date": date(2026, 8, 1),
        "project_end": date(2026, 7, 1),
        "p85_date": date(2026, 7, 15),
        "forecast_sufficient": True,
        "risk_level": "low",
        "drift_level": "low",
        "avg_percent_complete": 40.0,
        "completed_tasks": 4,
        "total_tasks": 10,
        "open_decisions": 0,
        "open_blockers": 0,
        "at_risk_projects": [],
        "outcomes": [],
    }
    base.update(over)
    return digest_service.DigestInputs(**base)


def test_clean_initiative_has_no_attention() -> None:
    attention = digest_service.attention_items(_inputs())
    assert attention == []
    assert digest_service.headline(attention) == "On track — no exceptions to flag."


def test_attention_surfaces_exceptions() -> None:
    attention = digest_service.attention_items(
        _inputs(
            on_track=False,
            project_end=date(2026, 9, 1),
            p85_date=date(2026, 9, 10),
            risk_level="high",
            open_blockers=2,
            open_decisions=3,
            at_risk_projects=["Billing"],
        )
    )
    text = " ".join(attention)
    assert "Behind target" in text
    assert "P85 forecast" in text
    assert "Risk is high" in text
    assert "2 open blocker" in text
    assert "3 decision" in text
    assert "Billing" in text
    assert digest_service.headline(attention).endswith("need attention.")


def test_markdown_leads_with_attention() -> None:
    inp = _inputs(open_blockers=1)
    md = digest_service.render_markdown(inp, digest_service.attention_items(inp))
    assert "## Needs attention" in md
    assert md.index("## Needs attention") < md.index("## Status")


# --- API: function field + digest endpoint --------------------------------------

async def _seed_admin(session) -> None:
    session.add(
        User(email="a@e.com", hashed_password=hash_password("secret123"), role="admin")
    )
    await session.commit()


async def _token(client) -> str:
    resp = await client.post(
        "/api/v1/auth/login", data={"username": "a@e.com", "password": "secret123"}
    )
    return resp.json()["access_token"]


@pytest.mark.asyncio
async def test_register_sets_function(client, db_session) -> None:
    await _seed_admin(db_session)
    headers = {"Authorization": f"Bearer {await _token(client)}"}
    # admin defaults to engineering
    me = (await client.get("/api/v1/auth/me", headers=headers)).json()
    assert me["function"] == UserFunction.engineering

    created = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "pm@e.com",
            "password": "secret123",
            "role": "viewer",
            "function": "product",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["function"] == "product"


@pytest.mark.asyncio
async def test_initiative_digest_endpoint(client, db_session) -> None:
    await _seed_admin(db_session)
    headers = {"Authorization": f"Bearer {await _token(client)}"}
    initiative = (
        await client.post(
            "/api/v1/initiatives", json={"key": "Q3", "name": "Q3 Program"}, headers=headers
        )
    ).json()
    # an initiative-scoped outcome should appear in the digest
    await client.post(
        "/api/v1/outcomes",
        json={"scope_level": "initiative", "scope_id": initiative["id"], "statement": "Lift NPS"},
        headers=headers,
    )

    resp = await client.get(f"/api/v1/initiatives/{initiative['id']}/digest", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["initiative_id"] == initiative["id"]
    assert "headline" in body
    assert "# Q3 Program — weekly digest" in body["markdown"]
    assert any("Lift NPS" in o for o in body["outcomes"])
