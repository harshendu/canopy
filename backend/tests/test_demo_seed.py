import pytest
from sqlmodel import select

from app.core.config import settings
from app.core.security import hash_password
from app.models.base import UserRole
from app.models.project import Task
from app.models.user import User
from app.services import seed
from app.services.links import collect_task_links


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

    assert counts["projects"] >= 8
    assert counts["initiatives"] == 3
    assert counts["users"] >= 6  # one login per role, spanning every persona
    assert counts["tasks"] > 40
    assert counts["dependencies"] > 0
    assert counts["decisions"] >= 10  # ADRs spread across every project
    assert counts["components"] >= 15
    assert counts["risks"] >= 8  # project + initiative scope
    assert counts["specs"] >= 8  # every project has a spec
    assert counts["outcomes"] >= 8
    assert counts["blockers"] >= 2
    assert counts["scenarios"] >= 3  # one rich what-if per initiative
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
        await db_session.execute(select(Task).where(Task.name == "Wire secure gateway in"))
    ).scalars().one()
    assert task.id is not None

    links = await collect_task_links(db_session, task.id)
    # A clickable Jira issue built from the demo connection's browsable base_url.
    assert links.jira is not None
    assert links.jira.key.startswith("HELIX-")
    assert links.jira.url == f"https://helix.atlassian.net/browse/{links.jira.key}"
    # The GitHub PRs that implement it.
    assert {pr.number for pr in links.pull_requests} == {318, 316}
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


@pytest.mark.asyncio
async def test_agentic_dataset_loads_with_the_same_depth(db_session):
    """The alternate (Northstar / agentic) narrative builds through the same generic loader and
    is as fully populated as the default: every project has its ADRs, specs, risks, outcomes,
    and every initiative a what-if scenario."""
    from app.services.seed import DATASETS, get_dataset

    assert set(DATASETS) >= {"helix", "agentic"}
    ds = get_dataset("agentic")
    assert {i.key for i in ds.initiatives} >= {
        "INTERVIEWER", "PILOT", "FORGE", "BUILDER", "DEVAGENTS", "SUPPORT", "ENHANCE",
    }
    # Every referenced task name resolves (hand-offs, scenarios, baseline, PRs, Jira keys).
    names = {p.key: {t.name for ph in p.phases for t in ph.tasks} for p in ds.projects}
    for (pk, t_pred), (sk, t_succ) in ds.cross_project_handoffs:
        assert t_pred in names[pk] and t_succ in names[sk]
    for sc in ds.scenarios:
        for name, _ in sc.duration_overrides:
            assert name in names[sc.project_key]
        for name in sc.removed_tasks:
            assert name in names[sc.project_key]
    assert ds.baseline_inflight_task in names[ds.flagship_key]
    for pr in ds.pull_requests:
        assert pr.task_name in names[ds.flagship_key]
    for _, _, name in ds.jira_task_keys:
        assert name in names[ds.flagship_key]

    counts = await seed.load_seed_data(db_session, set(), ds)
    assert counts["tasks"] > 60
    assert counts["decisions"] >= 30
    assert counts["specs"] >= 10
    assert counts["scenarios"] == 5
    assert counts["connections"] == 3
    assert counts["users"] >= 12

    # Org model (§R6): every initiative has one or more owners and belongs to a team; every
    # project has exactly one owner and a pod; some people own several initiatives.
    assert counts["initiatives"] == 7 and counts["projects"] == 13
    assert all(i.leads and i.team_key for i in ds.initiatives)
    assert all(p.owner and p.pod for p in ds.projects)
    seats: dict[str, int] = {}
    for i in ds.initiatives:
        for name, _ in i.leads:
            seats[name] = seats.get(name, 0) + 1
    assert {"Priya Raman", "Jonah Fields"} <= {n for n, c in seats.items() if c >= 2}
    pods_of = {
        i.key: {p.pod for p in ds.projects if p.initiative_key == i.key} for i in ds.initiatives
    }
    assert {k for k, pods in pods_of.items() if len(pods) > 1} >= {"PILOT", "FORGE", "ENHANCE"}
    leads = (
        await db_session.execute(select(User).where(User.role == UserRole.architect))
    ).scalars().all()
    assert {u.function.value for u in leads} == {"engineering", "product", "design"}
    execs = (
        await db_session.execute(select(User).where(User.role == UserRole.viewer))
    ).scalars().all()
    assert {u.full_name for u in execs if u.function.value == "leadership"} == {
        "Maya Lindqvist", "Grace Tan",
    }
