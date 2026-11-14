"""Normalized shapes a work tracker hands the sync engine (`app/services/tracker_sync.py`).

A `WorkTracker` (`app/connectors/tracker.py`) only fetches and normalizes into these; it holds
no canopy logic. They are deliberately plain dataclasses so a new tracker is one module that
fills them in, and so the engine — upsert, parents, watermarks, history, sprints, auto-replan —
is written once for every tracker.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

# What kind of node an item is in the tracker's hierarchy.
KIND_EPIC = "epic"  # becomes a summary task (or a project, when mapping into an initiative)
KIND_ITEM = "item"  # a story / issue → a leaf task
KIND_SUBITEM = "subitem"  # a sub-task → a leaf task under its parent


@dataclass(frozen=True)
class TrackerCapabilities:
    """What a tracker supports. The engine never calls an unsupported method and the UI hides
    the matching action."""

    direct_read: bool = True  # polling / "Sync now"; False = fed only by MCP or file ingest
    hierarchy: bool = True  # parent wiring, subtree links, epic → project mapping
    status_categories: bool = False  # the tracker sends its own todo/in_progress/done category
    status_history: bool = False  # a changelog to backfill transitions from
    iterations: bool = False  # sprints / cycles to mirror
    webhooks: bool = False  # signed push notifications at /webhooks/{provider}
    create_items: bool = False  # finalise a draft plan into the tracker; "publish" on switch
    update_items: bool = False
    estimates: bool = False  # story points on pushed items
    oauth: bool = False


@dataclass(frozen=True)
class Scope:
    """Where in the tracker a binding points: a whole project/team (`project`), one item and
    its descendants (`subtree`), or a saved query (`query`). `values` holds the tracker's own
    keys (e.g. Jira `project_key`/`board_id`, Linear `team_key`)."""

    kind: str
    values: dict[str, Any] = field(default_factory=dict)
    mapping: dict[str, Any] = field(default_factory=dict)  # type/field mapping (epic types…)

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)


@dataclass(frozen=True)
class Assignee:
    account_id: str | None = None
    name: str | None = None
    email: str | None = None


@dataclass(frozen=True)
class WorkItem:
    """One tracker item, normalized — what canopy actually uses."""

    external_id: str
    key: str | None
    title: str
    status_name: str | None = None
    status_category: str | None = None  # todo | in_progress | done | cancelled, when known
    kind: str = KIND_ITEM
    parent_external_id: str | None = None
    assignee: Assignee | None = None
    iteration_external_id: str | None = None
    estimate: float | None = None
    updated: str | None = None  # the tracker's last-updated timestamp (ISO), for staleness
    url: str | None = None
    raw_type: str | None = None  # the tracker's own type name (Epic, Story…), for display


@dataclass
class ItemPage:
    items: list[WorkItem]
    watermark: str | None = None  # the cursor to pass as `since` next time


@dataclass(frozen=True)
class ItemRef:
    external_id: str
    key: str | None = None


@dataclass(frozen=True)
class StatusDef:
    """A status the tracker has, with its category and its place in the tracker's order."""

    name: str
    category: str
    position: int = 0


@dataclass(frozen=True)
class StatusChange:
    to_status: str | None
    from_status: str | None
    at: datetime
    author: str | None = None
    to_category: str | None = None


@dataclass(frozen=True)
class Iteration:
    """A sprint / cycle: dates, state (planned | active | completed) and its items."""

    external_id: str
    name: str
    state: str
    start: date | None = None
    end: date | None = None
    goal: str | None = None
    item_external_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ItemDraft:
    """Content to create in the tracker (from a reviewed draft plan) — never a status."""

    title: str
    kind: str = KIND_ITEM
    description: str | None = None
    estimate: float | None = None
    parent: ItemRef | None = None


@dataclass(frozen=True)
class ItemPatch:
    title: str | None = None
    description: str | None = None
    estimate: float | None = None


@dataclass(frozen=True)
class WebhookEvent:
    """What a verified webhook says changed: the item (when it carries one) and a scope hint
    (e.g. a Jira project key) used to find the bindings it belongs to."""

    item: WorkItem | None
    scope_hint: dict[str, Any] = field(default_factory=dict)
    deleted: bool = False
