"""The organization artifact sync (USER_FLOWS §V11): the metadata-only Compliance API connector,
pairing tracked Claude docs with listed artifacts, what a run records (versions, sharing,
source changes, missing artifacts), the admin-only connection, a person's own suggestions, the
worker jobs, and the `/docs` team filter."""

from datetime import datetime, timedelta

import httpx
import pytest
from sqlmodel import select

from app.connectors.claude_artifacts import (
    LIST_PATH,
    ArtifactListing,
    ArtifactMeta,
    ClaudeArtifactsConnector,
    candidate_ids,
    parse_artifact,
    parse_time,
)
from app.core.config import settings
from app.core.crypto import encrypt_token
from app.core.security import hash_password
from app.models.base import DocReviewStatus, Provider, UserRole, utcnow
from app.models.doc import DocReference, DocRevision
from app.models.integration import Connection, ExternalRef
from app.models.org import Team
from app.models.project import Initiative, Project
from app.models.user import User
from app.services import claude_sync, design_docs
from app.services.design_docs import SYNC_DOC_ENTITY

API = "/api/v1"
ART = "https://claude.ai/artifact"
DOMAIN = "shop.example.com"  # the demo Compliance API mock's owners


# --- pure ------------------------------------------------------------------------------------


def test_parse_artifact_reads_metadata_only():
    meta = parse_artifact({
        "id": "cart_01Abc",
        "artifact_type": "code",
        "owner_user_id": "user_01X",
        "published_version_id": "v2",
        "read_mode": "org",
        "updated_at": "2026-03-14T09:05:17.456789Z",
        "user": {"id": "user_01X", "email_address": "Jane.Doe@Example.com"},
        "versions": [
            {"id": "v1", "created_at": "2026-03-01T00:00:00Z", "name": "Old title"},
            {"id": "v2", "created_at": "2026-03-12T18:22:41Z", "name": "Team dashboard"},
        ],
    })
    assert meta is not None
    assert meta.owner_email == "jane.doe@example.com"
    assert meta.title == "Team dashboard"  # the newest version's name
    assert meta.version_label == "v2"
    assert meta.updated_at == datetime(2026, 3, 14, 9, 5, 17, 456789)  # naive UTC
    assert meta.updated_at.tzinfo is None

    doc = parse_artifact({"id": "cart_01Doc", "artifact_type": "claude_docs",
                          "published_version_id": None, "read_mode": "users", "user": None,
                          "versions": []})
    assert doc is not None and doc.version_label is None and doc.owner_email is None
    assert parse_artifact({"artifact_type": "code"}) is None
    assert parse_time("2026-01-01T10:00:00+02:00") == datetime(2026, 1, 1, 8, 0)
    assert parse_time("not a date") is None


def test_candidate_ids_try_each_documented_link_form():
    ids = candidate_ids("cart_01FeJDTrUMxp1SgJzj8o4inL")
    assert {"cart_01FeJDTrUMxp1SgJzj8o4inL", "01FeJDTrUMxp1SgJzj8o4inL",
            "FeJDTrUMxp1SgJzj8o4inL"} <= ids
    uuids = [i for i in ids if i.count("-") == 4]
    assert len(uuids) == 1 and len(uuids[0]) == 36  # the body read as a base58 UUID
    assert candidate_ids("plainid") == {"plainid"}


# --- the connector: list endpoint only, headers, pagination -----------------------------------


