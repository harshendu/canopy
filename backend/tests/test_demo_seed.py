from collections import Counter

import pytest
from sqlmodel import select

from app.core.config import settings
from app.core.security import hash_password
from app.models.base import UserFunction, UserRole
from app.models.leadership import LeadershipNote
from app.models.project import Task
from app.models.user import User
from app.services import seed
from app.services.links import collect_task_links
from app.services.seed.catalog import Dataset


async def _admin(session) -> User:
    user = User(
        email="admin@example.com", hashed_password=hash_password("secret123"),
        role=UserRole.admin, full_name="Op Admin",
    )
    session.add(user)
    await session.commit()
    return user


async def _token(client, email: str, password: str) -> str:
    resp = await client.post(
        "/api/v1/auth/login", data={"username": email, "password": password}
    )
    return resp.json()["access_token"]


def _hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_seed_loader_builds_a_full_coherent_dataset(db_session):
    counts = await seed.load_seed_data(db_session, set())

    assert counts["initiatives"] == 5
    assert counts["projects"] == 10
    assert counts["users"] >= 20  # every role and every function, incl. leads + executives
    assert counts["tasks"] > 60
    assert counts["dependencies"] > 0
    assert counts["decisions"] >= 25  # ADRs spread across every project
    assert counts["components"] >= 40
    assert counts["risks"] >= 15  # project + initiative scope
    assert counts["specs"] >= 10  # every project has a spec
    assert counts["outcomes"] >= 15
    assert counts["blockers"] >= 5
    assert counts["scenarios"] == 5  # one rich what-if per initiative
    assert counts["status_history"] > 0
    assert counts["connections"] == 3


@pytest.mark.asyncio
async def test_seed_scenarios_are_rich_whatifs(db_session):
    """Each seeded scenario is a real clone-plus-edits, not an empty branch — so the Compare,
    Capacity, Gantt and Milestones tabs all have content and a non-trivial delta vs live."""
    from app.models.scenario import (
        Scenario,
        ScenarioAllocation,
        ScenarioAvailability,
        ScenarioMilestone,
        ScenarioTask,
    )

    await seed.load_seed_data(db_session, set())
    scenarios = (await db_session.execute(select(Scenario))).scalars().all()

    # Lifecycle is demonstrated: at least one reviewed ("ready") and one in-flight ("draft").
    statuses = {s.status for s in scenarios}
    assert "ready" in statuses and "draft" in statuses

    # Across the scenarios, every editable dimension is exercised at least once.
    all_tasks = (await db_session.execute(select(ScenarioTask))).scalars().all()
    assert any(t.live_task_id is None for t in all_tasks)  # an added task
    assert any(t.removed for t in all_tasks)  # a tombstoned (deferred) task
    assert (await db_session.execute(select(ScenarioAllocation))).scalars().first() is not None
    assert (await db_session.execute(select(ScenarioAvailability))).scalars().first() is not None
    assert (await db_session.execute(select(ScenarioMilestone))).scalars().first() is not None

    # Every scenario is a faithful full clone (milestones + allocations carried over) carrying at
    # least one explicit edit (an added/removed row) — never an empty branch.
    for scenario in scenarios:
        sid = scenario.id
        s_tasks = [t for t in all_tasks if t.scenario_id == sid]
        s_allocs = (await db_session.execute(
            select(ScenarioAllocation).where(ScenarioAllocation.scenario_id == sid)
        )).scalars().all()
        s_avail = (await db_session.execute(
            select(ScenarioAvailability).where(ScenarioAvailability.scenario_id == sid)
        )).scalars().all()
        assert any(t.live_task_id is not None for t in s_tasks)  # cloned the live plan
        edits = (
            sum(t.live_task_id is None for t in s_tasks)
            + sum(t.removed for t in s_tasks)
            + sum(a.live_allocation_id is None for a in s_allocs)
            + sum(av.live_availability_id is None for av in s_avail)
        )
        assert edits > 0, f"scenario {scenario.title!r} has no edits vs live"


