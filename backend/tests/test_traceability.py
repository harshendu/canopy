"""The decision-to-code traceability ledger (PROPOSED_FLOWS §T, AGENT_EXECUTION.md Phase 4):
a decision joined to the work that implements it or touches what it governs, the PRs and
reviews behind that work, its fitness rules and drift — with a computed verdict."""

from __future__ import annotations

from typing import Any

import pytest

from app.core.security import hash_password
from app.models.architecture import (
    ADRComponentLink,
    ADRFitnessFunction,
    ArchitectureComponent,
    ArchitectureDecision,
    DriftEvent,
    TaskComponentLink,
)
from app.models.base import ADRStatus, Reversibility, UserRole
from app.models.integration import PullRequest
from app.models.project import Project, Task
from app.models.user import User
from app.models.work import TaskArtifact
from app.services import traceability as tr

API = "/api/v1"


def test_the_verdict_is_the_worst_thing_that_holds() -> None:
    base = tr.DecisionFacts(1, 1, "Vault", "accepted", "one_way", components=["payments"])
    done = tr.TaskFact(1, "PAY-1", "Vault", "Done", True, implements=True, governed=True)
    open_ = tr.TaskFact(2, "PAY-2", "More", "In Progress", False, implements=True, governed=False)
    rule = tr.FitnessFact(5, "require", "payments", "vault", None, violated=False)
    assert tr.verdict(tr.DecisionFacts(1, 1, "X", "superseded", None))[0] == "retired"
    assert tr.verdict(tr.DecisionFacts(1, 1, "X", "under_discussion", None))[0] == "pending"
    assert tr.verdict(base)[0] == "no_linked_work"
    assert tr.verdict(tr.DecisionFacts(**{**vars(base), "tasks": [done, open_]}))[0] == (
        "in_progress")
    honored = tr.DecisionFacts(**{**vars(base), "tasks": [done], "fitness": [rule]})
    assert tr.verdict(honored)[0] == "honored"
    broken = tr.FitnessFact(5, "require", "payments", "vault", None, violated=True)
    code, why = tr.verdict(tr.DecisionFacts(**{**vars(honored), "fitness": [broken]}))
    assert code == "violated" and "payments must depend on vault" in why
    drift = tr.DriftFact(9, "unimplemented_adr", "No code")
    assert tr.verdict(tr.DecisionFacts(**{**vars(honored), "drift": [drift]}))[0] == (
        "unimplemented")
    failed = tr.ReviewFact(1, 3, "fail", checked=True)
    assert tr.verdict(tr.DecisionFacts(**{**vars(honored), "reviews": [failed]}))[0] == (
        "at_risk")


