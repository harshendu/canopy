"""Feature gates: the resolver, the admin API, and 403 enforcement on gated surfaces.

Defaults must reproduce the pre-gate behavior (everything on), so existing installs are
unaffected until an admin opts out. A group toggle must cascade to its children, and
re-enabling must restore access without a restart (the "seamless" requirement).
"""

import pytest

from app.core.security import hash_password
from app.models.base import UserRole
from app.models.feature import FeatureFlag
from app.models.project import Project
from app.models.user import User
from app.services.features import (
    FEATURE_CATALOG,
    FEATURES_BY_KEY,
    feature_enabled,
    resolve_effective,
)


# --- resolver unit tests (pure) ---
def test_catalog_children_reference_real_groups() -> None:
    for feature in FEATURE_CATALOG:
        if feature.group is not None:
            assert feature.group in FEATURES_BY_KEY
            assert FEATURES_BY_KEY[feature.group].group is None  # two levels only


def test_resolve_defaults_everything_on() -> None:
    effective = resolve_effective({})
    assert effective and all(effective.values())


def test_resolve_child_off_alone() -> None:
    effective = resolve_effective({"tracking.board": False})
    assert not effective["tracking.board"]
    assert effective["tracking"] and effective["tracking.burndown"]


def test_resolve_group_off_cascades_to_children() -> None:
    effective = resolve_effective({"tracking": False})
    assert not effective["tracking"]
    assert not effective["tracking.board"] and not effective["tracking.forecast"]
    assert effective["planning"] and effective["planning.scenarios"]


def test_resolve_child_override_cannot_beat_disabled_group() -> None:
    effective = resolve_effective({"governance": False, "governance.risk": True})
    assert not effective["governance.risk"]


@pytest.mark.asyncio
async def test_feature_enabled_reads_db_and_defaults(db_session) -> None:
    assert await feature_enabled(db_session, "planning.scenarios")
    assert await feature_enabled(db_session, "not-in-catalog")  # unknown keys fail open
    db_session.add(FeatureFlag(key="planning.scenarios", enabled=False))
    await db_session.commit()
    assert not await feature_enabled(db_session, "planning.scenarios")


# --- API + enforcement ---
async def _seed(session) -> None:
    session.add_all(
        [
            User(
                email="admin@e.com",
                hashed_password=hash_password("secret123"),
                role=UserRole.admin,
            ),
            User(
                email="eng@e.com",
                hashed_password=hash_password("secret123"),
                role=UserRole.engineer,
            ),
        ]
    )
    session.add(Project(key="PLAT", name="Platform"))
    await session.commit()


async def _headers(client, email: str) -> dict[str, str]:
    resp = await client.post(
        "/api/v1/auth/login", data={"username": email, "password": "secret123"}
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.mark.asyncio
async def test_admin_features_requires_admin(client, db_session) -> None:
    await _seed(db_session)
    eng = await _headers(client, "eng@e.com")
    assert (await client.get("/api/v1/admin/features", headers=eng)).status_code == 403
    assert (
        await client.patch(
            "/api/v1/admin/features/tracking", json={"enabled": False}, headers=eng
        )
    ).status_code == 403


@pytest.mark.asyncio
async def test_effective_map_readable_by_any_user(client, db_session) -> None:
    await _seed(db_session)
    eng = await _headers(client, "eng@e.com")
    resp = await client.get("/api/v1/features", headers=eng)
    assert resp.status_code == 200
    features = resp.json()["features"]
    assert features["tracking.board"] is True and features["planning"] is True


@pytest.mark.asyncio
async def test_admin_lists_catalog_and_patch_cascades(client, db_session) -> None:
    await _seed(db_session)
    admin = await _headers(client, "admin@e.com")

    listed = (await client.get("/api/v1/admin/features", headers=admin)).json()
    by_key = {row["key"]: row for row in listed}
    assert by_key["tracking"]["group"] is None
    assert by_key["tracking.board"]["group"] == "tracking"
    assert all(row["enabled"] and row["effective"] for row in listed)

    patched = await client.patch(
        "/api/v1/admin/features/tracking", json={"enabled": False}, headers=admin
    )
    assert patched.status_code == 200, patched.text
    by_key = {row["key"]: row for row in patched.json()}
    # The child keeps its own toggle on, but its effective state follows the group.
    assert by_key["tracking.board"]["enabled"] and not by_key["tracking.board"]["effective"]

    unknown = await client.patch(
        "/api/v1/admin/features/nope", json={"enabled": False}, headers=admin
    )
    assert unknown.status_code == 404


@pytest.mark.asyncio
async def test_disabled_feature_returns_403_and_reenables_live(client, db_session) -> None:
    await _seed(db_session)
    admin = await _headers(client, "admin@e.com")

    assert (await client.get("/api/v1/projects/1/board", headers=admin)).status_code == 200
    assert (await client.get("/api/v1/specs", headers=admin)).status_code == 200
    assert (await client.get("/api/v1/initiatives", headers=admin)).status_code == 200

    # Child gate off -> that endpoint 403s with a machine-readable detail.
    await client.patch(
        "/api/v1/admin/features/tracking.board", json={"enabled": False}, headers=admin
    )
    blocked = await client.get("/api/v1/projects/1/board", headers=admin)
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["code"] == "feature_disabled"
    assert blocked.json()["detail"]["feature"] == "tracking.board"

    # Group gate off -> the whole router 403s (specs sits under governance).
    await client.patch(
        "/api/v1/admin/features/governance", json={"enabled": False}, headers=admin
    )
    assert (await client.get("/api/v1/specs", headers=admin)).status_code == 403

    # Portfolio group off -> initiatives router 403s.
    await client.patch(
        "/api/v1/admin/features/portfolio.initiatives", json={"enabled": False}, headers=admin
    )
    assert (await client.get("/api/v1/initiatives", headers=admin)).status_code == 403

    # Re-enable -> access restored immediately (no restart, no cache staleness).
    for key in ("tracking.board", "governance", "portfolio.initiatives"):
        await client.patch(
            f"/api/v1/admin/features/{key}", json={"enabled": True}, headers=admin
        )
    assert (await client.get("/api/v1/projects/1/board", headers=admin)).status_code == 200
    assert (await client.get("/api/v1/specs", headers=admin)).status_code == 200
    assert (await client.get("/api/v1/initiatives", headers=admin)).status_code == 200


@pytest.mark.asyncio
async def test_gated_core_endpoints_stay_open(client, db_session) -> None:
    """Core flows (projects, tasks, gantt, team) have no gate at all."""
    await _seed(db_session)
    admin = await _headers(client, "admin@e.com")
    for key, _ in (("tracking", False), ("planning", False)):
        await client.patch(
            f"/api/v1/admin/features/{key}", json={"enabled": False}, headers=admin
        )
    assert (await client.get("/api/v1/projects", headers=admin)).status_code == 200
    assert (await client.get("/api/v1/projects/1/gantt", headers=admin)).status_code == 200
    assert (await client.get("/api/v1/tasks?project_id=1", headers=admin)).status_code == 200
    assert (await client.get("/api/v1/team/engineers", headers=admin)).status_code == 200
