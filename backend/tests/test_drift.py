import pytest

from app.core.security import hash_password
from app.models.base import UserRole
from app.models.user import User
from app.services.code_analysis import actual_edges, python_imports
from app.services.drift import (
    DriftInputs,
    ImplicitSignal,
    detect,
    level,
    run_detection,
    score_kinds,
)

# --- Pure: code analysis -----------------------------------------------------


def test_python_imports_handles_absolute_and_skips_relative():
    src = "import a.b\nfrom c.d import x\nfrom . import y\nimport os\n"
    assert python_imports(src) == {"a.b", "c.d", "os"}


def test_python_imports_survives_syntax_error():
    assert python_imports("def (:\n") == set()


def test_actual_edges_maps_imports_to_owning_component():
    component_imports = {1: {"app.b.thing"}, 2: {"app.a.x"}, 3: {"os"}}
    module_prefixes = {1: ["app.a"], 2: ["app.b"]}
    # 1 imports app.b -> owned by 2; 2 imports app.a -> owned by 1; 3 imports stdlib -> none.
    assert actual_edges(component_imports, module_prefixes) == {(1, 2), (2, 1)}


def test_actual_edges_longest_prefix_wins():
    component_imports = {9: {"app.a.b.deep"}}
    module_prefixes = {1: ["app.a"], 2: ["app.a.b"]}
    assert actual_edges(component_imports, module_prefixes) == {(9, 2)}


# --- Pure: detection ---------------------------------------------------------


NAMES = {1: "A", 2: "B", 3: "C"}


def test_detect_unexpected_and_dead_dependencies():
    findings = detect(
        DriftInputs(
            component_names=NAMES,
            declared_edges={(1, 2), (2, 3)},
            actual_edges={(1, 2), (1, 3)},
        )
    )
    kinds = {f.kind: f for f in findings}
    assert "unexpected_dependency" in kinds  # (1,3) in code, not declared
    assert "dead_dependency" in kinds  # (2,3) declared, not in code
    assert kinds["unexpected_dependency"].rule_key == "dep_unexpected:1->3"


def test_detect_unimplemented_adr_and_implicit_decision():
    findings = detect(
        DriftInputs(
            component_names=NAMES,
            accepted_adrs=[(7, "Event sourcing", [1])],
            inactive_component_ids={1},
            implicit_signals=[ImplicitSignal("new_datastore", "Added Redis cache")],
        )
    )
    kinds = {f.kind for f in findings}
    assert kinds == {"unimplemented_adr", "implicit_decision"}


def test_suppression_and_score_and_level():
    inputs = DriftInputs(
        component_names=NAMES, declared_edges=set(), actual_edges={(1, 2), (1, 3)}
    )
    full = run_detection(inputs, suppressed=set())
    assert full.score == score_kinds(["unexpected_dependency", "unexpected_dependency"])  # 24
    assert full.level == level(full.score)

    suppressed = run_detection(inputs, suppressed={"dep_unexpected:1->2"})
    assert len(suppressed.findings) == 1
    assert suppressed.score < full.score


# --- API ---------------------------------------------------------------------


async def _seed_admin(session) -> None:
    session.add(
        User(
            email="architect@example.com",
            hashed_password=hash_password("secret123"),
            role=UserRole.admin,
        )
    )
    await session.commit()


async def _token(client) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "architect@example.com", "password": "secret123"},
    )
    return resp.json()["access_token"]


@pytest.mark.asyncio
async def test_drift_scan_queue_and_reconciliation(client, db_session):
    await _seed_admin(db_session)
    headers = {"Authorization": f"Bearer {await _token(client)}"}
    project_id = (
        await client.post(
            "/api/v1/projects", json={"key": "PLAT", "name": "Platform"}, headers=headers
        )
    ).json()["id"]

    async def comp(name: str) -> int:
        return (
            await client.post(
                "/api/v1/architecture/components",
                json={"project_id": project_id, "name": name},
                headers=headers,
            )
        ).json()["id"]

    a, b, c = await comp("A"), await comp("B"), await comp("C")
    # Declare A -> B only.
    await client.post(
        "/api/v1/architecture/component-links",
        json={"source_id": a, "target_id": b},
        headers=headers,
    )

    # The Sentinel observes A->B (ok) and A->C (undeclared) in code.
    scan = await client.post(
        f"/api/v1/projects/{project_id}/drift/scan",
        json={"actual_edges": [[a, b], [a, c]]},
        headers=headers,
    )
    assert scan.status_code == 200, scan.text
    report = scan.json()
    assert report["score"] > 0
    unexpected = [e for e in report["events"] if e["kind"] == "unexpected_dependency"]
    dead = [e for e in report["events"] if e["kind"] == "dead_dependency"]
    assert len(unexpected) == 1
    assert sorted(unexpected[0]["affected_component_ids"]) == sorted([a, c])
    assert len(dead) == 0  # A->B is backed by code

    # Accept the drift -> a proposed ADR is minted for the change.
    event_id = unexpected[0]["id"]
    rec = await client.post(
        f"/api/v1/projects/{project_id}/drift/{event_id}/reconcile",
        json={"action": "accepted"},
        headers=headers,
    )
    assert rec.status_code == 200, rec.text
    assert rec.json()["created_adr_id"] is not None
    adrs = (
        await client.get(f"/api/v1/architecture/adrs?project_id={project_id}", headers=headers)
    ).json()
    assert any(c in adr["component_ids"] and a in adr["component_ids"] for adr in adrs)


