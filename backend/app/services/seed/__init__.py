"""Demo / seeded-data mode.

A coherent, repository-resident dataset that fills every user-facing surface (users across all
roles + functions, multiple initiatives → projects → a scheduled WBS, a cross-functional team
with availability, architecture/ADRs/drift, risk, specs, outcomes, blockers, retros, docs,
draft plans, a scenario, and demo connectors served by an offline HTTP mock). Loaded and reset
by an admin from the UI when ``DEMO_MODE`` is on, and the substrate for browser e2e tests.

Public API:
    - ``load_seed_data(session, keep_user_ids)`` — build the full dataset (assumes empty domain).
    - ``clear_all_data(session, keep_user_ids)`` — wipe every domain table (users except kept).
    - ``reseed(session, keep_user_ids)``         — clear then load.
    - ``seed_summary(session)``                  — per-entity counts + a ``seeded`` flag.
"""

from __future__ import annotations

from app.services.seed.catalog import DEMO_PASSWORD, demo_accounts
from app.services.seed.loader import (
    clear_all_data,
    load_seed_data,
    reseed,
    seed_summary,
)

__all__ = [
    "DEMO_PASSWORD",
    "clear_all_data",
    "demo_accounts",
    "load_seed_data",
    "reseed",
    "seed_summary",
]
