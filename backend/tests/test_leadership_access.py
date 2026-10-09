"""Initiative lead teams (ownership-scoped editing, §R6) + leadership notes and the
business review (§BR)."""

import pytest

from app.core.security import hash_password
from app.models.base import UserRole
from app.models.user import User


async def _seed_admin(session) -> None:
    session.add(
        User(
            email="admin@example.com",
            hashed_password=hash_password("secret123"),
            role=UserRole.admin,
        )
    )
    await session.commit()


async def _token(client, email: str, password: str = "pw12345678") -> str:
    resp = await client.post(
        "/api/v1/auth/login", data={"username": email, "password": password}
    )
    return resp.json()["access_token"]


def _hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def world(client, db_session):
    """Admin + two architects (Ada leads initiative A; Bob leads nothing) + a CTO viewer, two
    initiatives with a project each, and engineers linked to the architects' logins."""
    await _seed_admin(db_session)
    admin = _hdr(await _token(client, "admin@example.com", "secret123"))
    people = {}
    for email, role, fn in (
        ("ada@example.com", "architect", "engineering"),
        ("bob@example.com", "architect", "product"),
        ("cto@example.com", "viewer", "leadership"),
        ("eng@example.com", "engineer", "engineering"),
    ):
        created = await client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": "pw12345678", "role": role, "function": fn},
            headers=admin,
        )
        assert created.status_code == 201, created.text
        people[email] = {"id": created.json()["id"], "h": _hdr(await _token(client, email))}
    # Engineers linked to Ada and Bob so lead seats can point at them.
    engs = {}
    for name, email in (("Ada", "ada@example.com"), ("Bob", "bob@example.com")):
        r = await client.post(
            "/api/v1/team/engineers",
            json={"name": name, "user_id": people[email]["id"]},
            headers=admin,
        )
        assert r.status_code == 201, r.text
        engs[name] = r.json()["id"]
    inits = {}
    projects = {}
    for key in ("A", "B"):
        i = await client.post(
            "/api/v1/initiatives", json={"key": key, "name": f"Init {key}"}, headers=admin
        )
        inits[key] = i.json()["id"]
        p = await client.post(
            "/api/v1/projects",
            json={"key": f"P{key}", "name": f"Project {key}", "initiative_id": inits[key]},
            headers=admin,
        )
        projects[key] = p.json()["id"]
    return admin, people, engs, inits, projects


@pytest.mark.asyncio
async def test_lead_team_scopes_planning_writes(client, world):
    admin, people, engs, inits, projects = world
    ada, bob = people["ada@example.com"]["h"], people["bob@example.com"]["h"]

    # No lead team yet → plain role rules: both architects may edit both initiatives.
    assert (
        await client.patch(
            f"/api/v1/initiatives/{inits['A']}", json={"status_note": "x"}, headers=bob
        )
    ).status_code == 200

    # Admin seats Ada as the technical lead of A.
    r = await client.put(
        f"/api/v1/initiatives/{inits['A']}/leads",
        json=[{"engineer_id": engs["Ada"], "lead_role": "technical"}],
        headers=admin,
    )
    assert r.status_code == 200 and r.json()[0]["engineer_name"] == "Ada"

    # Access map: Ada leads A; Bob leads nothing.
    acc = (await client.get("/api/v1/initiatives/access", headers=ada)).json()
    assert acc["led_initiative_ids"] == [inits["A"]]
    assert (await client.get("/api/v1/initiatives/access", headers=bob)).json()[
        "led_initiative_ids"
    ] == []

    # Rollup tells each user whether they may edit.
    assert (await client.get(f"/api/v1/initiatives/{inits['A']}/rollup", headers=ada)).json()[
        "can_edit"
    ] is True
    roll_bob = (await client.get(f"/api/v1/initiatives/{inits['A']}/rollup", headers=bob)).json()
    assert roll_bob["can_edit"] is False
    assert roll_bob["leads"][0]["lead_role"] == "technical"

    # Bob (a planner, not a lead) is read-only inside A: initiative, project, task writes 403...
    denied = await client.patch(
        f"/api/v1/initiatives/{inits['A']}", json={"status_note": "y"}, headers=bob
    )
    assert denied.status_code == 403 and denied.json()["detail"]["code"] == "not_initiative_lead"
    assert (
        await client.post(
            "/api/v1/tasks",
            json={"project_id": projects["A"], "name": "T", "duration": 2},
            headers=bob,
        )
    ).status_code == 403
    assert (
        await client.patch(
            f"/api/v1/projects/{projects['A']}", json={"status_note": "z"}, headers=bob
        )
    ).status_code == 403
    assert (
        await client.post(f"/api/v1/projects/{projects['A']}/replan", headers=bob)
    ).status_code == 403
    # ...but keeps full read access, and B (no leads) stays editable for Bob.
    assert (
        await client.get(f"/api/v1/projects/{projects['A']}/gantt", headers=bob)
    ).status_code == 200
    assert (
        await client.post(
            "/api/v1/tasks",
            json={"project_id": projects["B"], "name": "T", "duration": 2},
            headers=bob,
        )
    ).status_code == 201

    # Ada edits A freely; admin is exempt everywhere.
    task = await client.post(
        "/api/v1/tasks",
        json={"project_id": projects["A"], "name": "Lead task", "duration": 2},
        headers=ada,
    )
    assert task.status_code == 201
    assert (
        await client.patch(
            f"/api/v1/initiatives/{inits['A']}", json={"status_note": "admin"}, headers=admin
        )
    ).status_code == 200

    # Project access endpoint mirrors the decision and names the lead team.
    pa = (await client.get(f"/api/v1/projects/{projects['A']}/access", headers=bob)).json()
    assert pa["can_edit"] is False and pa["initiative_name"] == "Init A"
    assert [lead["engineer_name"] for lead in pa["leads"]] == ["Ada"]

    # Only an admin or a current lead may change the seats.
    assert (
        await client.put(
            f"/api/v1/initiatives/{inits['A']}/leads",
            json=[{"engineer_id": engs["Bob"], "lead_role": "product"}],
            headers=bob,
        )
    ).status_code == 403
    assert (
        await client.put(
            f"/api/v1/initiatives/{inits['A']}/leads",
            json=[
                {"engineer_id": engs["Ada"], "lead_role": "technical"},
                {"engineer_id": engs["Bob"], "lead_role": "product"},
            ],
            headers=ada,
        )
    ).status_code == 200
    assert (
        await client.patch(
            f"/api/v1/initiatives/{inits['A']}", json={"status_note": "now a lead"}, headers=bob
        )
    ).status_code == 200


