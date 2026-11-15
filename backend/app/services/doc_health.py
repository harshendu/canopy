"""Design-doc health: the flags that say a doc needs a look (pure, unit-tested).

Computed from a doc, its links and the dates/status of what its gate links point at — never
stored. Two families (USER_FLOWS §V8):

* **check flags** — `unverified` (a Claude doc no session has opened since it was registered)
  and `check_due` (a tracked doc not re-checked within `DOC_CHECK_DAYS`, or — with the
  organization artifact sync on — edited in Claude after its last check). They feed the
  sentinel's worklist and the session orientation, not the alerts.
* **attention flags** — `changed_since_approval` (a newer version than the approved one, or
  for a Claude Doc the sync saw an edit after approval), `behind_pin` (a basis link pinned an older
  version), `gate_open` (work that should wait for approval is close), `restricted` (a shared
  Claude doc was made private) and `broken` (a check could not open it). They feed the project
  alerts, the initiative digest and the coverage `needs_attention` count.

Superseded and archived docs raise nothing; a personal doc raises check flags only (it is
nobody else's business).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

CHECK_FLAGS = frozenset({"unverified", "check_due"})
ATTENTION_FLAGS = frozenset(
    {"changed_since_approval", "behind_pin", "gate_open", "restricted", "broken"}
)
_QUIET = frozenset({"superseded", "archived"})
_MILESTONE_DONE = frozenset({"hit", "done"})


@dataclass(frozen=True)
class HealthDoc:
    id: int
    title: str
    provider: str
    visibility: str
    personal: bool
    review_status: str | None
    current_version: str | None
    approved_version: str | None
    last_checked_at: datetime | None
    link_health: str
    created_at: datetime | None = None
    # when the source last changed (the organization artifact sync; Claude Docs and Sheets)
    source_updated_at: datetime | None = None
    approved_at: datetime | None = None


@dataclass(frozen=True)
class HealthLink:
    entity_type: str
    entity_id: int
    relation: str
    pinned_version: str | None = None
    label: str | None = None
    # what a gate link points at: a milestone's date + status, or a spec's status
    target_date: date | None = None
    target_status: str | None = None


@dataclass(frozen=True)
class HealthFlag:
    flag: str
    severity: str  # info | warning | error
    message: str
    entity_type: str | None = None
    entity_id: int | None = None


def _name(doc: HealthDoc) -> str:
    return f"'{doc.title}'"


def doc_health(
    doc: HealthDoc,
    links: list[HealthLink],
    *,
    now: datetime,
    check_days: int,
    gate_window_days: int,
) -> list[HealthFlag]:
    """Every flag a doc raises right now, check flags first."""
    if doc.review_status in _QUIET:
        return []
    flags: list[HealthFlag] = []
    tracked = doc.review_status is not None

    if doc.link_health == "broken":
        flags.append(HealthFlag(
            "broken", "error",
            f"Design doc {_name(doc)} could not be opened at its last check — fix or replace "
            "the link.",
        ))
    if doc.provider == "claude" and doc.last_checked_at is None:
        flags.append(HealthFlag(
            "unverified", "info",
            f"Design doc {_name(doc)} has not been opened by a session since it was registered.",
        ))
    elif (
        tracked
        and doc.last_checked_at is not None
        and doc.source_updated_at is not None
        and doc.source_updated_at > doc.last_checked_at
    ):
        flags.append(HealthFlag(
            "check_due", "info",
            f"Design doc {_name(doc)} changed in Claude after its last check.",
        ))
    elif (
        tracked
        and doc.last_checked_at is not None
        and now - doc.last_checked_at > timedelta(days=check_days)
    ):
        days = (now - doc.last_checked_at).days
        flags.append(HealthFlag(
            "check_due", "info",
            f"Design doc {_name(doc)} was last checked {days} days ago.",
        ))
    if doc.personal:
        return flags

    if doc.provider == "claude" and doc.visibility == "owner":
        flags.append(HealthFlag(
            "restricted", "error",
            f"Design doc {_name(doc)} is private in Claude again — the people it is linked "
            "for cannot open it. Share it again before it is approved or relied on.",
        ))
    if (
        doc.review_status == "approved"
        and doc.approved_version
        and doc.current_version
        and doc.approved_version != doc.current_version
    ):
        flags.append(HealthFlag(
            "changed_since_approval", "warning",
            f"Design doc {_name(doc)} changed after approval ({doc.approved_version} → "
            f"{doc.current_version}).",
        ))
    elif (
        doc.review_status == "approved"
        and doc.approved_at is not None
        and doc.source_updated_at is not None
        and doc.source_updated_at > doc.approved_at
    ):
        flags.append(HealthFlag(
            "changed_since_approval", "warning",
            f"Design doc {_name(doc)} was edited in Claude after it was approved "
            f"({doc.approved_at.date()}).",
        ))
    for link in links:
        if (
            link.relation == "basis"
            and link.pinned_version
            and doc.current_version
            and link.pinned_version != doc.current_version
        ):
            target = link.label or f"{link.entity_type} #{link.entity_id}"
            flags.append(HealthFlag(
                "behind_pin", "warning",
                f"{target} was based on {_name(doc)} at {link.pinned_version}; the doc is now "
                f"{doc.current_version} — re-check it.",
                link.entity_type, link.entity_id,
            ))
        if link.relation == "gate" and doc.review_status != "approved":
            target = link.label or f"{link.entity_type} #{link.entity_id}"
            near = (
                link.entity_type == "milestone"
                and link.target_date is not None
                and (link.target_status or "").lower() not in _MILESTONE_DONE
                and link.target_date - now.date() <= timedelta(days=gate_window_days)
            )
            waiting_spec = link.entity_type == "spec" and link.target_status == "draft"
            if near or waiting_spec:
                when = f" (due {link.target_date})" if near and link.target_date else ""
                flags.append(HealthFlag(
                    "gate_open", "warning",
                    f"{target}{when} waits on {_name(doc)}, which is not approved yet.",
                    link.entity_type, link.entity_id,
                ))
    return flags


def needs_attention(flags: list[HealthFlag]) -> bool:
    return any(f.flag in ATTENTION_FLAGS for f in flags)


def needs_check(flags: list[HealthFlag]) -> bool:
    return any(f.flag in CHECK_FLAGS for f in flags)
