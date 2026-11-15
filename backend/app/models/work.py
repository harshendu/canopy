"""Agent work: claims, task artifacts and the work-event log (docs/AGENT_EXECUTION.md §6, §8, §11).

* `WorkClaim` — one session's lease on one task for one role. Its `id` is the handle the session
  presents on every call; every claim-bound write starts by renewing the lease with a conditional
  UPDATE, so a session whose claim was lost changes nothing (`app/services/work_service.py` is
  the only writer of `state` and of `Task.active_claim_id`).
* `TaskArtifact` — an append-only, versioned note on a task: the plan, the hand-off, a review or
  QA verdict, a note. A change is a new revision; an approval binds to the revision it approved.
* `WorkEvent` — the append-only trail of everything above (the audit log behind a task's
  execution timeline and the agent-flow metrics).

Closed sets are VARCHAR validated by StrEnums in `app/models/base.py`.
"""

from datetime import datetime

from sqlalchemy import JSON, Column, String, Text, UniqueConstraint
from sqlmodel import Field

from app.models.base import ActorKind, ClaimState, TimestampMixin, utcnow


class WorkClaim(TimestampMixin, table=True):
    id: int | None = Field(default=None, primary_key=True)
    task_id: int = Field(foreign_key="task.id", index=True)
    role: str  # the agent role claimed as (implementer | reviewer | qa | a team's own key)
    stage: str  # the column the task was in (or moved into) when claimed
    attempt: int = 1  # the nth claim on this task, across roles — an ordering
    state: str = Field(default=ClaimState.active.value, index=True)
    outcome: str | None = None  # ClaimOutcome, once the claim ends
    user_id: int = Field(foreign_key="app_user.id", index=True)  # the issuer the token acts as
    agent_token_id: int | None = Field(default=None, foreign_key="agent_token.id", index=True)
    agent_label: str | None = None  # what the session calls itself
    runner: str | None = None  # interactive | loop | headless | cloud | sdk | action
    session_ref: str | None = Field(default=None, sa_column=Column(Text))  # session id / log URL
    # The client's Idempotency-Key (else generated): a retried claim returns this claim.
    idempotency_key: str = Field(sa_column=Column(String(64), unique=True, nullable=False))
    claimed_at: datetime = Field(default_factory=utcnow)
    heartbeat_at: datetime = Field(default_factory=utcnow)
    lease_minutes: int = 30  # the stage's lease when claimed; every renewal extends by this
    lease_expires_at: datetime = Field(index=True)
    finished_at: datetime | None = None
    # Why it ended, for the heartbeat directive: taken_over | undelegated | intake_off |
    # cancelled | moved_by_person | expired | released | … (None while active).
    end_reason: str | None = None
    progress_note: str | None = Field(default=None, sa_column=Column(Text))  # last heartbeat note
    branch: str | None = None
    pr_url: str | None = Field(default=None, sa_column=Column(Text))
    # What the runner chose to report when the claim ended: turns, cost_usd, duration_s.
    usage: dict | None = Field(default=None, sa_column=Column(JSON))


class TaskArtifact(TimestampMixin, table=True):
    __table_args__ = (
        UniqueConstraint("task_id", "kind", "revision", name="uq_taskartifact_revision"),
    )

    id: int | None = Field(default=None, primary_key=True)
    task_id: int = Field(foreign_key="task.id", index=True)
    kind: str  # ArtifactKind
    revision: int = 1  # 1, 2, … per task and kind
    title: str | None = None
    body: str = Field(default="", sa_column=Column(Text, nullable=False))
    data: dict = Field(default_factory=dict, sa_column=Column(JSON))  # the structured fields (§8)
    # Promoted from `data` for the `verdict` check and for staleness against the PR head.
    verdict: str | None = None
    head_sha: str | None = None
    author_kind: str = ActorKind.agent.value  # agent | human
    author_user_id: int | None = Field(default=None, foreign_key="app_user.id")
    work_claim_id: int | None = Field(default=None, foreign_key="workclaim.id", index=True)


class WorkEvent(TimestampMixin, table=True):
    """One thing that happened to agent work on a task (or, with no task, to a project: intake,
    policy). The id columns other than task/project are plain integers (audit metadata), so the
    log never blocks deleting what it describes."""

    id: int | None = Field(default=None, primary_key=True)
    task_id: int | None = Field(default=None, foreign_key="task.id", index=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    at: datetime = Field(default_factory=utcnow, index=True)
    kind: str = Field(index=True)  # WorkEventKind
    actor_kind: str = ActorKind.system.value  # human | agent | system
    user_id: int | None = None
    agent_token_id: int | None = None
    work_claim_id: int | None = Field(default=None, index=True)
    gate_id: int | None = Field(default=None, index=True)
    artifact_id: int | None = None
    data: dict = Field(default_factory=dict, sa_column=Column(JSON))