@pytest.mark.asyncio
async def test_flagship_task_surfaces_external_links(db_session):
    await seed.load_seed_data(db_session, set())
    task = (
        await db_session.execute(select(Task).where(Task.name == "Integrate tokenized payments"))
    ).scalars().one()
    assert task.id is not None

    links = await collect_task_links(db_session, task.id)
    # A clickable Jira issue built from the demo connection's browsable base_url.
    assert links.jira is not None
    assert links.jira.key.startswith("SHOP-")
    assert links.jira.url == f"https://jira.example.com/browse/{links.jira.key}"
    # The GitHub PRs that implement it.
    assert {pr.number for pr in links.pull_requests} == {412, 415}
    # A design doc that lives in GitHub (source=repo).
    assert any(d.source.value == "repo" for d in links.docs)


@pytest.mark.asyncio
async def test_clear_wipes_everything_but_kept_users(db_session):
    keeper = await _admin(db_session)
    await seed.load_seed_data(db_session, {keeper.id})
    await seed.clear_all_data(db_session, {keeper.id})

    after = await seed.seed_summary(db_session)
    assert after["projects"] == 0
    assert after["tasks"] == 0
    assert after["connections"] == 0
    # The acting admin is preserved so they stay logged in.
    assert after["users"] == 1


@pytest.mark.asyncio
async def test_reseed_endpoint_double_gated(client, db_session, monkeypatch):
    await _admin(db_session)
    admin = _hdr(await _token(client, "admin@example.com", "secret123"))

    monkeypatch.setattr(settings, "DEMO_MODE", False)
    blocked = await client.post("/api/v1/admin/demo/reseed", headers=admin)
    assert blocked.status_code == 403

    monkeypatch.setattr(settings, "DEMO_MODE", True)
    ok = await client.post("/api/v1/admin/demo/reseed", headers=admin)
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["seeded"] is True
    assert body["counts"]["projects"] >= 5
    assert body["password"] and len(body["accounts"]) >= 6

    cleared = await client.post("/api/v1/admin/demo/clear", headers=admin)
    assert cleared.status_code == 200
    assert cleared.json()["counts"]["projects"] == 0


@pytest.mark.asyncio
async def test_reseed_requires_admin(client, db_session, monkeypatch):
    await _admin(db_session)
    admin = _hdr(await _token(client, "admin@example.com", "secret123"))
    monkeypatch.setattr(settings, "DEMO_MODE", True)
    await client.post(
        "/api/v1/auth/register",
        json={"email": "eng@example.com", "password": "pw12345678", "role": "engineer"},
        headers=admin,
    )
    eng = _hdr(await _token(client, "eng@example.com", "pw12345678"))
    denied = await client.post("/api/v1/admin/demo/reseed", headers=eng)
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_public_demo_info_reflects_mode(client, monkeypatch):
    monkeypatch.setattr(settings, "DEMO_MODE", False)
    off = (await client.get("/api/v1/admin/demo/public")).json()
    assert off["demo_mode"] is False
    assert off["accounts"] == []

    monkeypatch.setattr(settings, "DEMO_MODE", True)
    on = (await client.get("/api/v1/admin/demo/public")).json()
    assert on["demo_mode"] is True
    assert on["password"]
    assert len(on["accounts"]) >= 6


@pytest.mark.asyncio
async def test_demo_jira_sync_uses_offline_mock(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "DEMO_MODE", True)
    await _admin(db_session)
    admin = _hdr(await _token(client, "admin@example.com", "secret123"))
    await client.post("/api/v1/admin/demo/reseed", headers=admin)

    conns = (await client.get("/api/v1/connectors/connections", headers=admin)).json()
    jira = next(c for c in conns if c["provider"] == "jira")
    synced = await client.post(
        f"/api/v1/connectors/connections/{jira['id']}/sync", headers=admin
    )
    assert synced.status_code == 200, synced.text
    # The offline mock returns one epic + three stories — the first sync imports them.
    assert synced.json()["created"] >= 1

    # GitHub PR reads also work fully offline.
    github = next(c for c in conns if c["provider"] == "github")
    pulls = await client.get(
        f"/api/v1/connectors/github/{github['id']}/pulls", headers=admin
    )
    assert pulls.status_code == 200
    assert len(pulls.json()) >= 1


