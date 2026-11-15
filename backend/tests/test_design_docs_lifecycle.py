"""Design docs wired into the lifecycle (USER_FLOWS §V9): pins at decision points, advisory
docs-readiness, an ADR from a doc's text, staged doc links with a source doc, draft plans that
carry their doc, design-doc tables in exports, and the retro seeder."""

import pytest
from sqlmodel import select

from app.models.doc import DocLink
from app.models.project import Task
from app.models.spec import Spec
from app.services.draft_sync import cite_doc
from tests.test_design_docs_api import API, ART, _body, _h, _seed


async def _register(client, ids, headers, **over) -> dict:
    resp = await client.post(f"{API}/docs/register", json=_body(ids, **over), headers=headers)
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["doc"]


async def _pin(db_session, doc_id: int, entity_type: str) -> str | None:
    link = (
        await db_session.execute(
            select(DocLink).where(DocLink.doc_id == doc_id, DocLink.entity_type == entity_type)
        )
    ).scalar_one()
    await db_session.refresh(link)
    return link.pinned_version


@pytest.mark.asyncio
async def test_accepting_a_decision_pins_its_docs_and_reports_readiness(client, db_session):
    ids = await _seed(db_session)
    arch = await _h(client, "arch")
    doc = await _register(
        client, ids, arch,
        links=[{"entity_type": "decision", "entity_id": ids["adr"], "relation": "basis"}],
    )
    assert await _pin(db_session, doc["id"], "decision") == "r1"
    await client.post(f"{API}/docs/{doc['id']}/revisions", json={"version": "r2"}, headers=arch)

    review = (await client.get(f"{API}/architecture/adrs/{ids['adr']}", headers=arch)).json()[
        "review"
    ]
    assert review["docs_ready"] is False
    assert review["docs_pending"] == ["Checkout technical design"]
    assert review["can_accept"] is True  # readiness is advisory, like the rule check

    accepted = await client.patch(
        f"{API}/architecture/adrs/{ids['adr']}", json={"status": "accepted"}, headers=arch
    )
    assert accepted.status_code == 200, accepted.text
    assert await _pin(db_session, doc["id"], "decision") == "r2"  # pinned at acceptance


@pytest.mark.asyncio
async def test_approving_a_spec_pins_and_reports_its_source_docs(client, db_session):
    ids = await _seed(db_session)
    spec = Spec(project_id=ids["p1"], title="One-page checkout", problem="Five steps is slow")
    db_session.add(spec)
    await db_session.commit()
    arch = await _h(client, "arch")
    doc = await _register(
        client, ids, arch, kind="prd",
        links=[{"entity_type": "spec", "entity_id": spec.id, "relation": "basis"}],
    )
    bundle = (await client.get(f"{API}/specs/{spec.id}", headers=arch)).json()
    assert bundle["docs_ready"] is False and bundle["docs_pending"] == [doc["title"]]

    await client.post(f"{API}/docs/{doc['id']}/request-review", json={}, headers=arch)
    await client.post(f"{API}/docs/{doc['id']}/approve", json={}, headers=arch)
    assert (await client.get(f"{API}/specs/{spec.id}", headers=arch)).json()["docs_ready"]

    await client.post(f"{API}/docs/{doc['id']}/revisions", json={"version": "r5"}, headers=arch)
    approved = await client.patch(
        f"{API}/specs/{spec.id}", json={"status": "approved"}, headers=arch
    )
    assert approved.status_code == 200, approved.text
    assert await _pin(db_session, doc["id"], "spec") == "r5"


@pytest.mark.asyncio
async def test_a_baseline_pins_the_plans_basis_docs(client, db_session):
    ids = await _seed(db_session)
    arch = await _h(client, "arch")
    doc = await _register(
        client, ids, arch,
        links=[{"entity_type": "task", "entity_id": ids["t1"], "relation": "basis"}],
    )
    await client.post(f"{API}/docs/{doc['id']}/revisions", json={"version": "r3"}, headers=arch)
    resp = await client.post(
        f"{API}/projects/{ids['p1']}/baseline", json={"note": "Plan of record"}, headers=arch
    )
    assert resp.status_code == 201, resp.text
    assert await _pin(db_session, doc["id"], "task") == "r3"


