"""Design-doc versions, review and approval, and where health surfaces (USER_FLOWS §V8)."""

from datetime import date, timedelta

import pytest
from sqlmodel import select

from app.models.doc import DocRevision
from app.models.project import Initiative, Milestone, Project
from tests.test_design_docs_api import API, ART, _body, _h, _seed


async def _register(client, ids, headers, **over) -> dict:
    resp = await client.post(f"{API}/docs/register", json=_body(ids, **over), headers=headers)
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["doc"]


@pytest.mark.asyncio
async def test_versions_review_and_human_approval(client, db_session) -> None:
    ids = await _seed(db_session)
    arch = await _h(client, "arch")
    doc = await _register(client, ids, arch)
    assert doc["health"] == [
        {"flag": "unverified", "severity": "info", "message": doc["health"][0]["message"],
         "entity_type": None, "entity_id": None}
    ]

    # a check records the version it saw; the same version again adds no log row
    seen = await client.post(
        f"{API}/docs/{doc['id']}/revisions",
        json={"version": "r2", "content_hash": "a" * 64, "change_summary": "Retries added"},
        headers=arch,
    )
    assert seen.status_code == 200, seen.text
    assert seen.json()["new_version"] is True
    assert seen.json()["doc"]["current_version"] == "r2"
    assert seen.json()["doc"]["health"] == []  # checked now: no longer unverified
    again = await client.post(
        f"{API}/docs/{doc['id']}/revisions", json={"version": "r2"}, headers=arch
    )
    assert again.json()["new_version"] is False and again.json()["revision"] is None
    detail = (await client.get(f"{API}/docs/{doc['id']}", headers=arch)).json()
    assert [r["version"] for r in detail["revisions"]] == ["r2", "r1"]
    assert detail["revisions"][0]["content_hash"] == "a" * 64

    # review → approval is a human planner's act
    reviewed = await client.post(
        f"{API}/docs/{doc['id']}/request-review", json={}, headers=await _h(client, "eng")
    )
    assert reviewed.status_code == 403  # not the eng's doc
    reviewed = await client.post(f"{API}/docs/{doc['id']}/request-review", json={}, headers=arch)
    assert reviewed.json()["review_status"] == "in_review"
    assert reviewed.json()["review_version"] == "r2"

    workspace = (await client.get(f"{API}/me/workspace", headers=arch)).json()
    assert [d["id"] for d in workspace["docs_to_review"]] == [doc["id"]]
    other_ws = (await client.get(f"{API}/me/workspace", headers=await _h(client, "other"))).json()
    assert other_ws["docs_to_review"] == []  # not their project

    agent = await _h(client, "arch", agent=True)
    assert (
        await client.post(f"{API}/docs/{doc['id']}/approve", json={}, headers=agent)
    ).status_code == 403
    approved = await client.post(f"{API}/docs/{doc['id']}/approve", json={}, headers=arch)
    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["review_status"] == "approved"
    assert body["approved_version"] == "r2" and body["approved_by_user_id"] == ids["user_arch"]

    # the doc moves on after approval: still approved, flagged
    await client.post(f"{API}/docs/{doc['id']}/revisions", json={"version": "r3"}, headers=arch)
    moved = (await client.get(f"{API}/docs/{doc['id']}", headers=arch)).json()
    assert moved["review_status"] == "approved"
    assert [f["flag"] for f in moved["health"]] == ["changed_since_approval"]

    # it shows on the project's alerts and in coverage
    alerts = (
        await client.get(f"{API}/projects/{ids['p1']}/alerts", headers=arch)
    ).json()["alerts"]
    doc_alerts = [a for a in alerts if a["kind"].startswith("doc_")]
    assert [(a["kind"], a["entity_type"], a["entity_id"]) for a in doc_alerts] == [
        ("doc_changed_since_approval", "doc", doc["id"])
    ]
    cov = (
        await client.get(
            f"{API}/docs/coverage", params={"scope_level": "project", "scope_id": ids["p1"]},
            headers=arch,
        )
    ).json()
    assert {e["kind"]: e["state"] for e in cov["expected"]}["tech_design"] == "approved"
    assert cov["needs_attention"] == 1


