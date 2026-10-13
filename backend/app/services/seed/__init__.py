"""Demo / seeded-data mode.

A coherent, repository-resident dataset that fills every user-facing surface (users across all
roles + functions, teams with pods, initiatives → projects → a scheduled WBS, a cross-functional
team with availability, architecture/ADRs/drift, risk, specs, outcomes, blockers, retros, docs,
draft plans, what-if scenarios, leadership notes, and demo connectors served by an offline HTTP
mock). Loaded and reset by an admin from the UI when ``DEMO_MODE`` is on, and the substrate for
browser e2e tests. The shipped narrative is a fictional online retailer (``ecommerce.py``).

Public API:
    - ``load_seed_data(session, keep_user_ids)`` — build the full dataset (assumes empty domain).
    - ``clear_all_data(session, keep_user_ids)`` — wipe every domain table (users except kept).
    - ``reseed(session, keep_user_ids)``         — clear then load.
    - ``seed_summary(session)``                  — per-entity counts + a ``seeded`` flag.
"""

from __future__ import annotations

import logging

from app.core.config import settings
from app.services.seed.catalog import DEMO_PASSWORD, Dataset, DemoAccount
from app.services.seed.ecommerce import ECOMMERCE
from app.services.seed.loader import (
    clear_all_data,
    load_seed_data,
    reseed,
    seed_summary,
)

logger = logging.getLogger(__name__)

# Every selectable narrative, by key. ``DEMO_DATASET`` picks the default (login-screen accounts,
# reseed without an explicit choice); the admin reseed endpoint can pick any of them.
DATASETS: dict[str, Dataset] = {ECOMMERCE.key: ECOMMERCE}
DEFAULT_DATASET = ECOMMERCE.key

_warned_unknown: set[str] = set()  # warn once per stale value, not on every login-page load


def get_dataset(key: str | None = None) -> Dataset:
    """Resolve a dataset by key. An explicit unknown key raises ``KeyError``.

    With no key, ``settings.DEMO_DATASET`` decides; if it names a dataset that isn't registered
    (e.g. a stale ``.env`` from a release that shipped other datasets) this logs a warning and
    falls back to the default rather than breaking demo mode."""
    if key:
        return DATASETS[key]
    configured = settings.DEMO_DATASET
    if configured in DATASETS:
        return DATASETS[configured]
    if configured not in _warned_unknown:
        _warned_unknown.add(configured)
        logger.warning(
            "DEMO_DATASET=%r is not a registered demo dataset (have: %s); using %r",
            configured, ", ".join(sorted(DATASETS)), DEFAULT_DATASET,
        )
    return DATASETS[DEFAULT_DATASET]


def demo_accounts(key: str | None = None) -> list[DemoAccount]:
    """The demo logins of a dataset (for the login screen + admin panel + e2e)."""
    return get_dataset(key).accounts()


__all__ = [
    "DATASETS",
    "DEFAULT_DATASET",
    "DEMO_PASSWORD",
    "Dataset",
    "clear_all_data",
    "demo_accounts",
    "get_dataset",
    "load_seed_data",
    "reseed",
    "seed_summary",
]
