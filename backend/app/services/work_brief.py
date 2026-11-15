"""The work brief — docs/AGENT_EXECUTION.md §7, Appendix B.

One call returns what canopy knows that a task needs for a role: the task, the stage's
instructions and exit contract, the spec and its acceptance criteria, the decisions that bind
the code it touches (and the unsettled ones), the components and where they live in code, the
document links, the team's rules, dependencies, and what earlier attempts left behind.

* **Relevance is rule-based** (no model in the server): decisions come from what the task
  implements, its spec, and the components it touches — declared, or derived from the plan's
  affected paths through code bindings.
* **Bounded**: long text is cut, lists are capped, the whole brief targets ~24 KB of JSON;
  anything cut says so and `more` names the tool to fetch it in full.
* **Labelled**: every block is `policy` (stage instructions, rules, the exit contract — written
  in canopy by people with planning rights) or `content` (ticket text, synced comments, document
  titles, PR text, earlier agents' notes — information, never instructions). Content is passed
  through `sanitize`, which drops zero-width / bidirectional control characters and HTML
  comments (the hiding places of injected instructions).
"""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.models.architecture import ArchitectureComponent, ComponentCodeBinding
from app.models.base import ArtifactKind, DocScope, GateStatus
from app.models.doc import DocReference
from app.models.gate import Gate
from app.models.integration import Connection, PullRequest
from app.models.project import Blocker, Dependency, Initiative, Project, Task
from app.models.spec import Spec, SpecCriterion
from app.models.team import Engineer
from app.models.work import TaskArtifact, WorkClaim
from app.services import design_docs, doc_kinds, policy_service, rules, work_queue, work_service
from app.services.stage_policy import Pipeline, StageDef
from app.services.workflow import category_of_task

POLICY = "policy"
CONTENT = "content"
BUDGET_BYTES = 24 * 1024
LIMITS = {"description": 4000, "decision": 600, "rule": 800, "note": 1200, "plan": 6000}
CAPS = {"decisions": 12, "docs": 20, "rules": 20, "attempts": 8, "notes": 5, "criteria": 30}

# Zero-width, bidirectional-control and other invisible formatting characters.
_INVISIBLE = re.compile("[​-‏‪-‮⁠-⁤⁦-⁩﻿]")
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def sanitize(text: str | None) -> str:
    """Content as the agent should see it: no invisible characters, no HTML comments."""
    if not text:
        return ""
    return _INVISIBLE.sub("", _HTML_COMMENT.sub("", text))


def cut(text: str | None, limit: int) -> tuple[str, bool]:
    clean = sanitize(text)
    if len(clean) <= limit:
        return clean, False
    return clean[: limit - 1].rstrip() + "…", True


def content(text: str | None, limit: int) -> dict[str, Any]:
    value, truncated = cut(text, limit)
    block: dict[str, Any] = {"trust": CONTENT, "text": value}
    if truncated:
        block["truncated"] = True
    return block


def slug(text: str, limit: int = 40) -> str:
    out = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return out[:limit].rstrip("-") or "work"


async def _engineer_name(session: AsyncSession, engineer_id: int | None) -> str | None:
    if engineer_id is None:
        return None
    engineer = await session.get(Engineer, engineer_id)
    return engineer.name if engineer is not None else None


def exit_contract(pipeline: Pipeline, stage: StageDef) -> dict[str, Any]:
    """What handing off from `stage` will be checked against: the next column's entry checks,
    and which decisions policy will ask a person for."""
    target = pipeline.next_after(stage)
    checks = [
        {"check": c.label(), "enforcement": c.enforcement, "applies_to": c.applies_to}
        for c in (target.enter_checks if target is not None else [])
        if c.enforcement != "off"
    ]
    asks = [
        {"checkpoint": name, "approval_when": cp.approval_when}
        for name, cp in stage.checkpoints.items()
    ]
    if target is not None and target.is_decision_column and target.decision is not None:
        asks.append({"decision_column": target.status_name, "when": target.decision.when})
    return {"to": target.status_name if target is not None else None, "checks": checks,
            "decisions": asks}


async def _repo_for(
    session: AsyncSession, component_ids: list[int], project: Project
) -> str | None:
    """The repository the work lands in: the touched components' code bindings, else the
    project's GitHub connection."""
    bindings = (
        await session.execute(
            select(ComponentCodeBinding).where(
                col(ComponentCodeBinding.component_id).in_(component_ids or [-1])
            )
        )
    ).scalars().all()
    for binding in bindings:
        if binding.repo:
            return binding.repo
        if binding.connection_id is not None:
            conn = await session.get(Connection, binding.connection_id)
            config = conn.config if conn is not None else {}
            if config.get("owner") and config.get("repo"):
                return f"{config['owner']}/{config['repo']}"
    return None