@pytest.mark.asyncio
async def test_leadership_notes_and_business_review(client, world):
    admin, people, engs, inits, projects = world
    ada, bob = people["ada@example.com"]["h"], people["bob@example.com"]["h"]
    cto, eng = people["cto@example.com"]["h"], people["eng@example.com"]["h"]
    await client.put(
        f"/api/v1/initiatives/{inits['A']}/leads",
        json=[{"engineer_id": engs["Ada"], "lead_role": "technical"}],
        headers=admin,
    )
    adr = await client.post(
        "/api/v1/architecture/adrs",
        json={"project_id": projects["A"], "title": "Retention period", "status": "proposed"},
        headers=admin,
    )
    assert adr.status_code == 201, adr.text

    # Only the leadership persona (or admin) leaves notes; an engineer cannot.
    body = {
        "scope_level": "initiative",
        "scope_id": inits["A"],
        "kind": "priority",
        "priority": 1,
        "body": "Close the retention decision this week.",
        "target_kind": "decision",
        "target_id": adr.json()["id"],
    }
    denied = await client.post("/api/v1/leadership/notes", json=body, headers=eng)
    assert denied.status_code == 403
    note = await client.post("/api/v1/leadership/notes", json=body, headers=cto)
    assert note.status_code == 201, note.text
    note = note.json()
    assert note["target_label"].endswith("Retention period")
    assert note["author_name"] == "cto@example.com"
    # Unknown target → 404; a bad scope → 404.
    assert (
        await client.post(
            "/api/v1/leadership/notes",
            json={**body, "target_id": 9999},
            headers=cto,
        )
    ).status_code == 404

    # Reads are open; filters work.
    listed = (
        await client.get(
            f"/api/v1/leadership/notes?scope_level=initiative&scope_id={inits['A']}",
            headers=eng,
        )
    ).json()
    assert [n["id"] for n in listed] == [note["id"]]

    # Responding: Bob is not A's lead → 403; Ada (lead) acknowledges with a response.
    assert (
        await client.patch(
            f"/api/v1/leadership/notes/{note['id']}",
            json={"status": "acknowledged", "response": "On it."},
            headers=bob,
        )
    ).status_code == 403
    acked = await client.patch(
        f"/api/v1/leadership/notes/{note['id']}",
        json={"status": "acknowledged", "response": "Review booked for Thursday."},
        headers=ada,
    )
    assert acked.status_code == 200, acked.text
    assert acked.json()["status"] == "acknowledged"
    assert acked.json()["responded_by_name"] == "ada@example.com"
    # Only the author (or admin) edits the note's content.
    assert (
        await client.patch(
            f"/api/v1/leadership/notes/{note['id']}", json={"body": "x"}, headers=ada
        )
    ).status_code == 403

    # The business review rolls everything up, with the open note on A and an attention line.
    review = (await client.get("/api/v1/leadership/review", headers=cto)).json()
    by_key = {i["key"]: i for i in review["initiatives"]}
    assert set(by_key) == {"A", "B"}
    assert by_key["A"]["leads"][0]["engineer_name"] == "Ada"
    assert [n["id"] for n in by_key["A"]["open_notes"]] == [note["id"]]
    assert review["open_note_count"] == 1
    assert any("priority" in line for line in review["attention"]), review["attention"]

    # Resolving removes it from the review; deleting is author/admin only.
    await client.patch(
        f"/api/v1/leadership/notes/{note['id']}", json={"status": "resolved"}, headers=ada
    )
    review = (await client.get("/api/v1/leadership/review", headers=cto)).json()
    assert review["open_note_count"] == 0
    assert (
        await client.delete(f"/api/v1/leadership/notes/{note['id']}", headers=ada)
    ).status_code == 403
    assert (
        await client.delete(f"/api/v1/leadership/notes/{note['id']}", headers=cto)
    ).status_code == 204
