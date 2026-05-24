"""Seed a representative dataset for the e2e suite via the public API.

Builds an initiative with two sub-projects, a team with (cross-project) allocations,
scheduled work with a cross-project hand-off, an architecture component map with an
accepted ADR + a fitness function, an open blocker, and a CI activity event — enough that
every major read-flow has something real to render. Returns the created ids.

External dependencies are NOT touched here; the Jira sync flow is exercised separately
against a local mock server (see mock_jira.py).
"""

from __future__ import annotations

import time
from typing import Any

from helpers import (
    api_create_adr,
    api_create_component,
    api_create_engineer,
    api_create_initiative,
    api_create_project,
    api_create_task,
    api_post,
)

SUFFIX = str(int(time.time()) % 100000)


def seed_dataset(base_url: str, token: str) -> dict[str, Any]:
    s = SUFFIX

    initiative = api_create_initiative(
        base_url, token, f"INIT{s}", "Q3 Platform",
        outcome_statement="Ship the multi-tenant platform", target_date="2026-09-01",
    )
    init_id = initiative["id"]

    proj_a = api_create_project(
        base_url, token, f"ALPHA{s}", "Alpha service",
        initiative_id=init_id, start_date="2026-06-01", target_date="2026-08-01",
    )
    proj_b = api_create_project(
        base_url, token, f"BETA{s}", "Beta service",
        initiative_id=init_id, start_date="2026-06-01", target_date="2026-08-15",
    )

    # Team: two engineers, one split across both projects (cross-project over-allocation).
    eng1 = api_create_engineer(base_url, token, "Ada Lovelace", skill_tags=["backend", "infra"])
    eng2 = api_create_engineer(base_url, token, "Alan Turing", skill_tags=["frontend"])
    for pid in (proj_a["id"], proj_b["id"]):
        api_post(base_url, token, "/team/allocations", {
            "engineer_id": eng1["id"], "project_id": pid,
            "percent_allocation": 60, "start_date": "2026-06-01", "end_date": "2026-08-01",
        })
    api_post(base_url, token, "/team/allocations", {
        "engineer_id": eng2["id"], "project_id": proj_b["id"],
        "percent_allocation": 80, "start_date": "2026-06-01", "end_date": "2026-08-15",
    })

    # Work in Alpha: a couple of statuses for the board + an assignee.
    a1 = api_create_task(base_url, token, proj_a["id"], "Design API", duration=3,
                         status="In Progress", assignee_engineer_id=eng1["id"])
    a2 = api_create_task(base_url, token, proj_a["id"], "Build API", duration=5, status="To Do")
    b1 = api_create_task(base_url, token, proj_b["id"], "Integrate", duration=4, status="To Do")
    api_post(base_url, token, "/dependencies",
             {"predecessor_id": a1["id"], "successor_id": a2["id"]})
    # Cross-project hand-off (same initiative): Alpha -> Beta.
    api_post(base_url, token, "/dependencies",
             {"predecessor_id": a2["id"], "successor_id": b1["id"]})
    api_post(base_url, token, f"/projects/{proj_a['id']}/replan", {})
    api_post(base_url, token, f"/projects/{proj_b['id']}/replan", {})

    # Architecture: two components, an accepted ADR forbidding api -> connectors.
    c_api = api_create_component(base_url, token, proj_a["id"], "api", kind="service")
    c_conn = api_create_component(base_url, token, proj_a["id"], "connectors", kind="module")
    api_post(base_url, token, "/architecture/code-bindings",
             {"component_id": c_api["id"], "path_glob": "app/api/**", "module_prefix": "app.api"})
    adr = api_create_adr(base_url, token, proj_a["id"], "Layering: api must not import connectors",
                         status="accepted", context="Keep the API layer thin.",
                         decision="api depends on services only.")
    fitness = api_post(base_url, token, f"/architecture/adrs/{adr['id']}/fitness",
                       {"kind": "forbid", "source_component_id": c_api["id"],
                        "target_component_id": c_conn["id"]})

    # An open blocker + a CI activity event (so quality risk has data).
    blocker = api_post(base_url, token, f"/tasks/{a2['id']}/blockers",
                       {"reason": "Waiting on infra access"})
    api_post(base_url, token, f"/projects/{proj_a['id']}/activity",
             {"kind": "deploy", "summary": "Deployed api v1"})

    return {
        "initiative_id": init_id,
        "project_a": proj_a["id"], "project_b": proj_b["id"],
        "project_a_name": proj_a["name"], "project_b_name": proj_b["name"],
        "eng1": eng1["id"], "eng2": eng2["id"],
        "task_a1": a1["id"], "task_a2": a2["id"], "task_b1": b1["id"],
        "component_api": c_api["id"], "component_connectors": c_conn["id"],
        "adr_id": adr["id"], "fitness_id": fitness["id"], "blocker_id": blocker["id"],
        "suffix": s,
    }