def _check_references(ds: Dataset) -> None:
    engineers = {e.name for e in ds.engineers}
    users = {u.email for u in ds.users}
    teams = {t.key for t in ds.teams}
    pods = [pod for t in ds.teams for pod in t.pods]
    projects = {p.key: p for p in ds.projects}
    initiatives = {i.key: i for i in ds.initiatives}
    tasks = {p.key: [t.name for ph in p.phases for t in ph.tasks] for p in ds.projects}

    def eng(name: str | None) -> None:
        assert name is None or name in engineers, f"{ds.key}: unknown engineer {name!r}"

    # People + org.
    assert len(users) == len(ds.users) and len(engineers) == len(ds.engineers)
    assert len(pods) == len(set(pods)), "pod names are looked up by name, so must be unique"
    for e in ds.engineers:
        assert e.role_name in ds.team_roles and (e.user_email is None or e.user_email in users)
    for av in ds.availability:
        eng(av.engineer)
    for name, key, _ in ds.allocations:
        eng(name)
        assert key in projects
    for t in ds.teams:
        for name in (*t.directors, *t.managers):
            eng(name)
    for i in ds.initiatives:
        assert i.team_key in teams
        eng(i.owner_engineer)
        for name, _ in i.leads:
            eng(name)
        for owned in (*i.outcomes, *i.risks):
            eng(owned.owner)

    # Projects: every name a builder looks up must exist in the same project.
    for p in ds.projects:
        assert p.initiative_key in initiatives and p.pod in pods
        eng(p.owner)
        names = set(tasks[p.key])
        assert len(names) == len(tasks[p.key]), f"{p.key}: duplicate task names"
        comps = {c.name for c in p.components}
        for t in (t for ph in p.phases for t in ph.tasks):
            eng(t.assignee)
        for c in p.components:
            eng(c.owner)
        for link in p.component_links:
            assert {link.source, link.target} <= comps, (p.key, link)
        for b in p.bindings:
            assert b.component in comps
        for a in p.adrs:
            for name in (a.owner, a.proposer, *a.stakeholders, *(c.author for c in a.comments)):
                eng(name)
            assert set(a.components) <= comps, (p.key, a.title)
            if a.fitness is not None:
                assert {a.fitness.source, a.fitness.target} <= comps, (p.key, a.title)
        for d in p.drift:
            assert set(d.components) <= comps
        for sp in p.specs:
            eng(sp.owner)
            assert set(sp.task_names) <= names, (p.key, sp.title)
            assert sp.adr_title is None or sp.adr_title in {a.title for a in p.adrs}
        for owned in (*p.risks, *p.mitigations, *p.outcomes):
            eng(owned.owner)
        for doc in p.docs:
            assert doc.task_name is None or doc.task_name in names
        for b in p.blockers:
            assert b.task_name in names
            eng(b.owner)
            eng(b.raised_by)
        if p.retro is not None:
            assert set(p.retro.components) <= comps
            for c in p.retro.comments:
                eng(c.author)
        for inc in p.incidents:
            assert inc.component is None or inc.component in comps

    # Hand-offs name real tasks and stay inside one initiative (the API enforces the same).
    for (pk, t_pred), (sk, t_succ) in ds.cross_project_handoffs:
        assert t_pred in tasks[pk] and t_succ in tasks[sk]
        assert projects[pk].initiative_key == projects[sk].initiative_key

    for sc in ds.scenarios:
        assert projects[sc.project_key].initiative_key == sc.initiative_key
        names = set(tasks[sc.project_key])
        assert {n for n, _ in sc.duration_overrides} | set(sc.removed_tasks) <= names
        for added in sc.added_tasks:
            eng(added.assignee)
            assert added.after_task is None or added.after_task in names
        for alloc in sc.allocations:
            eng(alloc.engineer)
            assert alloc.project_key in projects
        for av in sc.availability:
            eng(av.engineer)
        assert {m.name for m in sc.milestone_pulls} <= {
            m.name for m in projects[sc.project_key].milestones
        }

    flagship = set(tasks[ds.flagship_key])
    assert ds.baseline_inflight_task in flagship
    assert {pr.task_name for pr in ds.pull_requests} <= flagship
    assert {name for _, _, name in ds.jira_task_keys} <= flagship

    # Leadership notes: authors log in, and each target is found by its (globally unique)
    # title inside the note's scope — the loader resolves targets by title.
    adrs = Counter(a.title for p in ds.projects for a in p.adrs)
    milestones = Counter(m.name for p in ds.projects for m in p.milestones)
    risks = Counter(r.title for p in ds.projects for r in p.risks)
    risks.update(r.title for i in ds.initiatives for r in i.risks)
    outcomes = Counter(o.statement for p in ds.projects for o in p.outcomes)
    outcomes.update(o.statement for i in ds.initiatives for o in i.outcomes)
    by_kind = {"decision": adrs, "milestone": milestones, "risk": risks, "outcome": outcomes}
    for note in ds.leadership_notes:
        assert note.author_email in users
        assert note.responder_email is None or note.responder_email in users
        scope = initiatives if note.scope_level == "initiative" else projects
        assert note.scope_key in scope
        if note.target_kind is not None:
            assert by_kind[note.target_kind][note.target_title] == 1, note.target_title