@pytest.mark.asyncio
async def test_review_and_approval_refusals(client, db_session) -> None:
    ids = await _seed(db_session)
    arch, eng = await _h(client, "arch"), await _h(client, "eng")
    # a contributor's own doc: they request review, they cannot approve it
    mine = await _register(client, ids, eng, url=f"{ART}/Eng0ContributorDesign1")
    assert (
        await client.post(f"{API}/docs/{mine['id']}/request-review", json={}, headers=eng)
    ).status_code == 200
    refused = await client.post(f"{API}/docs/{mine['id']}/approve", json={}, headers=eng)
    assert refused.status_code == 403
    assert refused.json()["detail"]["code"] == "not_approver"
    # the project's owner approves it
    assert (
        await client.post(f"{API}/docs/{mine['id']}/approve", json={}, headers=arch)
    ).status_code == 200

    # a doc made private in Claude cannot be put up for review or approved
    shared = await _register(client, ids, arch, url=f"{ART}/Arch0SharedDesignDoc1")
    await client.post(
        f"{API}/docs/{shared['id']}/revisions", json={"visibility": "owner"}, headers=arch
    )
    flags = (await client.get(f"{API}/docs/{shared['id']}", headers=arch)).json()["health"]
    assert "restricted" in [f["flag"] for f in flags]
    for action in ("request-review", "approve"):
        resp = await client.post(f"{API}/docs/{shared['id']}/{action}", json={}, headers=arch)
        assert resp.status_code == 409, (action, resp.text)
        assert resp.json()["detail"]["code"] == "doc_not_shared"

    # a personal doc has no review
    personal = (
        await client.post(
            f"{API}/docs/register",
            json={"url": f"{ART}/Pers0NotesForArch0001", "personal": True}, headers=arch,
        )
    ).json()["doc"]
    resp = await client.post(f"{API}/docs/{personal['id']}/request-review", json={}, headers=arch)
    assert resp.status_code == 409 and resp.json()["detail"]["code"] == "doc_personal"

    # a check that cannot open the doc marks it broken; archiving retires it
    await client.post(f"{API}/docs/{shared['id']}/revisions", json={"reachable": False},
                      headers=arch)
    broken = (await client.get(f"{API}/docs/{shared['id']}", headers=arch)).json()
    assert broken["link_health"] == "broken"
    assert "broken" in [f["flag"] for f in broken["health"]]
    archived = await client.post(f"{API}/docs/{shared['id']}/archive", headers=arch)
    assert archived.json()["review_status"] == "archived"
    assert archived.json()["health"] == []


@pytest.mark.asyncio
async def test_gates_pins_worklist_and_digest(client, db_session) -> None:
    ids = await _seed(db_session)
    initiative = Initiative(key="INI", name="Checkout program")
    db_session.add(initiative)
    await db_session.flush()
    project = await db_session.get(Project, ids["p1"])
    project.initiative_id = initiative.id
    milestone = Milestone(
        project_id=ids["p1"], name="Checkout GA", target_date=date.today() + timedelta(days=5)
    )
    db_session.add(milestone)
    await db_session.commit()

    arch = await _h(client, "arch")
    doc = await _register(
        client, ids, arch,
        links=[
            {"entity_type": "milestone", "entity_id": milestone.id, "relation": "gate"},
            {"entity_type": "decision", "entity_id": ids["adr"], "relation": "basis"},
        ],
    )
    # never opened by a session → on the worklist
    worklist = (await client.get(f"{API}/docs/worklist", headers=arch)).json()
    assert worklist["total"] == 1 and worklist["docs"][0]["id"] == doc["id"]
    await client.post(f"{API}/docs/{doc['id']}/revisions", json={"version": "r9"}, headers=arch)
    assert (await client.get(f"{API}/docs/worklist", headers=arch)).json()["total"] == 0

    flags = {
        f["flag"]: f for f in (await client.get(f"{API}/docs/{doc['id']}", headers=arch)).json()[
            "health"
        ]
    }
    assert flags["gate_open"]["entity_type"] == "milestone"
    assert flags["behind_pin"]["entity_id"] == ids["adr"]  # pinned r1, now r9

    digest = (
        await client.get(f"{API}/initiatives/{initiative.id}/digest", headers=arch)
    ).json()
    text = " ".join(digest["attention"])
    assert "waits on 'Checkout technical design'" in text
    assert "ADR-0001 Server-side session was based on" in text


@pytest.mark.asyncio
async def test_revision_log_keeps_snapshot_links(client, db_session) -> None:
    ids = await _seed(db_session)
    arch = await _h(client, "arch")
    doc = await _register(client, ids, arch)
    await client.post(
        f"{API}/docs/{doc['id']}/revisions",
        json={"version": "r1", "snapshot_url": "https://github.com/acme/shop/blob/main/docs/d.md"},
        headers=arch,
    )
    rows = (await db_session.execute(select(DocRevision))).scalars().all()
    assert [(r.version, r.snapshot_url) for r in rows] == [
        ("r1", "https://github.com/acme/shop/blob/main/docs/d.md")
    ]