async def test_connector_pages_through_the_list_endpoint_only(db_session, monkeypatch):
    seen: list[httpx.Request] = []
    pages = {
        None: {"data": [{"id": "cart_01A", "read_mode": "org"}], "next_page": "p2"},
        "p2": {"data": [], "has_more": True, "next_page": "p3"},  # short page, keep going
        "p3": {"data": [{"id": "cart_01B", "read_mode": "owner"}], "next_page": None},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=pages[request.url.params.get("page")])

    original = ClaudeArtifactsConnector._client

    def patched(self: ClaudeArtifactsConnector) -> httpx.AsyncClient:
        real = original(self)
        return httpx.AsyncClient(
            base_url=real.base_url, headers=real.headers, transport=httpx.MockTransport(handler)
        )

    monkeypatch.setattr(ClaudeArtifactsConnector, "_client", patched)
    connection = Connection(provider=Provider.claude, name="Claude",
                            config={"organization_ids": ["org_1"]},
                            encrypted_token=encrypt_token("compliance-key"))
    db_session.add(connection)
    await db_session.commit()
    connector = ClaudeArtifactsConnector(connection, db_session)

    since = datetime(2026, 11, 1, 12, 0, 0)
    listing = await connector.list_artifacts(updated_since=since, user_ids=["user_01X"])
    assert [a.id for a in listing.items] == ["cart_01A", "cart_01B"] and listing.complete
    assert len(seen) == 3
    for request in seen:
        assert request.method == "GET" and request.url.path == LIST_PATH
        assert request.url.host == "api.anthropic.com"
        assert request.headers["authorization"] == "Bearer compliance-key"
        assert request.headers["anthropic-version"] == "2026-10-21"
        assert request.url.params["updated_at[gte]"] == "2026-11-01T12:00:00Z"
        assert request.url.params.get_list("user_ids[]") == ["user_01X"]
        assert request.url.params.get_list("organization_ids[]") == ["org_1"]

    capped = await connector.list_artifacts(max_pages=1)
    assert not capped.complete  # the cap cut it short: absence proves nothing


# --- applying a listing -------------------------------------------------------------------------


def _artifact(artifact_id: str, **over) -> ArtifactMeta:
    values = {
        "id": artifact_id, "artifact_type": "code", "read_mode": "org",
        "owner_user_id": None, "owner_email": None, "updated_at": utcnow(),
        "published_version_id": "v2", "latest_version_id": "v2", "title": "Checkout prototype",
    }
    values.update(over)
    return ArtifactMeta(**values)


async def _doc(session, link_id: str, **over) -> DocReference:
    values = {
        "url": f"{ART}/{link_id}", "provider": "claude", "external_id": link_id,
        "title": "Checkout prototype", "kind": "design", "visibility": "org",
        "review_status": DocReviewStatus.draft.value, "current_version": "v1",
    }
    values.update(over)
    doc = DocReference(**values)
    session.add(doc)
    await session.flush()
    return doc


async def test_a_listed_artifact_updates_the_doc_it_pairs_with(db_session):
    doc = await _doc(db_session, "Ab0CheckoutPrototype01")
    listing = ArtifactListing([_artifact("cart_01Ab0CheckoutPrototype01")])

    report = await claude_sync.apply_listing(db_session, listing, connection_id=None, full=False)
    assert (report.paired, report.newly_paired, report.new_versions, report.updated) == (1, 1, 1, 1)
    assert doc.current_version == "v2" and doc.last_checked_at is not None
    assert str(doc.link_health) == "ok"
    revision = (await db_session.execute(
        select(DocRevision).where(DocRevision.doc_id == doc.id)
    )).scalars().one()
    assert (revision.version, revision.source, revision.content_hash) == ("v2", "sync", None)
    ref = (await db_session.execute(select(ExternalRef))).scalars().one()
    assert (ref.provider, ref.entity_type, ref.entity_id) == (
        Provider.claude, SYNC_DOC_ENTITY, doc.id
    )

    again = await claude_sync.apply_listing(db_session, listing, connection_id=None, full=False)
    assert (again.newly_paired, again.new_versions) == (0, 0)  # idempotent


