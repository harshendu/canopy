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

    # The whole run, measured at team level.
    flow = (await client.get(f"{API}/projects/{w.project_id}/agent-flow",
                             headers=w.arch)).json()
    assert flow["sufficient"] is True and flow["agent_tasks_done"] == 1
    assert flow["rework"]["tasks_returned_share"] == 1.0
    assert flow["first_pass"]["reviews"] == 0.5  # review failed first time, QA passed
    assert {"plan_approval", "escalation", "signoff"} <= set(flow["human_wait"]["by_kind"])
    assert flow["unassisted_share"] == 0.0  # it needed a plan approval and an escalation


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

    # Which scopes reach the project, and which the caller may add to: the architect plans the
    # project but isn't an admin; an agent token edits none.
    scopes = (await client.get(f"{API}/rules/scopes", params={"project_id": w.project_id},
                               headers=w.arch)).json()
    assert [(s["scope_level"], s["can_edit"]) for s in scopes] == [
        ("workspace", False), ("project", True)]  # no team: the project has no pod
    assert [s["can_edit"] for s in (await client.get(
        f"{API}/rules/scopes", params={"project_id": w.project_id}, headers=adm)).json()] == [
        True, True]
    agent = await _mint(client, w.arch, label="reader")
    assert not any(s["can_edit"] for s in (await client.get(
        f"{API}/rules/scopes", params={"project_id": w.project_id}, headers=agent)).json())
    assert (await client.get(f"{API}/rules/scopes", headers=w.arch)).status_code == 422

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


@pytest.mark.asyncio
async def test_a_first_policy_edit_keeps_the_default_stages(client: Any, db_session: Any) -> None:
    w = await _world(client, db_session)
    wf = (await client.get(f"{API}/projects/{w.project_id}/workflow", headers=w.arch)).json()
    cols = [{"name": c["name"], "category": c["category"]} for c in wf["columns"]]
    assert (await client.put(f"{API}/projects/{w.project_id}/workflow", json={"columns": cols},
                             headers=w.arch)).status_code == 200
    url = f"{API}/projects/{w.project_id}/workflow/policy"
    read = (await client.get(url, headers=w.arch)).json()
    assert read["configured"] is False and read["scope"] == "project"
    # The UI sends every column's document with its edit, defaults included.
    policies = {c["status"]: c["policy"] for c in read["columns"] if c["policy"]}
    assert set(policies) == {"In Progress", "In Review"}
    policies["In Review"]["enter"]["checks"].append({"check": "pr_checks", "enforcement": "warn"})
    saved = (await client.put(url, json={"policies": policies}, headers=w.arch)).json()
    assert saved["configured"] is True and saved["roles"] == ["implementer"]
    review = next(c for c in saved["columns"] if c["status"] == "In Review")
    assert {c["check"] for c in review["policy"]["enter"]["checks"]} == {
        "artifact", "pr_linked", "pr_checks"}


@pytest.mark.asyncio
async def test_pre_approved_change_classes_skip_the_plan_gate_but_not_the_floor(
    client: Any, db_session: Any
) -> None:
    w = await _world(client, db_session)
    await client.post(f"{API}/projects/{w.project_id}/workflow/apply-template",
                      json={"dry_run": False}, headers=w.arch)
    await client.post(f"{API}/projects/{w.project_id}/agent-intake", json={"state": "on"},
                      headers=w.arch)
    url = f"{API}/projects/{w.project_id}/autonomy"
    before = (await client.get(url, headers=w.arch)).json()
    assert before["stage"] == "In Progress" and before["pre_approved"] == {"plan": []}
    assert "one_way_door" in before["floor"] and before["can_edit"]

    # People pre-approve; agents can't.
    agent = await _mint(client, w.arch, label="bot")
    assert (await client.post(url, headers=agent, json={
        "checkpoint": "plan", "change_class": "tag:docs", "action": "add"})).status_code == 403
    added = await client.post(url, headers=w.arch, json={
        "checkpoint": "plan", "change_class": "tag:docs", "action": "add"})
    assert added.status_code == 200, added.text
    assert added.json()["pre_approved"]["plan"] == ["tag:docs"]

    async def planned(name: str, components: list[int]) -> dict[str, Any]:
        tid = (await client.post(f"{API}/tasks", json={
            "project_id": w.project_id, "name": name, "status": "Ready", "tags": ["docs"]},
            headers=w.arch)).json()["id"]
        await client.post(f"{API}/tasks/{tid}/delegation", json={"delegation": "agent"},
                          headers=w.arch)
        if components:
            await client.put(f"{API}/tasks/{tid}/components",
                             json={"component_ids": components}, headers=w.arch)
        token = await _mint(client, w.arch, label=f"impl-{name}", roles=["implementer"])
        claim = (await _claim(client, token, "implementer", tid))["claim"]
        plan = await client.post(f"{API}/work/claims/{claim['id']}/artifacts", headers=token,
                                 json={"kind": "plan", "body": "p",
                                       "data": {"approach": "p", "confidence": "high"}})
        assert plan.status_code in (200, 201), plan.text
        return dict(plan.json())

    # Probation (fewer than 5 done) would ask a person; the docs class is pre-approved.
    easy = await planned("Docs tweak", [])
    assert easy["approval"]["required"] is False
    # Touching a high-criticality component governed by a one-way door still asks.
    risky = await planned("Docs in the payments service", [w.component_id])
    assert risky["approval"]["required"] is True
    # The trail says what wasn't asked, and why.
    trail = (await client.get(f"{API}/tasks/{easy['artifact']['task_id']}/execution",
                              headers=w.arch)).json()["events"]
    pre = [e for e in trail if e["kind"] == "pre_approved"]
    assert pre and pre[0]["data"]["class"] == "tag:docs"

    removed = await client.post(url, headers=w.arch, json={
        "checkpoint": "plan", "change_class": "tag:docs", "action": "remove"})
    assert removed.json()["pre_approved"]["plan"] == []