@pytest.mark.asyncio
async def test_false_positive_suppresses_on_next_scan(client, db_session):
    await _seed_admin(db_session)
    headers = {"Authorization": f"Bearer {await _token(client)}"}
    project_id = (
        await client.post(
            "/api/v1/projects", json={"key": "PLAT", "name": "Platform"}, headers=headers
        )
    ).json()["id"]

    async def comp(name: str) -> int:
        return (
            await client.post(
                "/api/v1/architecture/components",
                json={"project_id": project_id, "name": name},
                headers=headers,
            )
        ).json()["id"]

    a, c = await comp("A"), await comp("C")
    payload = {"actual_edges": [[a, c]]}
    first = (
        await client.post(
            f"/api/v1/projects/{project_id}/drift/scan", json=payload, headers=headers
        )
    ).json()
    event_id = first["events"][0]["id"]

    # Mark false positive -> learns a suppression.
    await client.post(
        f"/api/v1/projects/{project_id}/drift/{event_id}/reconcile",
        json={"action": "false_positive"},
        headers=headers,
    )
    # Re-scan: the same edge no longer produces an open finding; score is 0.
    second = (
        await client.post(
            f"/api/v1/projects/{project_id}/drift/scan", json=payload, headers=headers
        )
    ).json()
    assert second["score"] == 0
    assert all(e["status"] != "open" for e in second["events"])


@pytest.mark.asyncio
async def test_drift_scan_due_staleness(client, db_session):
    from datetime import datetime, timedelta

    from app.models.architecture import DriftScan

    await _seed_admin(db_session)
    headers = {"Authorization": f"Bearer {await _token(client)}"}

    async def make_project(key: str) -> int:
        return (
            await client.post(
                "/api/v1/projects", json={"key": key, "name": key}, headers=headers
            )
        ).json()["id"]

    async def bind(project_id: int) -> None:
        comp_id = (
            await client.post(
                "/api/v1/architecture/components",
                json={"project_id": project_id, "name": "Svc"},
                headers=headers,
            )
        ).json()["id"]
        await client.post(
            "/api/v1/architecture/code-bindings",
            json={"component_id": comp_id, "path_glob": "app/**", "module_prefix": "app"},
            headers=headers,
        )

    # (1) Bindings but never scanned -> scan is due, no last_scanned_at.
    p1 = await make_project("BIND")
    await bind(p1)
    d1 = (await client.get(f"/api/v1/projects/{p1}/drift", headers=headers)).json()
    assert d1["scan_due"] is True
    assert d1["last_scanned_at"] is None

    # After a scan -> not due, timestamp recorded.
    scan = (
        await client.post(
            f"/api/v1/projects/{p1}/drift/scan", json={"actual_edges": []}, headers=headers
        )
    ).json()
    assert scan["scan_due"] is False
    assert scan["last_scanned_at"] is not None

    # (2) No code bindings -> nothing to scan, never due.
    p2 = await make_project("NOBIND")
    d2 = (await client.get(f"/api/v1/projects/{p2}/drift", headers=headers)).json()
    assert d2["scan_due"] is False

    # (3) Bindings + only an old scan (10 days ago) -> stale, due again.
    p3 = await make_project("STALE")
    await bind(p3)
    db_session.add(
        DriftScan(
            project_id=p3,
            finding_count=0,
            created_at=datetime.utcnow() - timedelta(days=10),
        )
    )
    await db_session.commit()
    d3 = (await client.get(f"/api/v1/projects/{p3}/drift", headers=headers)).json()
    assert d3["scan_due"] is True
    assert d3["last_scanned_at"] is not None