async def build_brief(
    session: AsyncSession,
    task: Task,
    role: str | None = None,
    *,
    claim: WorkClaim | None = None,
) -> dict[str, Any]:
    assert task.id is not None
    project = await session.get(Project, task.project_id)
    assert project is not None
    pipeline = await policy_service.resolve_pipeline(session, project)
    column = pipeline.stage(task.status)
    stage: StageDef | None = None
    if claim is not None:
        stage = pipeline.stage(claim.stage)
        role = claim.role
    if stage is None and role:
        stage = next((s for s in pipeline.stages_for(role) if column and s.key == column.key),
                     None)
        if stage is None:
            stage = next(iter(pipeline.stages_for(role)), None)
    if stage is None:
        stage = column
    truncated: list[str] = []

    # --- task -------------------------------------------------------------------------------
    parent = await session.get(Task, task.parent_id) if task.parent_id else None
    description = content(task.description, LIMITS["description"])
    if description.get("truncated"):
        truncated.append("task.description")
    brief: dict[str, Any] = {
        "task": {
            "id": task.id,
            "key": task.key,
            "name": sanitize(task.name),
            "description": description,
            "status": task.status,
            "tags": list(task.tags or []),
            "deadline": task.deadline.isoformat() if task.deadline else None,
            "duration_days": task.duration,
            "story_points": task.story_points,
            "project": {"id": project.id, "key": project.key, "name": project.name},
            "phase": (
                {"name": sanitize(parent.name), "description": content(parent.description, 800)}
                if parent is not None else None
            ),
            "accountable": await _engineer_name(session, task.assignee_engineer_id),
        }
    }

    # --- stage ------------------------------------------------------------------------------
    facts_attempts = 0
    rework = 0
    if stage is not None:
        work = await work_service.load_project_work(session, project, task_ids=[task.id])
        facts = work.facts.get(task.id)
        facts_attempts = facts.stage_attempts.get(stage.key, 0) if facts else 0
        from app.services.gates import rework_rounds

        rework = await rework_rounds(session, task, stage.status_name)
    brief["stage"] = {
        "trust": POLICY,
        "column": stage.status_name if stage else task.status,
        "role": role or (stage.worked_by if stage else None),
        "worked_by": stage.worked_by if stage else None,
        "instructions": (stage.instructions if stage else "") or "",
        "exit_contract": exit_contract(pipeline, stage) if stage else None,
        "claim_checks": [
            {"check": c.label(), "enforcement": c.enforcement}
            for c in (stage.enter_checks if stage else [])
            if c.check in ("distinct_actor", "distinct_issuer") and c.enforcement != "off"
        ],
        "limits": {
            "lease_minutes": stage.lease_minutes if stage else None,
            "heartbeat_interval_s": work_queue.heartbeat_interval_s(stage.lease_minutes)
            if stage else None,
            "stage_attempt": facts_attempts + 1,
            "max_attempts": stage.max_attempts if stage else None,
            "rework": rework,
            "max_rework": stage.max_rework if stage else None,
        },
        "pipeline_configured": pipeline.configured,
    }
    if work_service.is_mirrored(task):
        # The tracker owns this ticket's status (§17): canopy clears moves, the session makes them.
        brief["stage"]["tracker"] = {
            "provider": task.status_owner,
            "key": task.key,
            "status": task.status,
            "pending_move": work_service.tracker_transition(task),
            "how": (
                f"This ticket's status belongs to {task.status_owner}; canopy never changes it. "
                "When a response carries `tracker_transition`, make that move in the tracker "
                "with your own tools (or let its automation do it) — canopy sees it on the next "
                "sync. Moving the ticket anywhere canopy didn't clear is recorded as "
                "moved_without_clearance and ends your claim."
            ),
        }
    if claim is not None:
        brief["claim"] = {
            "id": claim.id,
            "attempt": claim.attempt,
            "role": claim.role,
            "lease_expires_at": claim.lease_expires_at.isoformat(),
            "heartbeat_interval_s": work_queue.heartbeat_interval_s(claim.lease_minutes),
        }

    # --- intent -----------------------------------------------------------------------------
    spec = await session.get(Spec, task.spec_id) if task.spec_id else None
    if spec is not None:
        criteria = (
            await session.execute(
                select(SpecCriterion).where(SpecCriterion.spec_id == spec.id)
                .order_by(col(SpecCriterion.sort_order), col(SpecCriterion.id))
            )
        ).scalars().all()
        brief["intent"] = {
            "trust": CONTENT,
            "spec": {
                "id": spec.id, "title": sanitize(spec.title),
                "status": str(spec.status.value if hasattr(spec.status, "value") else spec.status),
                "problem": cut(spec.problem, 2000)[0],
                "context": cut(spec.context, 1500)[0] or None,
                "out_of_scope": cut(spec.out_of_scope, 1000)[0] or None,
            },
            "criteria": [
                {"id": c.id, "text": cut(c.text, 400)[0],
                 "status": str(c.status.value if hasattr(c.status, "value") else c.status),
                 "verification": cut(c.verification, 300)[0] or None}
                for c in criteria[: CAPS["criteria"]]
            ],
        }
    else:
        brief["intent"] = {"trust": CONTENT, "missing": True,
                           "note": "No spec: there are no recorded acceptance criteria."}

    # --- components + decisions -------------------------------------------------------------
    plan = await work_service.latest_artifact(session, task.id, ArtifactKind.plan)
    declared = await work_service.task_component_ids(session, task.id)
    from_plan = [int(c) for c in ((plan.data or {}).get("resolved_component_ids") or [])] if (
        plan is not None) else []
    component_ids = sorted({*declared, *from_plan})
    components = (
        await session.execute(
            select(ArchitectureComponent).where(
                col(ArchitectureComponent.id).in_(component_ids or [-1])
            )
        )
    ).scalars().all()
    bindings = (
        await session.execute(
            select(ComponentCodeBinding).where(
                col(ComponentCodeBinding.component_id).in_(component_ids or [-1])
            )
        )
    ).scalars().all()
    brief["components"] = [
        {
            "id": c.id, "name": c.name, "kind": c.kind, "criticality": c.criticality,
            "owner": await _engineer_name(session, c.owner_engineer_id),
            "declared": c.id in declared,
            "code": [{"repo": b.repo, "path_glob": b.path_glob} for b in bindings
                     if b.component_id == c.id],
        }
        for c in components
    ]
    binding, unsettled = await work_service.decisions_for(session, task, component_ids)
    if len(binding) > CAPS["decisions"]:
        truncated.append("decisions.binding")

    def _decision(d: work_service.GoverningDecision) -> dict[str, Any]:
        return {
            "adr_id": d.adr_id, "adr": f"ADR-{d.number:04d}", "title": d.title,
            "status": d.status, "reversibility": d.reversibility, "why": d.why,
            "decision": cut(d.decision, LIMITS["decision"])[0] or None, "fitness": d.fitness,
        }

    brief["decisions"] = {
        "trust": POLICY,
        "binding": [_decision(d) for d in binding[: CAPS["decisions"]]],
        "unsettled": [_decision(d) for d in unsettled[: CAPS["decisions"]]],
        "on_conflict": (
            "An accepted decision binds this work. If the task conflicts with one, stop and "
            "ask (ask_human) whether the task or the decision should change — don't pick a side."
        ),
    }

    # --- docs -------------------------------------------------------------------------------
    scopes: list[tuple[DocScope, int, str]] = [(DocScope.task, task.id, "task")]
    if parent is not None and parent.id is not None:
        scopes.append((DocScope.task, parent.id, "phase"))
    scopes.append((DocScope.project, project.id or 0, "project"))
    if project.initiative_id is not None:
        scopes.append((DocScope.initiative, project.initiative_id, "initiative"))
    # Shared docs only — homed at each scope or linked to it. A personal doc is its owner's
    # alone, and a Claude doc backs shared work only while it is shared in Claude
    # (design_docs.shared_at_source).
    docs: list[dict[str, Any]] = []
    kinds: set[str] = set()
    seen: set[int] = set()
    for level, scope_id, label in scopes:
        linked = await design_docs.doc_ids_linked_to(session, level.value, [scope_id])
        for ref in (
            await session.execute(
                select(DocReference)
                .where(design_docs.scope_or_link_clause(level, scope_id, linked),
                       col(DocReference.private_to_user_id).is_(None))
                .order_by(col(DocReference.id))
            )
        ).scalars().all():
            if ref.id is None or ref.id in seen or not design_docs.shared_at_source(ref):
                continue
            seen.add(ref.id)
            kind = str(ref.kind.value if hasattr(ref.kind, "value") else ref.kind)
            kinds.add(kind)
            docs.append({"kind": kind, "title": sanitize(ref.title) or None, "url": ref.url,
                         "scope": label, "review": ref.review_status})
    if len(docs) > CAPS["docs"]:
        truncated.append("docs")
    expected = doc_kinds.expected_keys(await doc_kinds.load_catalog(session))
    brief["docs"] = {"trust": CONTENT, "links": docs[: CAPS["docs"]],
                     "missing": [k for k in expected if k not in kinds]}

    # --- rules ------------------------------------------------------------------------------
    guidance, attestations = await rules.rules_for_brief(session, task, stage, role)
    brief["rules"] = {
        "trust": POLICY,
        "guidance": [{**g, "body": cut(str(g.get("body") or ""), LIMITS["rule"])[0]}
                     for g in guidance[: CAPS["rules"]]],
        "attestations": attestations[: CAPS["rules"]],
    }

    # --- dependencies -----------------------------------------------------------------------
    preds = (
        await session.execute(select(Dependency).where(Dependency.successor_id == task.id))
    ).scalars().all()
    succs = (
        await session.execute(select(Dependency).where(Dependency.predecessor_id == task.id))
    ).scalars().all()
    pred_rows = []
    for dep in preds:
        other = await session.get(Task, dep.predecessor_id)
        if other is None:
            continue
        pr = await policy_service.latest_pull_request(session, other.id or 0)
        pred_rows.append({"key": other.key, "name": sanitize(other.name),
                          "category": category_of_task(other),
                          "type": str(dep.type.value if hasattr(dep.type, "value") else dep.type),
                          "pr": pr.url if pr is not None else None})
    succ_rows = []
    for dep in succs:
        other = await session.get(Task, dep.successor_id)
        if other is not None:
            succ_rows.append({"key": other.key, "name": sanitize(other.name)})
    blockers = (
        await session.execute(
            select(Blocker).where(Blocker.task_id == task.id, col(Blocker.resolved_at).is_(None))
        )
    ).scalars().all()
    brief["dependencies"] = {
        "trust": CONTENT,
        "predecessors": pred_rows,
        "successors": succ_rows,
        "blockers": [{"reason": cut(b.reason, 300)[0],
                      "severity": b.severity.value if b.severity is not None else None}
                     for b in blockers],
    }

    # --- history ----------------------------------------------------------------------------
    gates = (
        await session.execute(
            select(Gate).where(Gate.task_id == task.id).order_by(col(Gate.created_at))
        )
    ).scalars().all()
    plan_state = None
    if plan is not None:
        plan_gate = next((g for g in reversed(gates) if g.subject_artifact_id == plan.id), None)
        plan_state = (
            "approved" if plan_gate is not None and plan_gate.status == GateStatus.approved.value
            else "waiting_for_approval" if plan_gate is not None
            and plan_gate.status == GateStatus.open.value
            else "changes_requested" if plan_gate is not None
            and plan_gate.status == GateStatus.changes_requested.value
            else "no_approval_needed"
        )
    claims = (
        await session.execute(
            select(WorkClaim).where(WorkClaim.task_id == task.id).order_by(col(WorkClaim.id))
        )
    ).scalars().all()
    artifacts = (
        await session.execute(
            select(TaskArtifact).where(TaskArtifact.task_id == task.id)
            .order_by(col(TaskArtifact.id))
        )
    ).scalars().all()
    reviews = [a for a in artifacts if a.kind in (ArtifactKind.review.value,
                                                   ArtifactKind.qa_report.value)]
    notes = [a for a in artifacts if a.kind == ArtifactKind.note.value]
    handoff = next((a for a in reversed(artifacts) if a.kind == ArtifactKind.handoff.value), None)
    prs = (
        await session.execute(
            select(PullRequest).where(PullRequest.task_id == task.id)
            .order_by(col(PullRequest.id))
        )
    ).scalars().all()
    brief["history"] = {
        "trust": CONTENT,
        "plan": (
            {"revision": plan.revision, "state": plan_state, "title": plan.title,
             "body": cut(plan.body, LIMITS["plan"])[0],
             "steps": (plan.data or {}).get("steps") or [],
             "author_kind": plan.author_kind}
            if plan is not None else None
        ),
        "handoff": (
            {"revision": handoff.revision, "body": cut(handoff.body, 2000)[0],
             "data": {k: handoff.data.get(k) for k in ("summary", "pr_url", "branch",
                                                       "known_gaps", "follow_ups")
                      if handoff.data and handoff.data.get(k)}}
            if handoff is not None else None
        ),
        "attempts": [
            {"attempt": c.attempt, "role": c.role, "stage": c.stage, "state": c.state,
             "outcome": c.outcome, "progress_note": cut(c.progress_note, 400)[0] or None,
             "claimed_at": c.claimed_at.isoformat()}
            for c in claims[-CAPS["attempts"]:]
            if claim is None or c.id != claim.id
        ],
        "decisions": [
            {"gate_id": g.id, "kind": g.kind, "status": g.status, "decision": g.decision,
             "note": cut(g.response_note, LIMITS["note"])[0] or None,
             "option": (g.response_data or {}).get("option"),
             "question": cut(g.prompt, 600)[0] if g.kind == "question" else None,
             "decided_by": g.decided_by_label, "decided_via": g.decided_via,
             "decided_at": g.decided_at.isoformat() if g.decided_at else None}
            for g in gates if g.status != GateStatus.open.value
        ],
        "open_gates": [{"gate_id": g.id, "kind": g.kind, "title": g.title}
                       for g in gates if g.status == GateStatus.open.value],
        "findings": [
            {"kind": a.kind, "revision": a.revision, "verdict": a.verdict,
             "findings": (a.data or {}).get("findings") or [],
             "body": cut(a.body, 1500)[0]}
            for a in reviews[-3:]
        ],
        "notes": [{"author_kind": n.author_kind, "body": cut(n.body, 600)[0],
                   "at": n.created_at.isoformat()} for n in notes[-CAPS["notes"]:]],
        "pull_requests": [
            {"repo": p.repo, "number": p.number, "url": p.url, "state": p.state,
             "merged": p.merged, "head_branch": p.head_branch,
             "checks_state": p.checks_state, "review_decision": p.review_decision}
            for p in prs
        ],
    }

    # --- conventions + more -----------------------------------------------------------------
    key = task.key or f"T{task.id}"
    existing_branch = next((p.head_branch for p in reversed(prs) if p.head_branch), None)
    initiative = await session.get(Initiative, project.initiative_id) if (
        project.initiative_id) else None
    brief["conventions"] = {
        "trust": POLICY,
        "repo": await _repo_for(session, component_ids, project),
        "branch": existing_branch or f"{key.lower()}-{slug(task.name)}",
        "pr_title_prefix": key,
        "note": "Keep the same branch and PR across attempts; the PR links itself to the task "
                "by the key in its title or branch.",
        "initiative": initiative.key if initiative is not None else None,
    }
    brief["more"] = {
        "get_adr": [d["adr_id"] for d in brief["decisions"]["binding"]
                    + brief["decisions"]["unsettled"]],
        "get_spec": [spec.id] if spec is not None else [],
        "adr_impact": [d["adr_id"] for d in brief["decisions"]["binding"]],
        "list_doc_references": {"scope_level": "task", "scope_id": task.id},
        "read_design_doc": "for a Drive doc in docs.links",
        "read_repo_file": "for files in the components' code paths",
    }
    if truncated:
        brief["truncated"] = truncated
    return fit_to_budget(brief)