@pytest.mark.asyncio
async def test_recurring_review_notes_become_a_rule_a_person_accepts(
    client: Any, db_session: Any
) -> None:
    from datetime import timedelta

    from app.models.base import utcnow
    from app.models.gate import Gate
    from app.models.policy import DeliveryRule

    w = await _world(client, db_session)
    tasks = []
    for i in range(3):
        tid = (await client.post(f"{API}/tasks", json={
            "project_id": w.project_id, "name": f"Change {i}", "status": "To Do"},
            headers=w.arch)).json()["id"]
        tasks.append(tid)
    notes = ["Add a migration test for the new column",
             "Missing migration test for the column change",
             "Please add a migration test covering the new column"]
    now = utcnow()
    for tid, note in zip(tasks, notes, strict=True):
        db_session.add(Gate(task_id=tid, project_id=w.project_id, kind="handoff_approval",
                            origin="checkpoint", title="Approve", status="changes_requested",
                            decision="request_changes", response_note=note, approvers="x",
                            created_at=now - timedelta(days=1), decided_at=now))
    await db_session.commit()

    [suggestion] = (await client.get(f"{API}/projects/{w.project_id}/rule-suggestions",
                                     headers=w.arch)).json()
    assert suggestion["count"] == 3 and len(suggestion["tasks"]) == 3
    assert "migration" in suggestion["key"]

    # A session stages the rule; a person accepts it.
    agent = await _mint(client, w.arch, label="reviewer-bot")
    rule_item = {"entity_type": "rule", "action": "create", "payload": {
        "key": "migration-tests", "title": "Schema changes come with a migration test",
        "body": "Every new or changed column ships with a migration test.",
        "kind": "attestation", "enforcement": "warn", "roles": ["implementer"]},
        "reason": "Asked for in three reviews this month", "source_kind": "other",
        "source_label": "recurring review notes"}
    staged = await client.post(f"{API}/proposals", headers=agent, json={
        "scope_level": "project", "scope_id": w.project_id,
        "title": "Make migration tests a rule", "items": [rule_item]})
    assert staged.status_code == 201, staged.text
    proposal_id = staged.json()["id"]
    preview = (await client.get(f"{API}/proposals/{proposal_id}/preview",
                                headers=w.arch)).json()
    assert preview["counts"]["rules_added"] == 1 and preview["can_apply"]
    assert (await client.post(f"{API}/proposals/{proposal_id}/apply",
                              headers=agent)).status_code == 403  # people apply
    applied = await client.post(f"{API}/proposals/{proposal_id}/apply", headers=w.arch)
    assert applied.status_code == 200, applied.text
    rule = (await db_session.execute(
        select(DeliveryRule).where(DeliveryRule.key == "migration-tests"))).scalar_one()
    assert rule.scope_level == "project" and rule.kind == "attestation"
    assert rule.roles == ["implementer"]
    assert rule.created_by_user_id is not None  # the person who accepted it, not the session
    # Covered now: the theme is no longer suggested, and the key can't be proposed twice.
    assert (await client.get(f"{API}/projects/{w.project_id}/rule-suggestions",
                             headers=w.arch)).json() == []
    again = await client.post(f"{API}/proposals", headers=agent, json={
        "scope_level": "project", "scope_id": w.project_id, "title": "Again",
        "items": [rule_item]})
    assert again.status_code == 400 and "already has a rule" in again.text
