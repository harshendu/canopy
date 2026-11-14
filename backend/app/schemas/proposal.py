"""Request/response shapes for change proposals (the agent→human review queue)."""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.base import ProposalAction, ProposalEntity, ProposalScope, ProposalStatus
from app.schemas.entities import GanttResponse

_read = ConfigDict(from_attributes=True)


class ProposalItemIn(BaseModel):
    entity_type: ProposalEntity
    action: ProposalAction
    payload: dict[str, Any] = Field(default_factory=dict)
    entity_id: int | None = None  # required for update/resolve
    ref: str | None = None  # handle later items can point at (creates only)
    reason: str | None = None
    source_kind: str | None = None  # slack | email | calendar | meeting | jira | github | ...
    source_label: str | None = None
    source_url: str | None = None


class ProposalCreate(BaseModel):
    scope_level: ProposalScope
    scope_id: int
    title: str
    summary: str | None = None
    origin: str | None = None  # authoring surface, e.g. "claude-session (product persona)"
    items: list[ProposalItemIn] = Field(min_length=1)


class ProposalItemRead(BaseModel):
    model_config = _read
    id: int
    sort_order: int
    entity_type: ProposalEntity
    action: ProposalAction
    entity_id: int | None
    ref: str | None
    payload: dict[str, Any]
    before: dict[str, Any] | None
    reason: str | None
    source_kind: str | None
    source_label: str | None
    source_url: str | None
    excluded: bool
    # Audit-preserving inline override (§AA2/T17): the reviewer's per-field edits (kept separate
    # from the agent's original `payload`) + who/when. `overridden_by` is the resolved display name.
    overrides: dict[str, Any] | None = None
    overridden_by_user_id: int | None = None
    overridden_by: str | None = None
    overridden_at: datetime | None = None
    applied_entity_id: int | None
    error: str | None
    # The proposal revision that added or last rewrote this item (§AA5) — equal to the
    # proposal's own `revision` means "changed in the latest revise".
    revision: int = 1


class ProposalItemDetail(ProposalItemRead):
    """Item plus the live values recomputed at read time — `stale` flags targets that
    moved since the before-snapshot was taken (or vanished entirely)."""

    current: dict[str, Any] | None = None
    stale: bool = False
    # Whitelisted fields the proposal doesn't set yet that the reviewer may add inline.
    addable_fields: list[str] = Field(default_factory=list)


class ProposalRead(BaseModel):
    model_config = _read
    id: int
    scope_level: ProposalScope
    scope_id: int
    title: str
    summary: str | None
    origin: str | None
    status: ProposalStatus
    created_by_user_id: int | None
    reviewed_by_user_id: int | None
    reviewed_at: datetime | None
    review_note: str | None
    applied_count: int
    created_at: datetime
    item_count: int = 0
    excluded_count: int = 0
    # Triage aids so the collapsed review-queue card is scannable without expanding it (§AA/T17):
    action_counts: dict[str, int] = Field(default_factory=dict)  # {"create": n, "update": n, …}
    # items that errored or drifted (stale) since staging — look before applying:
    attention_count: int = 0
    scope_label: str | None = None  # resolved project/initiative key+name for display
    # Co-review trail (§AA5): bumped each time the author revises the open proposal in place.
    revision: int = 1
    revised_at: datetime | None = None
    revision_note: str | None = None  # the author's "what changed" line for the last revise
    created_by: str | None = None  # resolved display name of the author


class ProposalDetail(ProposalRead):
    items: list[ProposalItemDetail] = Field(default_factory=list)
    # Display names for the ids the items mention, bucketed by kind
    # (`task` | `engineer` | `project` | `initiative` | `spec`) and keyed by the id as a
    # string — so a reader sees "Dana Lee", not `assignee_engineer_id: 14`.
    lookups: dict[str, dict[str, str]] = Field(default_factory=dict)


class ProposalItemPatch(BaseModel):
    # Both optional so a patch can toggle inclusion, set field overrides, or both. Only the fields
    # present in the request are applied (distinguished via model_fields_set). For `overrides`,
    # an empty object clears the reviewer's override (revert to the agent's proposed values).
    excluded: bool | None = None
    overrides: dict[str, Any] | None = None


class ProposalItemsBulkPatch(BaseModel):
    """Include / exclude many items in one go ("exclude all risks"). `item_ids=None` = all."""

    excluded: bool
    item_ids: list[int] | None = None


# --- Revise an open proposal in place (the conversational co-review loop, §AA5) ---


