"""API shapes for agent execution — docs/AGENT_EXECUTION.md §13."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.entities import TaskRead

_read = ConfigDict(from_attributes=True)


class AgentInfoIn(BaseModel):
    label: str | None = Field(default=None, max_length=120)
    runner: Literal["interactive", "loop", "headless", "cloud", "sdk", "action"] | None = None
    session_ref: str | None = Field(default=None, max_length=2000)


class ClaimRequest(BaseModel):
    role: str = Field(min_length=1, max_length=32)
    task_id: int | None = None
    project_id: int | None = None
    team_id: int | None = None
    repo: str | None = None
    agent: AgentInfoIn | None = None
    wait_s: int = Field(default=0, ge=0, le=25)


class ClaimRead(BaseModel):
    model_config = _read
    id: int
    task_id: int
    role: str
    stage: str
    attempt: int
    state: str
    outcome: str | None = None
    end_reason: str | None = None
    user_id: int
    agent_token_id: int | None = None
    agent_label: str | None = None
    runner: str | None = None
    session_ref: str | None = None
    claimed_at: datetime
    heartbeat_at: datetime
    lease_minutes: int
    lease_expires_at: datetime
    finished_at: datetime | None = None
    progress_note: str | None = None
    branch: str | None = None
    pr_url: str | None = None
    usage: dict[str, Any] | None = None


class ClaimResponse(BaseModel):
    claim: ClaimRead | None = None
    brief: dict[str, Any] | None = None
    retry_after_s: int | None = None
    reasons: dict[str, int] = {}
    # A mirrored task (§17): the move to make in its tracker — canopy never writes its status.
    tracker_transition: dict[str, Any] | None = None


class PlanStep(BaseModel):
    content: str = Field(min_length=1, max_length=300)
    status: Literal["pending", "in_progress", "completed", "canceled"] = "pending"


class HeartbeatRequest(BaseModel):
    note: str | None = Field(default=None, max_length=2000)
    steps: list[PlanStep] | None = None
    branch: str | None = Field(default=None, max_length=255)
    pr_url: str | None = Field(default=None, max_length=2000)


class HeartbeatResponse(BaseModel):
    directive: Literal["continue", "stop"]
    reason: str | None = None
    lease_expires_at: datetime | None = None
    heartbeat_interval_s: int


class PlanData(BaseModel):
    """The structured fields of a plan (§8). Everything is optional except what the session
    can always say: its approach."""

    approach: str = Field(min_length=1, max_length=4000)
    steps: list[PlanStep] = []
    affected_paths: list[str] = []
    affected_component_ids: list[int] = []
    change_classes: list[
        Literal["schema_migration", "public_api", "security_boundary", "data_deletion",
                "infrastructure", "dependency_upgrade"]
    ] = []
    risks: list[str] = []
    test_plan: str | None = None
    out_of_scope: str | None = None
    open_questions: list[str] = []
    confidence: Literal["high", "medium", "low"] = "medium"
    criteria_map: dict[str, str] = {}


class ArtifactCreate(BaseModel):
    kind: Literal["plan", "note"]
    title: str | None = Field(default=None, max_length=200)
    body: str = Field(default="", max_length=20000)
    data: dict[str, Any] = {}


class ArtifactRead(BaseModel):
    model_config = _read
    id: int
    task_id: int
    kind: str
    revision: int
    title: str | None = None
    body: str
    data: dict[str, Any] = {}
    verdict: str | None = None
    head_sha: str | None = None
    author_kind: str
    author_user_id: int | None = None
    work_claim_id: int | None = None
    created_at: datetime


class DecisionRead(BaseModel):
    adr_id: int
    adr: str
    title: str
    status: str
    reversibility: str | None = None
    why: str
    decision: str | None = None
    fitness: list[dict[str, Any]] = []


class PlanApproval(BaseModel):
    required: bool
    reasons: list[str] = []
    gate_id: int | None = None


class PlanResponse(BaseModel):
    artifact: ArtifactRead
    governing_decisions: list[DecisionRead]
    # The machine-checkable rules of those decisions, flattened (each names its ADR).
    fitness_rules: list[dict[str, Any]] = []
    unsettled: list[DecisionRead]
    approval: PlanApproval


class QuestionOption(BaseModel):
    value: str = Field(min_length=1, max_length=200)
    label: str | None = Field(default=None, max_length=200)


class AskRequest(BaseModel):
    kind: Literal["question", "escalation"] = "question"
    title: str = Field(min_length=1, max_length=200)
    prompt: str = Field(min_length=1, max_length=8000)
    options: list[QuestionOption] = []
    allow_text: bool = True


class VerificationRun(BaseModel):
    command: str = Field(max_length=500)
    result: str = Field(max_length=4000)


class Attestation(BaseModel):
    rule_key: str = Field(max_length=64)
    status: Literal["done", "n/a", "not_done"]
    evidence: str | None = Field(default=None, max_length=2000)


class CriterionAudit(BaseModel):
    criterion_id: int
    status: Literal["met", "unmet", "waived"]
    evidence: str | None = Field(default=None, max_length=2000)


class HandoffIn(BaseModel):
    summary: str = Field(min_length=1, max_length=4000)
    body: str = Field(default="", max_length=20000)
    pr_url: str | None = Field(default=None, max_length=2000)
    branch: str | None = Field(default=None, max_length=255)
    head_sha: str | None = Field(default=None, max_length=64)
    verification: list[VerificationRun] = []
    attestations: list[Attestation] = []
    criteria_audit: list[CriterionAudit] = []
    known_gaps: list[str] = []
    follow_ups: list[str] = []


class Finding(BaseModel):
    severity: Literal["blocker", "major", "minor", "nit"] = "major"
    path: str | None = Field(default=None, max_length=500)
    line: int | None = None
    note: str = Field(min_length=1, max_length=4000)


class QACase(BaseModel):
    criterion_id: int | None = None
    steps: str = Field(default="", max_length=4000)
    expected: str = Field(default="", max_length=2000)
    actual: str = Field(default="", max_length=2000)
    result: Literal["pass", "fail", "skipped"] = "pass"


class ReviewIn(BaseModel):
    kind: Literal["review", "qa_report"] = "review"
    verdict: Literal["pass", "concerns", "fail"]
    body: str = Field(default="", max_length=20000)
    findings: list[Finding] = []
    cases: list[QACase] = []
    checked: list[str] = []
    head_sha: str | None = Field(default=None, max_length=64)


class SubmitRequest(BaseModel):
    handoff: HandoffIn | None = None
    review: ReviewIn | None = None
    to_status: str | None = None
    usage: dict[str, Any] | None = None


class ReleaseRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    note: str | None = Field(default=None, max_length=2000)
    needs_human: bool = False
    usage: dict[str, Any] | None = None  # what the session cost, when the runner knows


class UsageReport(BaseModel):
    """What a session cost, reported by its runner after the session ended (§15). Team-level
    accounting only: it feeds the agent-flow cost per task, never a per-person figure."""

    cost_usd: float | None = Field(default=None, ge=0)
    turns: int | None = Field(default=None, ge=0)
    duration_s: float | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cache_read_input_tokens: int | None = Field(default=None, ge=0)
    model: str | None = Field(default=None, max_length=64)
    outcome: str | None = Field(default=None, max_length=64)  # the runner's view: success, …


class GateRead(BaseModel):
    model_config = _read
    id: int
    task_id: int
    project_id: int
    kind: str
    origin: str
    stage: str | None = None
    status: str
    title: str
    prompt: str | None = None
    options: list[dict[str, Any]] = []
    allow_text: bool = True
    allowed_decisions: list[str] = []
    reasons: list[str] = []
    evidence: dict[str, Any] = {}
    subject_artifact_id: int | None = None
    requested_by_claim_id: int | None = None
    requested_by_user_id: int | None = None
    approvers: str
    exclude_requester: bool = False
    satisfied_by: list[str] = []
    remind_at: datetime | None = None
    escalate_at: datetime | None = None
    escalation_level: int = 0
    on_approve: str | None = None
    on_changes: str | None = None
    on_reject: str | None = None
    decision: str | None = None
    decided_by_user_id: int | None = None
    decided_by_label: str | None = None
    decided_via: str | None = None
    decided_at: datetime | None = None
    response_note: str | None = None
    response_data: dict[str, Any] = {}
    routed_at: datetime | None = None
    created_at: datetime
    # Derived for the inbox.
    task_key: str | None = None
    task_name: str | None = None
    project_key: str | None = None
    requester_name: str | None = None
    age_hours: float = 0.0
    may_decide: bool = False
    waiting_for_evidence: bool = False
    # A mirrored task this gate cleared to move: make the move in its tracker (§17).
    tracker_transition: dict[str, Any] | None = None


class WorkEventRead(BaseModel):
    model_config = _read
    id: int
    task_id: int | None = None
    project_id: int
    at: datetime
    kind: str
    actor_kind: str
    user_id: int | None = None
    agent_token_id: int | None = None
    work_claim_id: int | None = None
    gate_id: int | None = None
    artifact_id: int | None = None
    data: dict[str, Any] = {}


class GateDetail(BaseModel):
    gate: GateRead
    task: TaskRead
    subject: ArtifactRead | None = None
    previous: ArtifactRead | None = None
    handoff: ArtifactRead | None = None
    reviews: list[ArtifactRead] = []
    trail: list[WorkEventRead] = []


class GateDecideRequest(BaseModel):
    decision: str
    note: str | None = Field(default=None, max_length=8000)
    option: str | None = Field(default=None, max_length=200)
    plan: dict[str, Any] | None = None
    subject_revision: int | None = None


class GateReassignRequest(BaseModel):
    approver_engineer_ids: list[int] = Field(min_length=1)


class SubmitResponse(BaseModel):
    claim: ClaimRead
    task: TaskRead
    moved_to: str | None = None
    # A mirrored task: canopy cleared the move instead of making it — make it in the tracker
    # (`tracker_transition`), or let the tracker's automation (§17).
    cleared_to: str | None = None
    tracker_transition: dict[str, Any] | None = None
    gate: GateRead | None = None
    evaluation: dict[str, Any] = {}
    warnings: list[str] = []


class QueueItemRead(BaseModel):
    task_id: int
    key: str | None = None
    name: str
    project_id: int
    project_key: str
    status: str | None = None
    stage: str
    pull: bool
    rank: int


class QueueResponse(BaseModel):
    role: str
    roles: list[str] = []
    ready: list[QueueItemRead] = []
    reasons: dict[str, int] = {}


class DelegationRequest(BaseModel):
    delegation: Literal["agent"] | None = None


class DelegationResponse(BaseModel):
    task: TaskRead
    hints: list[str] = []


class IntakeRequest(BaseModel):
    state: Literal["off", "on", "paused"]


class IntakeResponse(BaseModel):
    project_id: int
    agent_intake: str
    stopped: int = 0


class ComponentsRequest(BaseModel):
    component_ids: list[int] = []


class ComponentsResponse(BaseModel):
    task_id: int
    component_ids: list[int]


class ExecutionResponse(BaseModel):
    task_id: int
    delegation: str | None = None
    stage: str | None = None
    worked_by: str | None = None
    active_claim: ClaimRead | None = None
    claims: list[ClaimRead] = []
    artifacts: list[ArtifactRead] = []
    gates: list[GateRead] = []
    events: list[WorkEventRead] = []
    exit_contract: dict[str, Any] | None = None
    readiness: dict[str, Any] | None = None
    tracker_transition: dict[str, Any] | None = None  # a mirrored task's pending move (§17)


class StageRead(BaseModel):
    status: str
    category: str
    worked_by: str | None = None
    source: str = "none"


class AgentsWorkingRead(BaseModel):
    claim: ClaimRead
    task_key: str | None = None
    task_name: str
    heartbeat_age_s: int


class ParkedRead(BaseModel):
    task_id: int
    key: str | None = None
    name: str
    gate_id: int


class AgentsViewResponse(BaseModel):
    project_id: int
    agent_intake: str
    can_manage: bool
    configured: bool
    stages: list[StageRead]
    ready: dict[str, list[QueueItemRead]] = {}
    reasons: dict[str, int] = {}
    working: list[AgentsWorkingRead] = []
    waiting: list[GateRead] = []
    parked: list[ParkedRead] = []
    delegated: int = 0


class AgentFlowResponse(BaseModel):
    """Agent-flow metrics for a project, initiative or team (docs/AGENT_EXECUTION.md §19) —
    team-level by design; `sufficient: false` (with `reason`) on thin data."""

    scope: str
    scope_id: int
    weeks: int
    since: datetime
    projects: int
    sufficient: bool
    reason: str | None = None
    queue: dict[str, Any]
    human_wait: dict[str, Any]
    first_pass: dict[str, Any]
    rework: dict[str, Any]
    claims: dict[str, Any]
    flow_efficiency: float | None = None
    gate_load: dict[str, Any]
    gates_as_experiments: list[dict[str, Any]] = []
    unassisted_share: float | None = None
    agent_tasks_done: int = 0
    cost_per_task_usd: float | None = None
