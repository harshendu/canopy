"""The work queue (pure, unit-tested) — docs/AGENT_EXECUTION.md §6.2.

"The queue" for a role is computed, never stored: a task is **ready for role R** when its
project takes agent work, it is a delegated, open leaf, it sits in R's stage with no live claim
(a resume, a rework or a hand-over) or in a column that feeds R's stage, nothing holds it (an
open gate, an open blocker), a pull would pass the stage's blocking entry checks and its WIP
limit, it isn't parked, it is in the active sprint of a sprint team, and the caller may work it.
`readiness` answers that for one task with the first reason it fails; `order_key` sorts ready
work — finish before starting, then the board's rank (the team's priority; no hidden score).
The database side (`app/services/work_service.py`) gathers the facts.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.models.base import AgentIntake, ClaimOutcome, ClaimState
from app.services import flow
from app.services.stage_policy import Pipeline, StageDef

# Why delegated work is not ready (the counts `GET /work/queue` reports).
REASON_INTAKE_OFF = "intake_off"
REASON_INTAKE_PAUSED = "intake_paused"
REASON_NOT_DELEGATED = "not_delegated"
REASON_CLOSED = "closed"
REASON_NOT_IN_STAGE = "not_in_stage"
REASON_CLAIMED = "claimed"
REASON_GATE_OPEN = "gate_open"
REASON_BLOCKED = "blocked"
REASON_WAITING_ON_DEPENDENCIES = "waiting_on_dependencies"
REASON_CHECKS = "checks_failed"
REASON_WIP_LIMIT = "wip_limit"
REASON_PARKED = "parked"
REASON_NOT_IN_SPRINT = "not_in_sprint"
REASON_NOT_PERMITTED = "not_permitted"
REASON_ROLE_NOT_ALLOWED = "role_not_allowed"
REASON_NO_OWNER = "no_accountable_owner"
REASON_SAME_ACTOR = "same_actor"
# A mirrored task canopy cleared to move: nothing is offered until its tracker shows the move.
REASON_AWAITING_TRACKER = "awaiting_tracker_move"

# Attempts that count toward parking: the session didn't finish the stage's work.
UNFINISHED_OUTCOMES = frozenset(
    {ClaimOutcome.expired.value, ClaimOutcome.failed.value, ClaimOutcome.released.value}
)


@dataclass
class ClaimFact:
    id: int
    task_id: int
    role: str
    stage: str
    state: str
    outcome: str | None
    claimed_at: datetime
    lease_expires_at: datetime
    agent_token_id: int | None = None
    user_id: int | None = None
    progress_note: str | None = None


@dataclass
class TaskFacts:
    task_id: int
    project_id: int
    status: str | None
    category: str | None
    is_summary: bool
    delegated: bool
    assignee_engineer_id: int | None
    rank: int
    active_claim: ClaimFact | None = None
    open_gates: int = 0
    open_blockers: int = 0
    in_active_sprint: bool | None = None  # None = no sprint constraint applies
    # Unfinished attempts per stage (casefolded name) since the last reset.
    stage_attempts: dict[str, int] = field(default_factory=dict)
    # A mirrored task canopy cleared to move but whose tracker doesn't show it yet (§17).
    awaiting_move: str | None = None


@dataclass
class CallerFacts:
    """Who is asking: may they plan the project, which engineer they are, and the token's
    narrowing (empty lists = whatever the issuer may do)."""

    may_plan: bool = False
    engineer_id: int | None = None
    roles_allowed: Sequence[str] = ()
    project_ids_allowed: Sequence[int] = ()


@dataclass
class Readiness:
    ready: bool
    reason: str | None = None
    stage: str | None = None  # the stage the task would be worked in
    pull: bool = False  # it would move from a feeder column into the stage
    detail: str | None = None

    @classmethod
    def no(cls, reason: str, *, stage: str | None = None, detail: str | None = None) -> Readiness:
        return cls(ready=False, reason=reason, stage=stage, detail=detail)


def claim_is_live(claim: ClaimFact | None, now: datetime) -> bool:
    """A claim holds its task while it is active and its lease hasn't run out. A lapsed but
    not-yet-reaped claim does not: the next claim (or the reaper) expires it."""
    return (
        claim is not None
        and claim.state == ClaimState.active.value
        and claim.lease_expires_at > now
    )


def locate(task: TaskFacts, pipeline: Pipeline, role: str) -> tuple[StageDef | None, bool]:
    """The stage of `role` this task can be worked in, and whether it would be pulled into it
    from a feeder column. (None, False) when it is in neither."""
    column = pipeline.stage(task.status)
    for stage in pipeline.stages_for(role):
        if column is not None and column.key == stage.key:
            return stage, False
    for stage in pipeline.stages_for(role):
        if column is not None and any(f.key == column.key for f in pipeline.feeders(stage)):
            return stage, True
    return None, False


def readiness(
    task: TaskFacts,
    pipeline: Pipeline,
    role: str,
    *,
    intake: str,
    caller: CallerFacts,
    now: datetime,
    entry_failures: Sequence[str] = (),
    claim_failures: Sequence[str] = (),
    wip_full: Iterable[str] = (),
) -> Readiness:
    """Is `task` ready for `role` for this caller? `entry_failures` are the blocking entry checks
    a pull into the stage would fail; `claim_failures` the claim-time checks this caller fails
    (a different session must review, …); `wip_full` the stage keys at their WIP limit under
    `block` enforcement."""
    if intake == AgentIntake.paused.value:
        return Readiness.no(REASON_INTAKE_PAUSED)
    if intake != AgentIntake.on.value:
        return Readiness.no(REASON_INTAKE_OFF)
    if not task.delegated or task.is_summary:
        return Readiness.no(REASON_NOT_DELEGATED)
    if task.category in (flow.DONE, flow.CANCELLED):
        return Readiness.no(REASON_CLOSED)
    stage, pull = locate(task, pipeline, role)
    if stage is None:
        return Readiness.no(REASON_NOT_IN_STAGE)
    name = stage.status_name
    if claim_is_live(task.active_claim, now):
        return Readiness.no(REASON_CLAIMED, stage=name)
    if task.open_gates:
        return Readiness.no(REASON_GATE_OPEN, stage=name)
    if task.awaiting_move:
        return Readiness.no(REASON_AWAITING_TRACKER, stage=name, detail=task.awaiting_move)
    if task.open_blockers:
        return Readiness.no(REASON_BLOCKED, stage=name)
    if pull and entry_failures:
        if "dependencies_done" in entry_failures:
            return Readiness.no(REASON_WAITING_ON_DEPENDENCIES, stage=name)
        if "no_open_blockers" in entry_failures:
            return Readiness.no(REASON_BLOCKED, stage=name)
        return Readiness.no(REASON_CHECKS, stage=name, detail=", ".join(entry_failures))
    if pull and stage.key in set(wip_full):
        return Readiness.no(REASON_WIP_LIMIT, stage=name)
    if task.stage_attempts.get(stage.key, 0) >= stage.max_attempts:
        return Readiness.no(REASON_PARKED, stage=name)
    if task.in_active_sprint is False:
        return Readiness.no(REASON_NOT_IN_SPRINT, stage=name)
    if caller.roles_allowed and role not in caller.roles_allowed:
        return Readiness.no(REASON_ROLE_NOT_ALLOWED, stage=name)
    if caller.project_ids_allowed and task.project_id not in caller.project_ids_allowed:
        return Readiness.no(REASON_NOT_PERMITTED, stage=name)
    if not caller.may_plan:
        mine = caller.engineer_id is not None and task.assignee_engineer_id == caller.engineer_id
        if task.assignee_engineer_id is not None and not mine:
            return Readiness.no(REASON_NOT_PERMITTED, stage=name)
    if task.assignee_engineer_id is None and caller.engineer_id is None:
        return Readiness.no(REASON_NO_OWNER, stage=name)
    if claim_failures:
        return Readiness.no(REASON_SAME_ACTOR, stage=name, detail=", ".join(claim_failures))
    return Readiness(ready=True, stage=name, pull=pull)


def order_key(task: TaskFacts, verdict: Readiness) -> tuple[int, int, int]:
    """Finish before starting: work already in the stage first, then by board rank."""
    return (1 if verdict.pull else 0, task.rank, task.task_id)


# --------------------------------------------------------------------------- #
# Leases, attempts, rework
# --------------------------------------------------------------------------- #


def lease_expiry(now: datetime, minutes: int) -> datetime:
    return now + timedelta(minutes=minutes)


def heartbeat_interval_s(lease_minutes: int) -> int:
    """How often a session should renew: a sixth of the lease, at least a minute — several
    missed heartbeats fit inside one lease (the Kubernetes / Solid Queue ratio)."""
    return max(60, lease_minutes * 60 // 6)


def unfinished_attempts(
    claims: Iterable[ClaimFact], stage_key: str, since: datetime | None
) -> int:
    """Claims in `stage_key` that ended without finishing (expired, failed, released) since
    `since` (the last reset: a person's "retry with guidance", or the return into the stage)."""
    return sum(
        1
        for c in claims
        if c.stage.casefold() == stage_key
        and c.outcome in UNFINISHED_OUTCOMES
        and (since is None or c.claimed_at >= since)
    )


@dataclass
class EventFact:
    kind: str
    at: datetime
    stage: str | None = None  # for `returned`: the stage the task was sent back to


def rework_count(events: Iterable[EventFact], stage_key: str, since: datetime | None) -> int:
    """How many times the task was sent back to `stage_key` since the last reset."""
    return sum(
        1
        for e in events
        if e.kind == "returned"
        and (e.stage or "").casefold() == stage_key
        and (since is None or e.at >= since)
    )


def next_attempt(previous: Iterable[int]) -> int:
    return max(previous, default=0) + 1