async def test_sharing_and_source_changes_raise_the_right_flags(db_session):
    old_check = utcnow() - timedelta(days=2)
    shared = await _doc(db_session, "Ab0SharedPageArtifact1", last_checked_at=old_check)
    claude_doc = await _doc(
        db_session, "Ab0ApprovedClaudeDoc01", format="document",
        review_status=DocReviewStatus.approved.value, approved_version="r3",
        current_version="r3", approved_at=old_check, last_checked_at=old_check,
    )
    listing = ArtifactListing([
        _artifact("cart_01Ab0SharedPageArtifact1", read_mode="owner"),
        _artifact("cart_01Ab0ApprovedClaudeDoc01", artifact_type="claude_docs",
                  published_version_id=None, latest_version_id=None, title=None),
    ])
    report = await claude_sync.apply_listing(db_session, listing, connection_id=None, full=False)
    assert report.sharing_changed == 1
    assert shared.visibility == "owner"
    # a Claude Doc lists no version: only the source's change time moves, the check does not
    assert claude_doc.current_version == "r3" and claude_doc.last_checked_at == old_check
    assert claude_doc.source_updated_at is not None

    health = await design_docs.health_for(db_session, [shared, claude_doc])
    assert "restricted" in {f.flag for f in health[shared.id]}
    doc_flags = {f.flag: f.message for f in health[claude_doc.id]}
    assert "changed in Claude after its last check" in doc_flags["check_due"]
    assert "edited in Claude after it was approved" in doc_flags["changed_since_approval"]


async def test_only_a_complete_unfiltered_listing_marks_docs_missing(db_session):
    gone = await _doc(db_session, "Ab0DeletedArtifact0001")
    await _doc(db_session, "Ab0NeverPairedDoc00001")  # a tracked doc the listing never names
    first = ArtifactListing([_artifact("cart_01Ab0DeletedArtifact0001")])
    await claude_sync.apply_listing(db_session, first, connection_id=None, full=True)

    empty = ArtifactListing([])
    filtered = await claude_sync.apply_listing(db_session, empty, connection_id=None, full=False)
    assert filtered.missing == 0 and str(gone.link_health) == "ok"
    partial = await claude_sync.apply_listing(
        db_session, ArtifactListing([], complete=False), connection_id=None, full=True
    )
    assert partial.missing == 0 and partial.unmatched is None

    report = await claude_sync.apply_listing(db_session, empty, connection_id=None, full=True)
    assert report.missing == 1 and str(gone.link_health) == "broken"
    assert report.unmatched == 1  # the never-paired doc, counted so an admin can see it
    flags = (await design_docs.health_for(db_session, [gone]))[gone.id]
    assert "broken" in {f.flag for f in flags}


async def test_personal_copies_follow_the_shared_pairing(db_session):
    owner = User(email=f"leo@{DOMAIN}", hashed_password="x", role=UserRole.engineer)
    db_session.add(owner)
    await db_session.flush()
    shared = await _doc(db_session, "Ab0PairedEverywhere001")
    copy = await _doc(db_session, "Ab0PairedEverywhere001", private_to_user_id=owner.id,
                      review_status=None, scope_level=None)
    listing = ArtifactListing([_artifact(
        "cart_01Ab0PairedEverywhere001", owner_user_id="user_01Leo", owner_email=f"leo@{DOMAIN}",
    )])
    report = await claude_sync.apply_listing(db_session, listing, connection_id=None, full=False)
    assert report.paired == 2 and report.identities == 1
    assert shared.current_version == copy.current_version == "v2"
    refs = (await db_session.execute(select(ExternalRef))).scalars().all()
    by_type = {r.entity_type: r for r in refs}
    assert by_type[SYNC_DOC_ENTITY].entity_id == shared.id  # one pairing, the shared doc
    assert (by_type["user"].external_id, by_type["user"].entity_id) == ("user_01Leo", owner.id)


# --- the API, over the offline Compliance API mock ----------------------------------------------