class ProposalItemRevision(BaseModel):
    """A rewrite of one staged item. `payload` is **merged** into the staged payload (only the
    keys you pass change); `remove_fields` drops keys. An item's entity/action/target can't
    change — remove it and add a new one instead."""

    item_id: int
    payload: dict[str, Any] = Field(default_factory=dict)
    remove_fields: list[str] = Field(default_factory=list)
    reason: str | None = None
    source_kind: str | None = None
    source_label: str | None = None
    source_url: str | None = None


class ProposalReviseRequest(BaseModel):
    title: str | None = None
    summary: str | None = None
    # One line on what this revision changed — shown to the reviewer as it lands.
    note: str | None = None
    add_items: list[ProposalItemIn] = Field(default_factory=list)
    update_items: list[ProposalItemRevision] = Field(default_factory=list)
    remove_item_ids: list[int] = Field(default_factory=list)


class ProposalRejectRequest(BaseModel):
    note: str | None = None


class ProposalApplyResult(BaseModel):
    proposal: ProposalRead
    applied: int
    skipped: int
    replanned_projects: list[int]


# --- Plan preview: the plan as a whole, before vs after the proposal (§AA2) ---

TaskChangeKind = Literal["added", "edited", "shifted"]
MilestoneChangeKind = Literal["added", "edited", "unchanged"]


class PreviewIssue(BaseModel):
    """Why the proposal cannot be applied as it stands (known before clicking Apply)."""

    item_id: int | None = None  # None for a whole-project problem (a dependency cycle)
    project_id: int | None = None
    error: str


class PreviewTaskChange(BaseModel):
    """One task whose place in the plan differs between the current and proposed state."""

    task_id: int  # live id; a task the proposal creates gets a synthetic negative id
    name: str
    kind: TaskChangeKind  # added | edited (targeted by an item) | shifted (knock-on)
    is_summary: bool = False
    item_ids: list[int] = Field(default_factory=list)  # the proposal items behind the change
    start_before: date | None = None
    start_after: date | None = None
    end_before: date | None = None
    end_after: date | None = None
    end_delta_days: int | None = None  # calendar days the finish moves (+ = later)
    critical_before: bool = False
    critical_after: bool = False


class PreviewMilestone(BaseModel):
    milestone_id: int  # synthetic negative id for a milestone the proposal creates
    name: str
    kind: MilestoneChangeKind
    item_ids: list[int] = Field(default_factory=list)
    target_before: date | None = None
    target_after: date | None = None
    status_before: str | None = None
    status_after: str | None = None


class PreviewDeadlineMiss(BaseModel):
    task_id: int
    name: str
    deadline: date
    end: date


class ProjectPlanPreview(BaseModel):
    """One project's schedule in both states. `current` is the live plan recomputed with the
    same scheduler apply uses, so every difference from `proposed` is the proposal's doing."""

    project_id: int
    key: str
    name: str
    current: GanttResponse
    proposed: GanttResponse | None = None  # None when the staged dependencies form a cycle
    end_current: date | None = None
    end_proposed: date | None = None
    end_delta_days: int | None = None  # calendar days the project finish moves (+ = later)
    critical_current: int = 0
    critical_proposed: int = 0
    task_changes: list[PreviewTaskChange] = Field(default_factory=list)
    milestones: list[PreviewMilestone] = Field(default_factory=list)
    new_deadline_misses: list[PreviewDeadlineMiss] = Field(default_factory=list)
    # The saved schedule was out of date (edits since the last replan), so `current` differs
    # from what the Schedule tab shows until someone replans.
    live_schedule_stale: bool = False
    cycle: bool = False


class PreviewCounts(BaseModel):
    """Headline tallies over the items that would apply (excluded ones don't count)."""

    tasks_added: int = 0
    tasks_edited: int = 0
    tasks_shifted: int = 0  # leaf tasks that move as a knock-on effect
    dependencies_added: int = 0
    milestones_added: int = 0
    milestones_edited: int = 0
    blockers_raised: int = 0
    blockers_resolved: int = 0
    risks_added: int = 0
    risks_edited: int = 0
    outcomes_added: int = 0
    outcomes_edited: int = 0
    decisions_added: int = 0
    docs_added: int = 0


class ProposalPreview(BaseModel):
    proposal_id: int
    revision: int
    included: int
    excluded: int
    can_apply: bool
    issues: list[PreviewIssue] = Field(default_factory=list)
    counts: PreviewCounts = Field(default_factory=PreviewCounts)
    projects: list[ProjectPlanPreview] = Field(default_factory=list)
