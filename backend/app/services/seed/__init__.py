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

from app.core.config import settings
from app.services.seed.agentic import AGENTIC
from app.services.seed.catalog import DEMO_PASSWORD, HELIX, Dataset, DemoAccount
from app.services.seed.loader import (
    clear_all_data,
    load_seed_data,
    reseed,
    seed_summary,
)

# Every selectable narrative, by key. ``DEMO_DATASET`` picks the default (login-screen accounts,
# reseed without an explicit choice); the admin reseed endpoint can pick any of them.
DATASETS: dict[str, Dataset] = {HELIX.key: HELIX, AGENTIC.key: AGENTIC}


def get_dataset(key: str | None = None) -> Dataset:
    """Resolve a dataset by key (default: ``settings.DEMO_DATASET``; unknown keys → KeyError)."""
    return DATASETS[key or settings.DEMO_DATASET]


def demo_accounts(key: str | None = None) -> list[DemoAccount]:
    """The demo logins of a dataset (for the login screen + admin panel + e2e)."""
    return get_dataset(key).accounts()


__all__ = [
    "DATASETS",
    "DEMO_PASSWORD",
    "Dataset",
    "clear_all_data",
    "demo_accounts",
    "get_dataset",
    "load_seed_data",
    "reseed",
    "seed_summary",
]