def fit_to_budget(brief: dict[str, Any], budget: int = BUDGET_BYTES) -> dict[str, Any]:
    """Trim the least important parts until the brief fits the budget: the oldest notes,
    attempts and findings, then documents, successors and unsettled decisions (halving each
    list, down to empty), then the plan's body and the task's description. The stage, the exit
    contract and the binding decisions are never trimmed."""

    def size() -> int:
        return len(json.dumps(brief, default=str))

    def mark(name: str) -> None:
        names = brief.setdefault("truncated", [])
        if name not in names:
            names.append(name)

    # (section, key, keep): lists ordered oldest → newest keep their tail.
    trims: list[tuple[str, str, str]] = [
        ("history", "notes", "tail"), ("history", "attempts", "tail"),
        ("history", "findings", "tail"), ("docs", "links", "head"),
        ("dependencies", "successors", "head"), ("decisions", "unsettled", "head"),
    ]
    for section, key, keep in trims:
        block = brief.get(section)
        if not isinstance(block, dict) or not isinstance(block.get(key), list):
            continue
        while size() > budget and block[key]:
            rows = block[key]
            half = len(rows) // 2
            block[key] = rows[len(rows) - half:] if keep == "tail" and half else rows[:half]
            mark(f"{section}.{key}")
    history = brief.get("history")
    plan = history.get("plan") if isinstance(history, dict) else None
    if size() > budget and isinstance(plan, dict) and plan.get("body"):
        plan["body"] = cut(plan["body"], 1500)[0]
        mark("history.plan.body")
    task = brief.get("task")
    description = task.get("description") if isinstance(task, dict) else None
    if size() > budget and isinstance(description, dict) and description.get("text"):
        description["text"] = cut(description["text"], 1500)[0]
        description["truncated"] = True
        mark("task.description")
    return brief
