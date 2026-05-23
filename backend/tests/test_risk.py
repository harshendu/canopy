import pytest

from app.core.security import hash_password
from app.models.base import UserRole
from app.models.user import User
from app.services.risk import RiskSignals, compute_risk

# --- Pure service ------------------------------------------------------------


def _families(report):
    return {f.key: f for f in report.families}


def test_empty_signals_are_low_risk_and_quality_unavailable():
    report = compute_risk(RiskSignals())
    assert report.score == 0
    assert report.level == "low"
    fams = _families(report)
    assert [f.key for f in report.families] == [
        "schedule",
        "capacity",
        "architecture",
        "quality",
    ]
    assert fams["quality"].available is False


def test_quality_is_excluded_from_the_overall_score():
    # Architecture-only signal: 5 deferred-overdue -> deferred indicator caps at 100,
    # stuck 0 -> architecture family mean(100, 0) = 50.
    report = compute_risk(
        RiskSignals(deferred_overdue=[(i, f"ADR {i}") for i in range(1, 6)])
    )
    fams = _families(report)
    assert fams["architecture"].score == 50
    # Overall renormalises over available families (quality excluded), so
    # (50 * 0.25) / 0.80 = 16. With quality wrongly included it would be 13.
    assert report.score == 16
    assert fams["quality"].available is False


def test_strong_signals_across_families_reach_critical():
    report = compute_risk(
        RiskSignals(
            deadline_violations=[(i, "t") for i in range(4)],
            drifted_tasks=[(i, "t") for i in range(7)],
            critical_task_count=2,
            critical_zero_float_count=2,
            over_allocations=[("Ada", "2026-W20", 130.0) for _ in range(5)],
            deferred_overdue=[(i, "x") for i in range(5)],
            stuck_decisions=[(i, "y") for i in range(5)],
        )
    )
    assert report.score == 100
    assert report.level == "critical"


def test_indicator_details_are_surfaced_for_drilldown():
    report = compute_risk(RiskSignals(deadline_violations=[(7, "Ship API")]))
    schedule = _families(report)["schedule"]
    deadline = next(i for i in schedule.indicators if i.key == "deadline_violations")
    assert deadline.details == ["#7 Ship API"]


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
async def test_risk_dashboard_and_mitigation_log(client, db_session):
    await _seed_admin(db_session)
    headers = {"Authorization": f"Bearer {await _token(client)}"}

    project_id = (
        await client.post(
            "/api/v1/projects", json={"key": "PLAT", "name": "Platform"}, headers=headers
        )
    ).json()["id"]

    # A task that ends past its deadline -> schedule risk.
    task_id = (
        await client.post(
            "/api/v1/tasks",
            json={"project_id": project_id, "name": "Ship", "duration": 3},
            headers=headers,
        )
    ).json()["id"]
    await client.patch(
        f"/api/v1/tasks/{task_id}",
        json={"deadline": "2026-01-01", "end": "2026-02-01"},
        headers=headers,
    )

    # A deferred decision past its decide-by -> architecture risk.
    adr_id = (
        await client.post(
            "/api/v1/architecture/adrs",
            json={"project_id": project_id, "title": "Punt on caching"},
            headers=headers,
        )
    ).json()["id"]
    await client.patch(
        f"/api/v1/architecture/adrs/{adr_id}",
        json={"status": "deferred", "decide_by": "2026-01-01"},
        headers=headers,
    )

    risk = (await client.get(f"/api/v1/projects/{project_id}/risk", headers=headers)).json()
    assert risk["score"] > 0
    assert risk["level"] in {"low", "moderate", "high", "critical"}
    fams = {f["key"]: f for f in risk["families"]}
    assert fams["quality"]["available"] is False
    schedule_keys = {i["key"] for i in fams["schedule"]["indicators"]}
    assert "deadline_violations" in schedule_keys
    deferred = next(
        i for i in fams["architecture"]["indicators"] if i["key"] == "deferred_overdue"
    )
    assert deferred["score"] > 0

    # The portfolio card agrees with the Risk tab.
    portfolio = (await client.get("/api/v1/projects/portfolio", headers=headers)).json()
    card = next(p for p in portfolio["projects"] if p["id"] == project_id)
    assert card["risk_score"] == risk["score"]

    # Acknowledge an indicator, then resolve it.
    mit = await client.post(
        f"/api/v1/projects/{project_id}/risk/mitigations",
        json={"indicator_key": "deferred_overdue", "note": "Owner to decide Friday"},
        headers=headers,
    )
    assert mit.status_code == 201, mit.text
    mit_id = mit.json()["id"]

    risk2 = (await client.get(f"/api/v1/projects/{project_id}/risk", headers=headers)).json()
    assert any(m["id"] == mit_id for m in risk2["mitigations"])

    resolved = await client.patch(
        f"/api/v1/projects/{project_id}/risk/mitigations/{mit_id}",
        json={"resolved": True},
        headers=headers,
    )
    assert resolved.status_code == 200 and resolved.json()["resolved"] is True