@pytest.mark.asyncio
async def test_an_adr_from_a_docs_text_links_the_doc_as_its_basis(client, db_session):
    ids = await _seed(db_session)
    arch = await _h(client, "arch")
    doc = await _register(client, ids, arch, version="r7")
    markdown = (
        "# Use a server-side checkout session\n\n## Context\nState lives in the browser.\n\n"
        "## Decision\nKeep it on the server.\n\n## Consequences\nOne more service."
    )
    resp = await client.post(
        f"{API}/architecture/adrs/import-text",
        json={"project_id": ids["p1"], "markdown": markdown, "doc_id": doc["id"]},
        headers=arch,
    )
    assert resp.status_code == 201, resp.text
    adr = resp.json()
    assert adr["title"] == "Use a server-side checkout session"
    assert adr["decision"] == "Keep it on the server."
    linked = (
        await client.get(
            f"{API}/docs/links", params={"entity_type": "decision", "entity_id": adr["id"]},
            headers=arch,
        )
    ).json()
    assert [(e["link"]["relation"], e["link"]["pinned_version"]) for e in linked] == [
        ("basis", "r7")
    ]
    # contributors cannot create ADRs this way
    eng = await _h(client, "eng")
    assert (
        await client.post(
            f"{API}/architecture/adrs/import-text",
            json={"project_id": ids["p1"], "markdown": markdown}, headers=eng,
        )
    ).status_code == 403


@pytest.mark.asyncio
async def test_staged_doc_links_with_a_source_doc(client, db_session):
    ids = await _seed(db_session)
    arch = await _h(client, "arch")
    doc = await _register(client, ids, arch, version="r2")

    def stage(items: list[dict], **extra):
        return client.post(
            f"{API}/proposals",
            json={"scope_level": "project", "scope_id": ids["p1"], "title": "From the design",
                  "items": items, **extra},
            headers=arch,
        )

    # a new task staged together with a link from the doc to it (by ref)
    created = await stage(
        [
            {"entity_type": "task", "action": "create", "ref": "step",
             "payload": {"name": "Retry the payment step", "duration": 2}},
            {"entity_type": "doc_link", "action": "create",
             "payload": {"doc_id": doc["id"], "entity_type": "task", "entity_ref": "step",
                         "relation": "basis"}},
            {"entity_type": "doc_link", "action": "create",
             "payload": {"doc_id": doc["id"], "entity_type": "decision",
                         "entity_id": ids["adr"]}},
        ],
        source_doc_id=doc["id"], source_doc_version="r2",
    )
    assert created.status_code == 201, created.text
    proposal = created.json()
    assert proposal["source_doc"]["moved_on"] is False
    assert proposal["lookups"]["doc"] == {str(doc["id"]): "Checkout technical design"}

    # the doc moves on while the proposal waits: the review says so
    await client.post(f"{API}/docs/{doc['id']}/revisions", json={"version": "r3"}, headers=arch)
    again = (await client.get(f"{API}/proposals/{proposal['id']}", headers=arch)).json()
    assert again["source_doc"]["moved_on"] is True
    preview = (
        await client.get(f"{API}/proposals/{proposal['id']}/preview", headers=arch)
    ).json()
    assert preview["counts"]["docs_linked"] == 2

    applied = await client.post(f"{API}/proposals/{proposal['id']}/apply", headers=arch)
    assert applied.status_code == 200, applied.text
    task = (
        await db_session.execute(select(Task).where(Task.name == "Retry the payment step"))
    ).scalar_one()
    links = {
        (lk.entity_type, lk.entity_id, lk.relation)
        for lk in (
            await db_session.execute(select(DocLink).where(DocLink.doc_id == doc["id"]))
        ).scalars().all()
    }
    assert ("task", task.id, "basis") in links
    assert ("decision", ids["adr"], "reference") in links

    # refusals: a target outside the scope, a ref of the wrong kind, a personal source doc
    outside = await stage([
        {"entity_type": "doc_link", "action": "create",
         "payload": {"doc_id": doc["id"], "entity_type": "task", "entity_id": ids["t3"]}},
    ])
    assert outside.status_code == 400 and "outside this proposal" in outside.text
    wrong = await stage([
        {"entity_type": "milestone", "action": "create", "ref": "m",
         "payload": {"name": "GA"}},
        {"entity_type": "doc_link", "action": "create",
         "payload": {"doc_id": doc["id"], "entity_type": "task", "entity_ref": "m"}},
    ])
    assert wrong.status_code == 400 and "does not name a task" in wrong.text
    personal = (
        await client.post(
            f"{API}/docs/register",
            json={"url": f"{ART}/Pers0NotesForArch0002", "personal": True}, headers=arch,
        )
    ).json()["doc"]
    bad_source = await stage(
        [{"entity_type": "task", "action": "create", "payload": {"name": "x"}}],
        source_doc_id=personal["id"],
    )
    assert bad_source.status_code == 422


