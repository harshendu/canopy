"""Change proposals: a staging area for **agent-authored canopy changes** that a human
reviews and commits from the UI.

Where draft plans (models/draft.py) stage *outbound* work (plan → Jira tickets), a
`Proposal` stages *inbound* changes to canopy itself — tasks, dependencies, milestones,
blockers, risks, outcomes, decisions, doc links — typically assembled by a Claude session
from external signal (Slack, email, meetings, Jira, GitHub, Drive). Staged items are kept
out of the live plan (the Gantt/CPM/board never see them) until a human **applies** the
proposal in the review queue. Apply/reject are human-only (`require_human`): a bounded
agent token (§A6) can stage and withdraw, but committing the change is reserved for a
person in the UI — that *is* the review-and-commit loop.

Each item carries **provenance** (where the fact came from: a Slack thread, an email, a
meeting) and, for updates, a **before** snapshot taken at stage time so the reviewer sees
an honest diff (and staleness, when live data moved after staging).
"""

from datetime import datetime

from sqlalchemy import JSON, Column, Text
from sqlmodel import Field

from app.models.base import (
    ProposalAction,
    ProposalEntity,
    ProposalScope,
    ProposalStatus,
    TimestampMixin,
)


class Proposal(TimestampMixin, table=True):
    """A reviewable batch of staged canopy changes (the unit the human approves)."""

    id: int | None = Field(default=None, primary_key=True)
    scope_level: ProposalScope = Field(index=True)
    scope_id: int = Field(index=True)  # project_id | initiative_id
    title: str
    # The author's rationale — what was found and why these changes follow (markdown).
    summary: str | None = Field(default=None, sa_column=Column(Text))
    # Free label of the authoring surface, e.g. "claude-session (product persona)".
    origin: str | None = None
    status: ProposalStatus = Field(default=ProposalStatus.open, index=True)
    created_by_user_id: int | None = Field(default=None, foreign_key="app_user.id")
    reviewed_by_user_id: int | None = Field(default=None, foreign_key="app_user.id")
    reviewed_at: datetime | None = None
    # The reviewer's note (most useful on reject — the agent reads it and adjusts).
    review_note: str | None = Field(default=None, sa_column=Column(Text))
    applied_count: int = 0  # items actually applied (excluded ones are skipped)


class ProposalItem(TimestampMixin, table=True):
    """One staged mutation inside a proposal.

    `payload` holds the fields to set (whitelisted per entity/action in
    `services/proposals.py` — never applied via blind setattr). `ref` names a created
    entity so later items in the same proposal can point at it (`parent_ref`,
    `predecessor_ref`, …) before a real id exists. `before` is the stage-time snapshot
    of the payload's fields for update/resolve items (the reviewer's diff baseline).
    """

    id: int | None = Field(default=None, primary_key=True)
    proposal_id: int = Field(foreign_key="proposal.id", index=True)
    sort_order: int = 0
    entity_type: ProposalEntity
    action: ProposalAction
    entity_id: int | None = None  # the live target for update/resolve
    ref: str | None = None  # handle other items may reference (creates only)
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON))
    before: dict | None = Field(default=None, sa_column=Column(JSON))
    # Why this change is proposed (one line, shown next to the diff).
    reason: str | None = Field(default=None, sa_column=Column(Text))
    # Provenance: where the underlying fact came from.
    source_kind: str | None = None  # slack | email | calendar | meeting | jira | github | ...
    source_label: str | None = None  # e.g. "Slack #payments — thread of 2026-07-10"
    source_url: str | None = Field(default=None, sa_column=Column(Text))
    # Review state.
    excluded: bool = False  # reviewer opted this item out before applying
    # Audit-preserving inline override (§AA2/T17): the reviewer's per-field edits, layered OVER
    # `payload` at apply time. `payload` stays the agent's original proposal (the audit record), so
    # we can always show "agent proposed X → human changed to Y". Empty/None means no override.
    overrides: dict | None = Field(default=None, sa_column=Column(JSON))
    # Who/when last overrode. A bare int (NOT a DB foreign_key) on purpose: adding an FK to an
    # existing table forces a SQLite table rebuild (portability-hostile per CLAUDE.md); this is
    # audit metadata resolved to a name at read time, so a plain additive column is the right trade.
    overridden_by_user_id: int | None = None
    overridden_at: datetime | None = None
    applied_entity_id: int | None = None  # id of the created/updated entity after apply
    error: str | None = Field(default=None, sa_column=Column(Text))  # last validation error