@pytest.mark.asyncio
async def test_the_ledger_follows_a_decision_to_code(client: Any, db_session: Any) -> None:
    db_session.add(User(email="arch@e.com", role=UserRole.architect,
                        hashed_password=hash_password("secret123")))
    project = Project(key="PAY", name="Payments")
    db_session.add(project)
    await db_session.flush()
    payments = ArchitectureComponent(project_id=project.id, name="payments-service")
    vault = ArchitectureComponent(project_id=project.id, name="token-vault")
    db_session.add_all([payments, vault])
    await db_session.flush()
    adr = ArchitectureDecision(project_id=project.id, number=1, title="Tokenize in the vault",
                               status=ADRStatus.accepted, reversibility=Reversibility.one_way)
    idle = ArchitectureDecision(project_id=project.id, number=2, title="Use GraphQL",
                                status=ADRStatus.accepted)
    proposed = ArchitectureDecision(project_id=project.id, number=3, title="Orchestrator",
                                    status=ADRStatus.proposed)
    db_session.add_all([adr, idle, proposed])
    await db_session.flush()
    db_session.add(ADRComponentLink(adr_id=adr.id, component_id=payments.id))
    fitness = ADRFitnessFunction(adr_id=adr.id, kind="require",
                                 source_component_id=payments.id, target_component_id=vault.id)
    implementing = Task(project_id=project.id, name="Vault tokens", key="PAY-1",
                        status="In Progress", status_category="in_progress",
                        implements_adr_id=adr.id)
    touching = Task(project_id=project.id, name="Refunds", key="PAY-2", status="Done",
                    status_category="done")
    db_session.add_all([fitness, implementing, touching])
    await db_session.flush()
    db_session.add(TaskComponentLink(task_id=touching.id, component_id=payments.id))
    db_session.add(PullRequest(repo="acme/pay", number=7, title="PAY-1 vault", state="closed",
                               merged=True, task_id=implementing.id))
    db_session.add(TaskArtifact(task_id=implementing.id, kind="review", revision=1,
                                body="ok", verdict="pass",
                                data={"verdict": "pass", "checked": ["ADR-0001"]}))
    await db_session.commit()
    login = await client.post(f"{API}/auth/login",
                              data={"username": "arch@e.com", "password": "secret123"})
    h = {"Authorization": f"Bearer {login.json()['access_token']}"}

    trace = (await client.get(f"{API}/architecture/adrs/{adr.id}/traceability",
                              headers=h)).json()
    assert trace["verdict"] == "in_progress" and trace["components"] == ["payments-service"]
    assert {(t["key"], t["implements"], t["governed"]) for t in trace["tasks"]} == {
        ("PAY-1", True, False), ("PAY-2", False, True)}
    assert trace["pull_requests"][0]["merged"] and trace["reviews"][0]["checked"]
    assert trace["fitness"][0]["violated"] is False

    implementing.status, implementing.status_category = "Done", "done"
    await db_session.commit()
    assert (await client.get(f"{API}/architecture/adrs/{adr.id}/traceability",
                             headers=h)).json()["verdict"] == "honored"

    db_session.add(DriftEvent(project_id=project.id, kind="fitness_violation",
                              rule_key=f"fitness:{fitness.id}", summary="payments skips vault"))
    await db_session.commit()
    ledger = (await client.get(f"{API}/architecture/traceability",
                               params={"project_id": project.id}, headers=h)).json()
    assert [(r["number"], r["verdict"]) for r in ledger] == [
        (1, "violated"), (2, "no_linked_work"), (3, "pending")]
    assert ledger[0]["merged"] == 1 and ledger[0]["violated"] == 1


@pytest.mark.asyncio
async def test_a_task_implements_a_decision_of_its_own_project(
    client: Any, db_session: Any
) -> None:
    db_session.add(User(email="lead@e.com", role=UserRole.architect,
                        hashed_password=hash_password("secret123")))
    mine, other = Project(key="ONE", name="One"), Project(key="TWO", name="Two")
    db_session.add_all([mine, other])
    await db_session.flush()
    own = ArchitectureDecision(project_id=mine.id, number=1, title="Ours",
                               status=ADRStatus.accepted)
    foreign = ArchitectureDecision(project_id=other.id, number=1, title="Theirs",
                                   status=ADRStatus.accepted)
    task = Task(project_id=mine.id, name="Build it", key="ONE-1")
    db_session.add_all([own, foreign, task])
    await db_session.commit()
    login = await client.post(f"{API}/auth/login",
                              data={"username": "lead@e.com", "password": "secret123"})
    h = {"Authorization": f"Bearer {login.json()['access_token']}"}

    refused = await client.patch(f"{API}/tasks/{task.id}", headers=h,
                                 json={"implements_adr_id": foreign.id})
    assert refused.status_code == 422
    assert refused.json()["detail"]["code"] == "adr_not_in_project"
    linked = await client.patch(f"{API}/tasks/{task.id}", headers=h,
                                json={"implements_adr_id": own.id})
    assert linked.status_code == 200 and linked.json()["implements_adr_id"] == own.id
    unlinked = await client.patch(f"{API}/tasks/{task.id}", headers=h,
                                  json={"implements_adr_id": None})
    assert unlinked.status_code == 200 and unlinked.json()["implements_adr_id"] is None