async def _users(session) -> dict[str, int]:
    rows = {
        "admin": UserRole.admin, "rahul": UserRole.architect, "leo": UserRole.engineer,
        "sarah": UserRole.architect,
    }
    users = {
        name: User(email=f"{name}@{DOMAIN}", hashed_password=hash_password("secret123"),
                   role=role)
        for name, role in rows.items()
    }
    session.add_all(users.values())
    await session.commit()
    return {name: u.id for name, u in users.items()}


async def _h(client, name: str) -> dict[str, str]:
    resp = await client.post(
        f"{API}/auth/login", data={"username": f"{name}@{DOMAIN}", "password": "secret123"}
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def test_only_an_admin_connects_the_organization(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "DEMO_MODE", True)
    await _users(db_session)
    rahul, admin = await _h(client, "rahul"), await _h(client, "admin")
    body = {"provider": "claude", "name": "Claude artifacts", "config": {"demo": True},
            "token": "compliance-key"}

    status_off = await client.get(f"{API}/docs/artifact-sync", headers=rahul)
    assert status_off.json()["available"] is False
    refused = await client.post(f"{API}/connectors/connections", json=body, headers=rahul)
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "admin_only"
    created = await client.post(f"{API}/connectors/connections", json=body, headers=admin)
    assert created.status_code == 201
    stored = await db_session.get(Connection, created.json()["id"])
    assert stored is not None and stored.encrypted_token != "compliance-key"  # encrypted

    # the existing "sync now" runs it; the counts land on the connection for the status line
    synced = await client.post(
        f"{API}/connectors/connections/{created.json()['id']}/sync", headers=rahul
    )
    assert synced.status_code == 200, synced.text
    status_on = (await client.get(f"{API}/docs/artifact-sync", headers=rahul)).json()
    assert status_on["available"] is True
    assert status_on["last_sync"]["full"] is True and status_on["last_sync"]["listed"] == 7

    policy = await client.get(f"{API}/admin/integrations", headers=admin)
    assert "claude" in [row["provider"] for row in policy.json()]


async def _connect(session) -> Connection:
    connection = Connection(provider=Provider.claude, name="Claude artifacts",
                            config={"demo": True}, encrypted_token=encrypt_token("demo-token"))
    session.add(connection)
    await session.commit()
    return connection


async def test_suggestions_list_only_your_own_untracked_artifacts(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "DEMO_MODE", True)
    ids = await _users(db_session)
    leo, sarah = await _h(client, "leo"), await _h(client, "sarah")
    admin = await _h(client, "admin")
    off = await client.get(f"{API}/docs/suggestions", headers=leo)
    assert off.json() == {"available": False, "complete": True, "items": []}
    await _connect(db_session)

    first = await client.get(f"{API}/docs/suggestions", headers=leo)
    assert first.status_code == 200
    mine = {s["artifact_id"]: s for s in first.json()["items"]}
    # Leo's two artifacts, nobody else's
    assert set(mine) == {"cart_01Dm0LatencyNotesLeo0001", "cart_01Dm0ReturnsFlowSketch01"}
    # a Claude Doc lists no versions, so the listing has no title for it
    notes = mine["cart_01Dm0LatencyNotesLeo0001"]
    assert (notes["title"], notes["format"], notes["version"]) == (None, "document", None)
    sketch = mine["cart_01Dm0ReturnsFlowSketch01"]
    assert sketch["title"] == "Returns flow sketch"
    assert (sketch["format"], sketch["visibility"], sketch["version"]) == ("page", "owner", "v1")
    # the first call learnt the owners' identities: later calls filter by owner
    identity = (await db_session.execute(
        select(ExternalRef).where(ExternalRef.entity_type == "user",
                                  ExternalRef.entity_id == ids["leo"])
    )).scalars().one()
    assert identity.external_id.startswith("user_01DemoLeo")

    # someone else's *personal* tracking of Sarah's PRD does not hide it from Sarah
    db_session.add(DocReference(
        url=f"{ART}/Dm0SavedAddressesPrd01", provider="claude",
        external_id="Dm0SavedAddressesPrd01", private_to_user_id=ids["leo"], visibility="org",
    ))
    await db_session.commit()
    sarahs = await client.get(f"{API}/docs/suggestions", headers=sarah)
    assert "cart_01Dm0SavedAddressesPrd01" in {s["artifact_id"] for s in sarahs.json()["items"]}

    # registering one of your own pairs it; it then drops out of your suggestions
    sketch_id = sketch["artifact_id"]
    tracked = await client.post(f"{API}/docs/register", json={
        "url": f"{ART}/Dm0ReturnsFlowSketch01", "kind": "design", "personal": True,
        "source_artifact_id": sketch_id,
    }, headers=leo)
    assert tracked.status_code == 201, tracked.text
    doc = tracked.json()["doc"]
    assert (doc["source"], doc["title"], doc["visibility"], doc["current_version"]) == (
        "claude_sync", "Returns flow sketch", "owner", "v1"
    )
    pairing = (await db_session.execute(
        select(ExternalRef).where(ExternalRef.entity_type == SYNC_DOC_ENTITY)
    )).scalars().one()
    assert (pairing.external_id, pairing.entity_id) == (sketch_id, doc["id"])
    after = await client.get(f"{API}/docs/suggestions", headers=leo)
    assert sketch_id not in {s["artifact_id"] for s in after.json()["items"]}

    # you cannot pair someone else's artifact, nor a non-Claude link
    theirs = await client.post(f"{API}/docs/register", json={
        "url": f"{ART}/Dm0SavedAddressesPrd01", "personal": True,
        "source_artifact_id": "cart_01Dm0SavedAddressesPrd01",
    }, headers=leo)
    assert theirs.status_code == 404 and theirs.json()["detail"]["code"] == "artifact_not_yours"
    elsewhere = await client.post(f"{API}/docs/register", json={
        "url": "https://wiki.example.com/latency", "personal": True,
        "source_artifact_id": "cart_01Dm0LatencyNotesLeo0001",
    }, headers=leo)
    assert elsewhere.status_code == 422

    # an admin impersonating Leo sees no suggestions (they would be Leo's)
    imp = await client.post(f"{API}/auth/impersonate/{ids['leo']}", headers=admin)
    as_leo = {"Authorization": f"Bearer {imp.json()['access_token']}"}
    impersonated = await client.get(f"{API}/docs/suggestions", headers=as_leo)
    assert impersonated.json()["available"] is False
    paired_as_leo = await client.post(f"{API}/docs/register", json={
        "url": f"{ART}/Dm0LatencyNotesLeo0001", "personal": True,
        "source_artifact_id": "cart_01Dm0LatencyNotesLeo0001",
    }, headers=as_leo)
    assert paired_as_leo.status_code == 403
    assert paired_as_leo.json()["detail"]["code"] == "impersonating"


async def test_a_run_moves_the_watermark_and_rereads_an_overlap(db_session, monkeypatch):
    monkeypatch.setattr(settings, "DEMO_MODE", True)
    connection = await _connect(db_session)
    connector = claude_sync.connector_for(connection, db_session)
    report = await claude_sync.sync_connection(connector, full=False)  # no watermark: full
    assert report.full and report.listed == 7
    mark = parse_time(connection.watermark)
    assert mark is not None and mark > utcnow() - timedelta(days=1)

    asked: list[datetime | None] = []
    real = ClaudeArtifactsConnector.list_artifacts

    async def spy(self, **kwargs):
        asked.append(kwargs.get("updated_since"))
        return await real(self, **kwargs)

    monkeypatch.setattr(ClaudeArtifactsConnector, "list_artifacts", spy)
    incremental = await claude_sync.sync_connection(connector, full=False)
    assert not incremental.full and asked == [mark - claude_sync.OVERLAP]
    assert incremental.listed >= 1  # the newest artifact sits inside the overlap


async def test_deleting_a_doc_drops_its_pairing(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "DEMO_MODE", True)
    await _users(db_session)
    leo = await _h(client, "leo")
    await _connect(db_session)
    tracked = await client.post(f"{API}/docs/register", json={
        "url": f"{ART}/Dm0ReturnsFlowSketch01", "personal": True,
        "source_artifact_id": "cart_01Dm0ReturnsFlowSketch01",
    }, headers=leo)
    assert tracked.status_code == 201
    assert (await client.delete(f"{API}/docs/{tracked.json()['doc']['id']}",
                                headers=leo)).status_code == 204
    refs = (await db_session.execute(
        select(ExternalRef).where(ExternalRef.entity_type == SYNC_DOC_ENTITY)
    )).scalars().all()
    assert refs == []


def test_worker_runs_the_sync_hourly_and_a_full_listing_nightly():
    from app.workers.worker import (
        WorkerSettings,
        claude_artifact_full_sync,
        claude_artifact_sync,
    )

    assert claude_artifact_sync in WorkerSettings.functions
    assert claude_artifact_full_sync in WorkerSettings.functions
    names = {job.name for job in WorkerSettings.cron_jobs}
    assert any("claude_artifact_sync" in n for n in names)
    assert any("claude_artifact_full_sync" in n for n in names)


async def test_worker_syncs_the_configured_connection(db_session, monkeypatch):
    from app.workers import worker
    from tests.conftest import TestSession

    monkeypatch.setattr(worker, "async_session_factory", TestSession)
    monkeypatch.setattr(settings, "DEMO_MODE", True)
    assert await worker.claude_artifact_sync({}) == {}  # nothing configured: a no-op
    connection = await _connect(db_session)
    await _doc(db_session, "Dm0GuestOptionsPage001", current_version="v2")
    await db_session.commit()
    summary = await worker.claude_artifact_full_sync({})
    assert summary[connection.id]["full"] is True
    assert summary[connection.id]["new_versions"] == 1  # republished as v3


# --- the /docs library's team filter ------------------------------------------------------------


async def test_docs_filter_by_team(client, db_session):
    await _users(db_session)
    rahul = await _h(client, "rahul")
    team, other = Team(key="CHK", name="Checkout"), Team(key="SRC", name="Search")
    db_session.add_all([team, other])
    await db_session.flush()
    initiative = Initiative(key="CHECKOUT", name="Checkout", team_id=team.id)
    elsewhere = Initiative(key="SEARCH", name="Search", team_id=other.id)
    db_session.add_all([initiative, elsewhere])
    await db_session.flush()
    p_in = Project(key="ONEPAGE", name="One-page checkout", initiative_id=initiative.id)
    p_out = Project(key="RANK", name="Ranking", initiative_id=elsewhere.id)
    db_session.add_all([p_in, p_out])
    await db_session.flush()
    homed = DocReference(url="https://wiki.example.com/a", scope_level="project",
                         scope_id=p_in.id, title="Homed in the team")
    on_initiative = DocReference(url="https://wiki.example.com/b", scope_level="initiative",
                                 scope_id=initiative.id, title="On the initiative")
    outside = DocReference(url="https://wiki.example.com/c", scope_level="project",
                           scope_id=p_out.id, title="Another team's")
    db_session.add_all([homed, on_initiative, outside])
    await db_session.commit()

    listed = await client.get(f"{API}/docs", params={"team_id": team.id}, headers=rahul)
    assert listed.status_code == 200
    assert {d["title"] for d in listed.json()} == {"Homed in the team", "On the initiative"}
    nothing = await client.get(f"{API}/docs", params={"team_id": 9999}, headers=rahul)
    assert nothing.json() == []


@pytest.mark.parametrize("artifact_type,expected", [
    ("claude_docs", "document"), ("code", "page"), ("claude_slides", "deck"),
    ("claude_sheets", "sheet"),
])
def test_artifact_types_imply_a_format(artifact_type, expected):
    assert claude_sync.TYPE_FORMATS[artifact_type] == expected
