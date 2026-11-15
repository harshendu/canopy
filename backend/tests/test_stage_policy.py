"""Phase 2 of the agent work queue (docs/AGENT_EXECUTION.md §9, §10, Appendix A): stored stage
policies and their endpoints, the agentic-delivery template, rules, role-scoped submissions —
and the done-when walk: the Appendix A pipeline end to end with a plan gate on a one-way-door
task, a failed review routed back with its findings, an escalation at the rework cap, and a
sign-off satisfied by a GitHub approval from someone other than the requester."""

from __future__ import annotations

from typing import Any

import pytest
from sqlmodel import select

from app.core.security import hash_password
from app.models.architecture import ADRComponentLink, ArchitectureComponent, ArchitectureDecision
from app.models.base import ADRStatus, Provider, Reversibility, UserRole
from app.models.integration import Connection
from app.models.policy import StagePolicy
from app.models.project import Project, Task
from app.models.team import Engineer
from app.models.user import User

API = "/api/v1"


async def _login(client: Any, email: str) -> dict[str, str]:
    resp = await client.post(f"{API}/auth/login", data={"username": email, "password": "secret123"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _mint(client: Any, headers: dict[str, str], **body: Any) -> dict[str, str]:
    resp = await client.post(f"{API}/auth/agent-token", json=body, headers=headers)
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


class World:
    arch: dict[str, str]
    eng: dict[str, str]
    project_id: int
    component_id: int
    connection_id: int


async def _world(client: Any, db: Any) -> World:
    arch = User(email="arch@e.com", full_name="Ari Arch", role=UserRole.architect,
                hashed_password=hash_password("secret123"))
    eng = User(email="eng@e.com", full_name="Eli Eng", role=UserRole.engineer,
               hashed_password=hash_password("secret123"))
    db.add_all([arch, eng])
    await db.flush()
    db.add_all([Engineer(name="Ari Arch", user_id=arch.id, github_login="ari-gh"),
                Engineer(name="Eli Eng", user_id=eng.id, github_login="eli-gh")])
    project = Project(key="PAY", name="Payments")
    db.add(project)
    await db.flush()
    component = ArchitectureComponent(project_id=project.id, name="payments-service",
                                      criticality="high")
    db.add(component)
    await db.flush()
    adr = ArchitectureDecision(project_id=project.id, number=1, status=ADRStatus.accepted,
                               title="Tokenize cards through the provider vault",
                               reversibility=Reversibility.one_way,
                               decision="Card data never touches our servers.")
    db.add(adr)
    await db.flush()
    db.add(ADRComponentLink(adr_id=adr.id, component_id=component.id))
    connection = Connection(provider=Provider.github, name="gh",
                            config={"owner": "acme", "repo": "payments"})
    db.add(connection)
    await db.commit()
    w = World()
    w.arch = await _login(client, "arch@e.com")
    w.eng = await _login(client, "eng@e.com")
    assert project.id and component.id and connection.id
    w.project_id, w.component_id, w.connection_id = project.id, component.id, connection.id
    return w


# --------------------------------------------------------------------------- #
# Policies and the template
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_policy_endpoints_and_the_template(client: Any, db_session: Any) -> None:
    w = await _world(client, db_session)
    url = f"{API}/projects/{w.project_id}/workflow/policy"
    read = (await client.get(url, headers=w.arch)).json()
    assert read["scope"] == "default" and read["configured"] is False
    assert read["roles"] == ["implementer"]  # the built-in default
    # No own columns yet: policies attach to columns.
    put = await client.put(url, json={"policies": {}}, headers=w.arch)
    assert put.status_code == 409 and put.json()["detail"]["code"] == "workflow_inherited"

    # A card in To Do, then preview the template: To Do's cards go to Ready.
    await client.post(f"{API}/tasks", json={"project_id": w.project_id, "name": "Existing",
                                            "status": "To Do"}, headers=w.arch)
    tpl = f"{API}/projects/{w.project_id}/workflow/apply-template"
    preview = (await client.post(tpl, json={}, headers=w.arch)).json()
    assert preview["applied"] is False and preview["wip_enforcement"] == "block"
    assert {(m["from_status"], m["to_status"], m["tasks"]) for m in preview["moves"]} >= {
        ("To Do", "Ready", 1)}
    agent = await _mint(client, w.arch, label="bot")
    assert (await client.post(tpl, json={}, headers=agent)).status_code == 200  # a read
    refused = await client.post(tpl, json={"dry_run": False}, headers=agent)
    assert refused.status_code == 403  # saving is a person's
    applied = (await client.post(tpl, json={"dry_run": False}, headers=w.arch)).json()
    assert applied["applied"] is True
    pipeline = applied["pipeline"]
    assert pipeline["configured"] is True and pipeline["roles"] == ["implementer", "reviewer", "qa"]
    by_name = {c["status"]: c for c in pipeline["columns"]}
    assert by_name["In Review"]["hands_off"] == "review"
    assert by_name["Sign-off"]["worked_by"] == "human"
    existing = (await db_session.execute(select(Task).where(Task.name == "Existing"))).scalar_one()
    await db_session.refresh(existing)
    assert existing.status == "Ready"

    # Replacing: an invalid document is refused with its column; an agent can't loosen it.
    bad = await client.put(url, json={"policies": {"QA": {"worked_by": "Not A Role"}}},
                           headers=w.arch)
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "policy_invalid"
    assert bad.json()["detail"]["column"] == "QA"
    assert (await client.put(url, json={"policies": {}}, headers=agent)).status_code == 403
    # The workflow carries policies now: an agent can't change its columns either.
    wf = (await client.get(f"{API}/projects/{w.project_id}/workflow", headers=w.arch)).json()
    cols = [{"name": c["name"], "category": c["category"]} for c in wf["columns"]]
    change = await client.put(f"{API}/projects/{w.project_id}/workflow",
                              json={"columns": cols}, headers=agent)
    assert change.status_code == 403
    # A rename carries the column's policy; its references follow.
    renamed = [dict(c, previous_name=c["name"]) for c in cols]
    for c in renamed:
        if c["name"] == "In Progress":
            c["name"] = "Building"
    saved = await client.put(f"{API}/projects/{w.project_id}/workflow",
                             json={"columns": renamed, "wip_enforcement": "block"},
                             headers=w.arch)
    assert saved.status_code == 200, saved.text
    after = (await client.get(url, headers=w.arch)).json()
    stages = {c["status"]: c for c in after["columns"]}
    assert stages["Building"]["worked_by"] == "implementer"
    signoff = stages["Sign-off"]["policy"]["decision"]
    assert signoff["on_changes"] == "Building"
    rows = (await db_session.execute(select(StagePolicy))).scalars().all()
    assert "In Progress" not in {r.status_name for r in rows}


# --------------------------------------------------------------------------- #
# The Appendix A pipeline, end to end
# --------------------------------------------------------------------------- #


async def _claim(client: Any, token: dict[str, str], role: str, task_id: int) -> dict[str, Any]:
    resp = await client.post(f"{API}/work/claims", json={"role": role, "task_id": task_id},
                             headers=token)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["claim"] is not None, body
    return dict(body)


async def _pr(client: Any, w: World, **fields: Any) -> None:
    pr = {"number": 7, "title": "PAY-1 Card vault", "state": "open", "head_sha": "abc",
          "checks_state": "passing", "additions": 120, "deletions": 30, **fields}
    resp = await client.post(f"{API}/connectors/connections/{w.connection_id}/ingest/"
                             "pull-requests", json={"pull_requests": [pr]}, headers=w.arch)
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_the_appendix_a_pipeline_end_to_end(client: Any, db_session: Any) -> None:
    w = await _world(client, db_session)
    # A second planner, so the sign-off's separation of duties has someone else to ask.
    lead = User(email="lead@e.com", role=UserRole.architect,
                hashed_password=hash_password("secret123"))
    db_session.add(lead)
    await db_session.flush()
    db_session.add(Engineer(name="Lee Lead", user_id=lead.id, github_login="lee-gh"))
    await db_session.commit()
    lead_hdr = await _login(client, "lead@e.com")
    await client.post(f"{API}/projects/{w.project_id}/workflow/apply-template",
                      json={"dry_run": False}, headers=w.arch)
    task = (await client.post(f"{API}/tasks", json={
        "project_id": w.project_id, "name": "Card vault", "status": "Ready",
        "description": "Store cards in the provider vault"}, headers=w.arch)).json()
    tid = task["id"]
    assert task["key"] == "PAY-1"
    await client.put(f"{API}/tasks/{tid}/components", json={"component_ids": [w.component_id]},
                     headers=w.arch)
    await client.post(f"{API}/tasks/{tid}/delegation", json={"delegation": "agent"},
                      headers=w.arch)
    await client.post(f"{API}/projects/{w.project_id}/agent-intake", json={"state": "on"},
                      headers=w.arch)
    implementer = await _mint(client, w.arch, label="impl", roles=["implementer"])
    reviewer = await _mint(client, w.arch, label="rev", roles=["reviewer"])
    qa = await _mint(client, w.arch, label="qa", roles=["qa"])

    # 1. Plan gate: the plan touches what a one-way-door ADR governs.
    claim = (await _claim(client, implementer, "implementer", tid))["claim"]
    plan = (await client.post(f"{API}/work/claims/{claim['id']}/artifacts", json={
        "kind": "plan", "body": "Vault client + token store",
        "data": {"approach": "Vault client + token store",
                 "affected_paths": ["services/payments/vault.py"]}}, headers=implementer)).json()
    assert plan["approval"]["required"] is True
    assert any("one-way door" in r for r in plan["approval"]["reasons"])
    assert [d["adr"] for d in plan["governing_decisions"]] == ["ADR-0001"]
    gate_id = plan["approval"]["gate_id"]
    # The person whose agent wrote the plan can't approve it; the other planner does.
    own = await client.post(f"{API}/gates/{gate_id}/decide",
                            json={"decision": "approve", "subject_revision": 1}, headers=w.arch)
    assert own.status_code == 403
    approved = await client.post(f"{API}/gates/{gate_id}/decide",
                                 json={"decision": "approve", "subject_revision": 1},
                                 headers=lead_hdr)
    assert approved.status_code == 200, approved.text

    # 2. Implement and hand off — the review column needs an open PR with passing checks.
    claim = (await _claim(client, implementer, "implementer", tid))["claim"]
    handoff = {"handoff": {"summary": "Vault in place",
                           "verification": [{"command": "pytest", "result": "ok"}]}}
    refused = await client.post(f"{API}/work/claims/{claim['id']}/submit", json=handoff,
                                headers=implementer)
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "checks_failed"
    failed = {f["check"] for f in refused.json()["detail"]["evaluation"]["failures"]}
    assert failed == {"pr_linked", "pr_checks"}
    await _pr(client, w)
    moved = await client.post(f"{API}/work/claims/{claim['id']}/submit", json=handoff,
                              headers=implementer)
    assert moved.status_code == 200, moved.text
    assert moved.json()["moved_to"] == "In Review"

    # 3. The reviewer can't hand off code, and fails the review with findings.
    rclaim = (await _claim(client, reviewer, "reviewer", tid))["claim"]
    wrong = await client.post(f"{API}/work/claims/{rclaim['id']}/submit", json=handoff,
                              headers=reviewer)
    assert wrong.status_code == 409 and wrong.json()["detail"]["code"] == "wrong_artifact"
    review = {"review": {"kind": "review", "verdict": "fail", "body": "Tokens logged",
                         "findings": [{"severity": "blocker", "path": "vault.py",
                                       "note": "The token is written to the log"}]}}
    back = await client.post(f"{API}/work/claims/{rclaim['id']}/submit", json=review,
                             headers=reviewer)
    assert back.status_code == 200 and back.json()["moved_to"] == "In Progress"
    brief = (await _claim(client, implementer, "implementer", tid))["brief"]
    assert brief["history"]["findings"][-1]["findings"][0]["note"].startswith("The token")

    # 4. The loop is bounded: after three returns, the fourth opens an escalation.
    claim_id = brief["claim"]["id"]
    for round_ in range(3):
        sent = await client.post(f"{API}/work/claims/{claim_id}/submit", json=handoff,
                                 headers=implementer)
        assert sent.status_code == 200, sent.text
        rclaim = (await _claim(client, reviewer, "reviewer", tid))["claim"]
        out = (await client.post(f"{API}/work/claims/{rclaim['id']}/submit", json=review,
                                 headers=reviewer)).json()
        if round_ < 2:
            assert out["gate"] is None
            claim_id = (await _claim(client, implementer, "implementer", tid))["claim"]["id"]
    assert out["gate"] is not None and out["gate"]["kind"] == "escalation"
    assert "not converging" in out["gate"]["title"]
    retried = await client.post(f"{API}/gates/{out['gate']['id']}/decide", json={
        "decision": "retry", "note": "Redact tokens in the logger, then resubmit"},
        headers=w.arch)
    assert retried.status_code == 200

    # 5. This time it passes review and QA, and lands in Sign-off with a gate.
    claim = (await _claim(client, implementer, "implementer", tid))["claim"]
    await client.post(f"{API}/work/claims/{claim['id']}/submit", json=handoff,
                      headers=implementer)
    rclaim = (await _claim(client, reviewer, "reviewer", tid))["claim"]
    passed = (await client.post(f"{API}/work/claims/{rclaim['id']}/submit", json={
        "review": {"kind": "review", "verdict": "pass", "head_sha": "abc"}},
        headers=reviewer)).json()
    assert passed["moved_to"] == "QA"
    qclaim = (await _claim(client, qa, "qa", tid))["claim"]
    signoff = (await client.post(f"{API}/work/claims/{qclaim['id']}/submit", json={
        "review": {"kind": "qa_report", "verdict": "pass", "head_sha": "abc"}},
        headers=qa)).json()
    assert signoff["moved_to"] == "Sign-off" and signoff["gate"]["kind"] == "signoff"
    gate = signoff["gate"]
    assert gate["exclude_requester"] is True
    own = await client.post(f"{API}/gates/{gate['id']}/decide",
                            json={"decision": "approve"}, headers=w.arch)
    assert own.status_code == 403 and own.json()["detail"]["code"] == "self_approval_blocked"

    # 6. A GitHub approval from someone other than the requester satisfies it; the task
    #    waits for the merge (Done requires a merged PR), then moves.
    await _pr(client, w, approved_by=["ari-gh"], review_decision="approved")
    still = (await client.get(f"{API}/gates/{gate['id']}", headers=w.arch)).json()["gate"]
    assert still["status"] == "open"  # the requester's own approval doesn't count
    await _pr(client, w, approved_by=["eli-gh"], review_decision="approved")
    decided = (await client.get(f"{API}/gates/{gate['id']}", headers=w.arch)).json()["gate"]
    assert decided["status"] == "approved" and decided["decided_via"] == "pr_review"
    assert decided["waiting_for_evidence"] is True
    await _pr(client, w, merged=True, state="closed", merged_by="eli-gh")
    final = (await db_session.execute(select(Task).where(Task.id == tid))).scalar_one()
    await db_session.refresh(final)
    assert final.status == "Done"


# --------------------------------------------------------------------------- #
# Rules
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_rules_inherit_lock_and_become_definition_of_done(
    client: Any, db_session: Any
) -> None:
    w = await _world(client, db_session)
    admin = User(email="admin@e.com", role=UserRole.admin,
                 hashed_password=hash_password("secret123"))
    db_session.add(admin)
    await db_session.commit()
    adm = await _login(client, "admin@e.com")

    def rule(**body: Any) -> dict[str, Any]:
        return {"scope_level": "workspace", "scope_id": 0, "title": body.get("key", "x"), **body}

    # Only an admin writes workspace rules; agents never do.
    assert (await client.post(f"{API}/rules", json=rule(key="small-prs"), headers=w.arch)
            ).status_code == 403
    for body in (
        rule(key="small-prs", body="Keep PRs under 400 lines"),
        rule(key="flags", body="Feature-flag user-visible changes", locked=True),
        rule(key="tests", kind="attestation", enforcement="warn", title="Tests added"),
        rule(key="docs", kind="attestation", enforcement="warn", roles=["implementer"],
             title="USER_FLOWS updated"),
    ):
        resp = await client.post(f"{API}/rules", json=body, headers=adm)
        assert resp.status_code == 201, resp.text
    dup = await client.post(f"{API}/rules", json=rule(key="flags"), headers=adm)
    assert dup.status_code == 409
    project = {"scope_level": "project", "scope_id": w.project_id}
    for body in (
        {**project, "key": "small-prs", "title": "PRs under 200 lines here"},  # overrides
        {**project, "key": "flags", "title": "No flags", "disabled": True},  # locked: ignored
        {**project, "key": "tests", "title": "Tests added", "kind": "attestation",
         "enforcement": "block"},  # stricter wins
        {**project, "key": "docs", "title": "-", "kind": "attestation", "disabled": True},
    ):
        resp = await client.post(f"{API}/rules", json=body, headers=w.arch)
        assert resp.status_code == 201, resp.text
    effective = {e["rule"]["key"]: e for e in (await client.get(
        f"{API}/rules/effective", params={"project_id": w.project_id}, headers=w.arch)).json()}
    assert set(effective) == {"small-prs", "flags", "tests"}
    assert effective["small-prs"]["origin"] == "project"
    assert effective["small-prs"]["overrides"] == ["workspace"]
    assert effective["flags"]["origin"] == "workspace" and effective["flags"]["rule"]["locked"]
    assert effective["tests"]["enforcement"] == "block"

    # A rule from a superseded decision is stale.
    adr = (await db_session.execute(select(ArchitectureDecision))).scalar_one()
    await client.patch(f"{API}/rules/{effective['small-prs']['rule']['id']}",
                       json={"source_adr_id": adr.id}, headers=w.arch)
    adr.status = ADRStatus.superseded
    await db_session.commit()
    stale = {e["rule"]["key"]: e for e in (await client.get(
        f"{API}/rules/effective", params={"project_id": w.project_id}, headers=w.arch)).json()}
    assert stale["small-prs"]["stale"] is True

    # The brief carries them, and the template's review column checks attestations: it only
    # warns, but the project made "tests" a `block` rule, so a hand-off without it is refused.
    await client.post(f"{API}/projects/{w.project_id}/workflow/apply-template",
                      json={"dry_run": False}, headers=w.arch)
    tid = (await client.post(f"{API}/tasks", json={
        "project_id": w.project_id, "name": "Rules task", "status": "Ready"},
        headers=w.arch)).json()["id"]
    await client.post(f"{API}/tasks/{tid}/delegation", json={"delegation": "agent"},
                      headers=w.arch)
    await client.post(f"{API}/projects/{w.project_id}/agent-intake", json={"state": "on"},
                      headers=w.arch)
    impl = await _mint(client, w.arch, label="impl", roles=["implementer"])
    first = await _claim(client, impl, "implementer", tid)
    rules = first["brief"]["rules"]
    assert {g["key"] for g in rules["guidance"]} == {"small-prs", "flags"}
    assert [a["key"] for a in rules["attestations"]] == ["tests"]
    claim_id = first["claim"]["id"]
    plan = (await client.post(f"{API}/work/claims/{claim_id}/artifacts", json={
        "kind": "plan", "body": "p", "data": {"approach": "p", "confidence": "high"}},
        headers=impl)).json()
    if plan["approval"]["required"]:  # probation:5 on a fresh project
        # The admin approves: the requester's own approval doesn't count when someone else
        # may decide.
        approve = await client.post(f"{API}/gates/{plan['approval']['gate_id']}/decide",
                                    json={"decision": "approve", "subject_revision": 1},
                                    headers=adm)
        assert approve.status_code == 200, approve.text
        claim_id = (await _claim(client, impl, "implementer", tid))["claim"]["id"]
    await _pr(client, w, title="PAY-1 rules", number=8)
    missing = await client.post(f"{API}/work/claims/{claim_id}/submit", json={
        "handoff": {"summary": "done"}}, headers=impl)
    assert missing.status_code == 409
    checks = {f["check"] for f in missing.json()["detail"]["evaluation"]["failures"]}
    assert "attestations_complete" in checks
    ok = await client.post(f"{API}/work/claims/{claim_id}/submit", json={"handoff": {
        "summary": "done", "attestations": [{"rule_key": "tests", "status": "done",
                                             "evidence": "tests/test_vault.py"}]}},
        headers=impl)
    assert ok.status_code == 200 and ok.json()["moved_to"] == "In Review"