@pytest.mark.asyncio
async def test_draft_plans_carry_their_doc_into_tasks(client, db_session):
    ids = await _seed(db_session)
    arch = await _h(client, "arch")
    doc = await _register(client, ids, arch, version="r4")
    plan = await client.post(
        f"{API}/projects/{ids['p1']}/draft-plans",
        json={"title": "From the design", "source_doc_id": doc["id"], "source_doc_version": "r4"},
        headers=arch,
    )
    assert plan.status_code == 201, plan.text
    assert plan.json()["source_doc_version"] == "r4"
    plan_id = plan.json()["id"]
    await client.post(
        f"{API}/draft-plans/{plan_id}/tasks", json={"name": "Build the session API",
                                                    "estimate_days": 3},
        headers=arch,
    )
    done = await client.post(f"{API}/draft-plans/{plan_id}/finalize", json={}, headers=arch)
    assert done.status_code == 200, done.text
    task = (
        await db_session.execute(select(Task).where(Task.name == "Build the session API"))
    ).scalar_one()
    on_task = (
        await client.get(
            f"{API}/docs/links", params={"entity_type": "task", "entity_id": task.id},
            headers=arch,
        )
    ).json()
    assert [(e["doc"]["id"], e["link"]["relation"]) for e in on_task] == [
        (doc["id"], "reference")
    ]


def test_ticket_citation_is_idempotent() -> None:
    class _Doc:
        title = "Checkout design"
        url = "https://claude.ai/artifact/Ab0CheckoutDesignDoc01"

    doc = _Doc()
    cited = cite_doc("Build it.", doc)  # type: ignore[arg-type]
    assert cited == "Build it.\n\nDesign doc: Checkout design — " + doc.url
    assert cite_doc(cited, doc) == cited  # type: ignore[arg-type]
    assert cite_doc(None, doc).startswith("Design doc:")  # type: ignore[arg-type]
    assert cite_doc("x", None) == "x"


@pytest.mark.asyncio
async def test_exports_and_retros_list_the_design_docs(client, db_session):
    ids = await _seed(db_session)
    arch = await _h(client, "arch")
    doc = await _register(client, ids, arch, version="r1")
    await client.post(f"{API}/docs/{doc['id']}/request-review", json={}, headers=arch)
    await client.post(f"{API}/docs/{doc['id']}/approve", json={}, headers=arch)
    await client.post(f"{API}/docs/{doc['id']}/revisions", json={"version": "r2"}, headers=arch)
    personal = await client.post(
        f"{API}/docs/register",
        json={"url": f"{ART}/Pers0NotesForArch0003", "title": "Private notes",
              "personal": True, "scope_level": "project", "scope_id": ids["p1"]},
        headers=arch,
    )
    assert personal.status_code == 201

    csv_text = (
        await client.get(f"{API}/projects/{ids['p1']}/export?fmt=csv", headers=arch)
    ).text
    assert "Design docs" in csv_text
    assert "Checkout technical design,Tech design,approved,\"r1 approved, now r2\"" in csv_text
    assert "Private notes" not in csv_text
    pdf = await client.get(f"{API}/projects/{ids['p1']}/export?fmt=pdf", headers=arch)
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"

    seeded = await client.post(
        f"{API}/projects/{ids['p1']}/retrospectives", json={"title": "Retro"}, headers=arch
    )
    assert seeded.status_code == 201, seeded.text
    body = seeded.json()["body"]
    assert "## Design docs that changed after approval" in body
    assert "Checkout technical design (approved r1, now r2)" in body


@pytest.mark.asyncio
async def test_my_snapshot_store_preference(client, db_session):
    await _seed(db_session)
    eng = await _h(client, "eng")
    resp = await client.patch(
        f"{API}/auth/me/preferences", json={"doc_snapshot_store": "repo"}, headers=eng
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["doc_snapshot_store"] == "repo"
    bad = await client.patch(
        f"{API}/auth/me/preferences", json={"doc_snapshot_store": "dropbox"}, headers=eng
    )
    assert bad.status_code == 422
