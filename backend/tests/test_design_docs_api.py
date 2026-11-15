"""Design docs (USER_FLOWS §V5-§V6): register, the sharing rule, personal docs, who may write,
links across projects, the open kind catalog, and the legacy add-link path."""

import pytest
from sqlmodel import select

from app.core.security import hash_password
from app.models.architecture import ArchitectureDecision
from app.models.base import UserRole
from app.models.doc import DocLink, DocReference, DocRevision
from app.models.feature import FeatureFlag
from app.models.project import Project, Task
from app.models.team import Engineer
from app.models.user import User

ART = "https://claude.ai/artifact"
DOC_ID = "Ab0CheckoutDesignDoc01"
API = "/api/v1"


async def _seed(session) -> dict[str, int]:
    users = {
        name: User(email=f"{name}@e.com", hashed_password=hash_password("secret123"), role=role)
        for name, role in {
            "admin": UserRole.admin,
            "arch": UserRole.architect,
            "other": UserRole.architect,
            "eng": UserRole.engineer,
            "eng2": UserRole.engineer,
            "viewer": UserRole.viewer,
        }.items()
    }
    session.add_all(users.values())
    await session.flush()
    engineers = {
        name: Engineer(name=name.title(), user_id=users[name].id)
        for name in ("arch", "eng", "eng2")
    }
    session.add_all(engineers.values())
    await session.flush()
    p1 = Project(key="P1", name="Checkout", owner_engineer_id=engineers["arch"].id)
    p2 = Project(key="P2", name="Payments", owner_engineer_id=engineers["arch"].id)
    session.add_all([p1, p2])
    await session.flush()
    t1 = Task(project_id=p1.id, name="Address step", assignee_engineer_id=engineers["eng"].id)
    t2 = Task(project_id=p1.id, name="Payment step", assignee_engineer_id=engineers["eng2"].id)
    t3 = Task(project_id=p2.id, name="Tokenize cards", assignee_engineer_id=engineers["eng"].id)
    session.add_all([t1, t2, t3])
    await session.flush()
    adr = ArchitectureDecision(project_id=p1.id, number=1, title="Server-side session")
    session.add(adr)
    await session.commit()
    return {
        "p1": p1.id, "p2": p2.id, "t1": t1.id, "t2": t2.id, "t3": t3.id, "adr": adr.id,
        **{f"user_{k}": v.id for k, v in users.items()},
    }


async def _h(client, name: str, *, agent: bool = False) -> dict[str, str]:
    resp = await client.post(
        f"{API}/auth/login", data={"username": f"{name}@e.com", "password": "secret123"}
    )
    token = resp.json()["access_token"]
    if agent:
        full = {"Authorization": f"Bearer {token}"}
        token = (await client.post(f"{API}/auth/agent-token", json={}, headers=full)).json()[
            "access_token"
        ]
    return {"Authorization": f"Bearer {token}"}


def _body(ids: dict[str, int], **over) -> dict:
    body = {
        "url": f"{ART}/{DOC_ID}",
        "title": "Checkout technical design",
        "kind": "tech_design",
        "format": "document",
        "summary": "Server-side session; single page.",
        "version": "r1",
        "visibility": "org",
        "scope_level": "project",
        "scope_id": ids["p1"],
    }
    body.update(over)
    return body


@pytest.mark.asyncio
async def test_register_is_idempotent_per_artifact_and_links(client, db_session) -> None:
    ids = await _seed(db_session)
    arch = await _h(client, "arch")
    first = await client.post(f"{API}/docs/register", json=_body(ids), headers=arch)
    assert first.status_code == 201, first.text
    doc = first.json()["doc"]
    assert first.json()["created"] is True
    assert (doc["provider"], doc["external_id"], doc["format"]) == ("claude", DOC_ID, "document")
    assert doc["review_status"] == "draft" and doc["current_version"] == "r1"
    assert doc["source"] == "manual" and doc["personal"] is False
    assert doc["kind_label"] == "Tech design" and doc["stage"] == "design"

    # the same artifact spelled with its title prefix + a basis link to the ADR
    again = await client.post(
        f"{API}/docs/register",
        json=_body(
            ids,
            url=f"{ART}/checkout-technical-design-{DOC_ID}",
            links=[{"entity_type": "decision", "entity_id": ids["adr"], "relation": "basis"}],
        ),
        headers=arch,
    )
    assert again.status_code == 200, again.text
    assert again.json()["created"] is False
    assert again.json()["doc"]["id"] == doc["id"]
    links = again.json()["doc"]["links"]
    assert [(lk["entity_type"], lk["relation"], lk["pinned_version"]) for lk in links] == [
        ("decision", "basis", "r1")
    ]
    assert links[0]["label"] == "ADR-0001 Server-side session"

    rows = (await db_session.execute(select(DocReference))).scalars().all()
    assert len(rows) == 1
    revisions = (await db_session.execute(select(DocRevision))).scalars().all()
    assert [r.version for r in revisions] == ["r1"]

    on_adr = await client.get(
        f"{API}/docs/links", params={"entity_type": "decision", "entity_id": ids["adr"]},
        headers=arch,
    )
    assert on_adr.status_code == 200
    assert [d["doc"]["id"] for d in on_adr.json()] == [doc["id"]]