def test_every_dataset_reference_resolves():
    """The loader quietly skips names it cannot resolve (an unknown engineer, task, component or
    milestone just drops that row), so a typo in the declarative data would silently thin out
    the demo. Pin every cross-reference of every registered dataset instead."""
    assert seed.DATASETS
    for ds in seed.DATASETS.values():
        _check_references(ds)


@pytest.mark.asyncio
async def test_dataset_covers_the_org_model_and_every_persona(db_session):
    ds = seed.get_dataset()
    await seed.load_seed_data(db_session, set(), ds)

    # Org model (§R6): every initiative has owners and a team; every project one owner and a
    # pod; some people own several initiatives; some initiatives span several pods.
    assert all(i.leads and i.team_key for i in ds.initiatives)
    assert all(p.owner and p.pod for p in ds.projects)
    seats = Counter(name for i in ds.initiatives for name, _ in i.leads)
    assert {"Sarah Chen", "Oliver Grant", "Jakub Novak"} <= {n for n, c in seats.items() if c > 1}
    pods_of = {
        i.key: {p.pod for p in ds.projects if p.initiative_key == i.key} for i in ds.initiatives
    }
    assert {k for k, pods in pods_of.items() if len(pods) > 1} >= {"DELIVERY", "PEAK"}

    # Every access role and every persona function has a login, so each landing page has data.
    users = (await db_session.execute(select(User))).scalars().all()
    assert {u.role for u in users} == set(UserRole)
    assert {u.function for u in users} == set(UserFunction)
    leads = {u.function for u in users if u.role == UserRole.architect}
    assert {UserFunction.engineering, UserFunction.product, UserFunction.design} <= leads
    assert {u.full_name for u in users if u.function == UserFunction.leadership} == {
        "Elena Rossi", "Kwame Mensah",
    }

    # Every targeted leadership note resolved its target.
    notes = (await db_session.execute(select(LeadershipNote))).scalars().all()
    assert len(notes) == len(ds.leadership_notes)
    assert all(n.target_id is not None for n in notes if n.target_kind is not None)


def test_unknown_dataset_keys(monkeypatch):
    # An explicit unknown key is an error (the reseed endpoint turns it into a 400)...
    with pytest.raises(KeyError):
        seed.get_dataset("no-such-dataset")
    # ...but a stale DEMO_DATASET (e.g. from an older .env) falls back to the default instead
    # of breaking the login screen and the admin panel.
    monkeypatch.setattr(settings, "DEMO_DATASET", "no-such-dataset")
    assert seed.get_dataset().key == seed.DEFAULT_DATASET
    assert seed.demo_accounts()