@pytest.mark.asyncio
async def test_sharing_rule_refuses_private_claude_docs_on_shared_work(client, db_session) -> None:
    ids = await _seed(db_session)
    arch = await _h(client, "arch")
    for visibility in ("unknown", "owner"):
        resp = await client.post(
            f"{API}/docs/register", json=_body(ids, visibility=visibility), headers=arch
        )
        assert resp.status_code == 409, resp.text
        assert resp.json()["detail"]["code"] == "doc_not_shared"
    # people named in Claude count as shared
    named = await client.post(
        f"{API}/docs/register", json=_body(ids, visibility="users"), headers=arch
    )
    assert named.status_code == 201
    # a non-Claude link keeps today's behaviour (canopy does not track its sharing)
    drive = await client.post(
        f"{API}/docs/register",
        json=_body(ids, url="https://docs.google.com/document/d/x1/edit", visibility="unknown"),
        headers=arch,
    )
    assert drive.status_code == 201, drive.text
    # the legacy add-link form enforces the same rule for Claude links
    legacy = await client.post(
        f"{API}/docs",
        json={"scope_level": "project", "scope_id": ids["p2"],
              "url": f"{ART}/Zz9PrivateNotesOnly001", "kind": "prd"},
        headers=arch,
    )
    assert legacy.status_code == 409
    # a doc made private after sharing cannot gain new shared links
    doc_id = named.json()["doc"]["id"]
    await client.patch(f"{API}/docs/{doc_id}", json={"visibility": "owner"}, headers=arch)
    blocked = await client.post(
        f"{API}/docs/{doc_id}/links",
        json={"entity_type": "decision", "entity_id": ids["adr"], "relation": "basis"},
        headers=arch,
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "doc_not_shared"


@pytest.mark.asyncio
async def test_personal_docs_are_private_and_promote_needs_sharing(client, db_session) -> None:
    ids = await _seed(db_session)
    eng = await _h(client, "eng")
    mine = await client.post(
        f"{API}/docs/register",
        json={"url": f"{ART}/Pp0LatencyNotesForEng1", "title": "My notes", "kind": "research",
              "visibility": "owner", "personal": True},
        headers=eng,
    )
    assert mine.status_code == 201, mine.text
    doc = mine.json()["doc"]
    assert doc["personal"] is True and doc["review_status"] is None
    assert doc["scope_level"] is None

    # a personal doc links only to its owner's own tasks, as a reference
    own = await client.post(
        f"{API}/docs/{doc['id']}/links", json={"entity_type": "task", "entity_id": ids["t1"]},
        headers=eng,
    )
    assert own.status_code == 201, own.text
    other_task = await client.post(
        f"{API}/docs/{doc['id']}/links", json={"entity_type": "task", "entity_id": ids["t2"]},
        headers=eng,
    )
    assert other_task.status_code == 409

    # nobody else sees it: not the planner, not an admin, not an admin impersonating its owner
    for name in ("arch", "admin"):
        headers = await _h(client, name)
        assert (await client.get(f"{API}/docs/{doc['id']}", headers=headers)).status_code == 404
        listed = await client.get(f"{API}/docs", headers=headers)
        assert doc["id"] not in [d["id"] for d in listed.json()]
        task_links = await client.get(f"{API}/tasks/{ids['t1']}/links", headers=headers)
        assert task_links.json()["docs"] == []
    admin = await _h(client, "admin")
    imp = await client.post(f"{API}/auth/impersonate/{ids['user_eng']}", headers=admin)
    as_eng = {"Authorization": f"Bearer {imp.json()['access_token']}"}
    assert (await client.get(f"{API}/docs/{doc['id']}", headers=as_eng)).status_code == 404
    # …but its owner does, on their task too
    assert (await client.get(f"{API}/docs/{doc['id']}", headers=eng)).status_code == 200
    mine_only = await client.get(f"{API}/docs", params={"personal": True}, headers=eng)
    assert [d["id"] for d in mine_only.json()] == [doc["id"]]
    task_links = await client.get(f"{API}/tasks/{ids['t1']}/links", headers=eng)
    assert [d["id"] for d in task_links.json()["docs"]] == [doc["id"]]

    # promote: refused while private in Claude, accepted once shared
    refused = await client.post(
        f"{API}/docs/{doc['id']}/promote",
        json={"scope_level": "project", "scope_id": ids["p1"]}, headers=eng,
    )
    assert refused.status_code == 409
    promoted = await client.post(
        f"{API}/docs/{doc['id']}/promote",
        json={"scope_level": "project", "scope_id": ids["p1"], "visibility": "org"},
        headers=eng,
    )
    assert promoted.status_code == 200, promoted.text
    body = promoted.json()
    assert body["personal"] is False and body["review_status"] == "draft"
    assert (body["scope_level"], body["scope_id"]) == ("project", ids["p1"])
    arch = await _h(client, "arch")
    assert (await client.get(f"{API}/docs/{doc['id']}", headers=arch)).status_code == 200


@pytest.mark.asyncio
async def test_promote_folds_into_an_existing_shared_record(client, db_session) -> None:
    ids = await _seed(db_session)
    arch, eng = await _h(client, "arch"), await _h(client, "eng")
    shared = await client.post(f"{API}/docs/register", json=_body(ids), headers=arch)
    personal = await client.post(
        f"{API}/docs/register",
        json={"url": f"{ART}/{DOC_ID}#notes", "personal": True, "visibility": "org"},
        headers=eng,
    )
    # the doc is already tracked for everyone: no personal copy
    assert personal.json()["doc"]["id"] == shared.json()["doc"]["id"]
    assert personal.json()["created"] is False


@pytest.mark.asyncio
async def test_contributors_register_and_link_their_own_work(client, db_session) -> None:
    ids = await _seed(db_session)
    eng, eng2 = await _h(client, "eng"), await _h(client, "eng2")
    reg = await client.post(
        f"{API}/docs/register",
        json=_body(ids, links=[{"entity_type": "task", "entity_id": ids["t1"]}]),
        headers=eng,
    )
    assert reg.status_code == 201, reg.text
    doc_id = reg.json()["doc"]["id"]
    # not someone else's task, and not a decision
    for target in ({"entity_type": "task", "entity_id": ids["t2"]},
                   {"entity_type": "decision", "entity_id": ids["adr"], "relation": "basis"}):
        resp = await client.post(f"{API}/docs/{doc_id}/links", json=target, headers=eng)
        assert resp.status_code == 403, resp.text
    # another contributor cannot change it; the project's owner can
    assert (
        await client.patch(f"{API}/docs/{doc_id}", json={"title": "x"}, headers=eng2)
    ).status_code == 403
    arch = await _h(client, "arch")
    assert (
        await client.patch(f"{API}/docs/{doc_id}", json={"title": "Better"}, headers=arch)
    ).status_code == 200
    # a contributor files docs under a project, not an initiative-level home
    viewer = await _h(client, "viewer")
    assert (
        await client.post(f"{API}/docs/register", json=_body(ids, url=f"{ART}/Vv1ViewerDoc000001"),
                          headers=viewer)
    ).status_code == 403
    viewer_personal = await client.post(
        f"{API}/docs/register",
        json={"url": f"{ART}/Vv1ViewerDoc000001", "personal": True}, headers=viewer,
    )
    assert viewer_personal.status_code == 201


@pytest.mark.asyncio
async def test_planner_ownership_and_cross_project_links(client, db_session) -> None:
    ids = await _seed(db_session)
    other = await _h(client, "other")
    denied = await client.post(f"{API}/docs/register", json=_body(ids), headers=other)
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "not_initiative_lead"

    arch = await _h(client, "arch")
    doc_id = (await client.post(f"{API}/docs/register", json=_body(ids), headers=arch)).json()[
        "doc"
    ]["id"]
    # one PRD can serve two projects: link it to a task in the other project
    cross = await client.post(
        f"{API}/docs/{doc_id}/links", json={"entity_type": "task", "entity_id": ids["t3"]},
        headers=arch,
    )
    assert cross.status_code == 201, cross.text
    on_task = await client.get(
        f"{API}/docs", params={"scope_level": "task", "scope_id": ids["t3"]}, headers=arch
    )
    assert [d["id"] for d in on_task.json()] == [doc_id]
    # the other architect cannot hang it on the first project's work
    assert (
        await client.post(
            f"{API}/docs/{doc_id}/links",
            json={"entity_type": "decision", "entity_id": ids["adr"]}, headers=other,
        )
    ).status_code == 403
    # unlink + delete clean up after themselves
    link_id = cross.json()["id"]
    assert (await client.delete(f"{API}/docs/links/{link_id}", headers=arch)).status_code == 204
    assert (await client.delete(f"{API}/docs/{doc_id}", headers=arch)).status_code == 204
    assert (await db_session.execute(select(DocLink))).scalars().all() == []
    assert (await db_session.execute(select(DocRevision))).scalars().all() == []


@pytest.mark.asyncio
async def test_agent_registration_is_marked(client, db_session) -> None:
    ids = await _seed(db_session)
    agent = await _h(client, "arch", agent=True)
    resp = await client.post(f"{API}/docs/register", json=_body(ids), headers=agent)
    assert resp.status_code == 201, resp.text
    assert resp.json()["doc"]["source"] == "agent"


@pytest.mark.asyncio
async def test_kind_catalog_is_open(client, db_session) -> None:
    ids = await _seed(db_session)
    arch = await _h(client, "arch")
    reg = await client.post(
        f"{API}/docs/register", json=_body(ids, kind="Threat Model"), headers=arch
    )
    assert reg.json()["doc"]["kind"] == "threat_model"
    assert reg.json()["doc"]["stage"] == "other"
    kinds = {k["key"]: k for k in (await client.get(f"{API}/docs/kinds", headers=arch)).json()}
    assert kinds["threat_model"]["doc_count"] == 1
    assert kinds["prd"]["expected"] is True and kinds["prd"]["builtin"] is True

    staged = await client.put(
        f"{API}/docs/kinds/threat_model", json={"stage": "design", "label": "Threat model"},
        headers=arch,
    )
    assert staged.status_code == 200 and staged.json()["stage"] == "design"
    eng = await _h(client, "eng")
    assert (
        await client.put(f"{API}/docs/kinds/threat_model", json={"stage": "build"}, headers=eng)
    ).status_code == 403
    by_stage = await client.get(f"{API}/docs", params={"stage": "design"}, headers=arch)
    assert [d["kind"] for d in by_stage.json()] == ["threat_model"]

    # merging is admin-only and rewrites the docs
    assert (
        await client.post(f"{API}/docs/kinds/threat_model/merge", json={"into": "security"},
                          headers=arch)
    ).status_code == 403
    admin = await _h(client, "admin")
    merged = await client.post(
        f"{API}/docs/kinds/threat_model/merge", json={"into": "Security review"}, headers=admin
    )
    assert merged.json() == {"merged": 1, "into": "security_review"}
    doc = (await db_session.execute(select(DocReference))).scalars().one()
    await db_session.refresh(doc)
    assert doc.kind == "security_review"


@pytest.mark.asyncio
async def test_legacy_add_link_dedupes_into_a_link(client, db_session) -> None:
    ids = await _seed(db_session)
    arch = await _h(client, "arch")
    url = "https://docs.google.com/document/d/prd77/edit"
    first = await client.post(
        f"{API}/docs", json={"scope_level": "project", "scope_id": ids["p1"], "url": url,
                             "kind": "PRD"},
        headers=arch,
    )
    assert first.status_code == 201, first.text
    assert first.json()["kind"] == "prd" and first.json()["review_status"] is None
    second = await client.post(
        f"{API}/docs", json={"scope_level": "project", "scope_id": ids["p2"],
                             "url": "https://docs.google.com/document/d/prd77/view"},
        headers=arch,
    )
    assert second.json()["id"] == first.json()["id"]
    on_p2 = await client.get(
        f"{API}/docs", params={"scope_level": "project", "scope_id": ids["p2"]}, headers=arch
    )
    assert [d["id"] for d in on_p2.json()] == [first.json()["id"]]
    untracked = await client.get(
        f"{API}/docs", params={"review_status": "untracked"}, headers=arch
    )
    assert len(untracked.json()) == 1
    cov = await client.get(
        f"{API}/docs/coverage", params={"scope_level": "project", "scope_id": ids["p2"]},
        headers=arch,
    )
    assert "prd" in cov.json()["present"]
    expected = {e["kind"]: e["state"] for e in cov.json()["expected"]}
    assert expected["prd"] == "linked" and expected["design"] == "missing"


@pytest.mark.asyncio
async def test_design_docs_follow_the_docs_feature_gate(client, db_session) -> None:
    ids = await _seed(db_session)
    db_session.add(FeatureFlag(key="governance.docs", enabled=False))
    await db_session.commit()
    arch = await _h(client, "arch")
    resp = await client.post(f"{API}/docs/register", json=_body(ids), headers=arch)
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "feature_disabled"
