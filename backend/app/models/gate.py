"""Gates: blocking requests for a human decision on one task (docs/AGENT_EXECUTION.md §9.4).

While a gate is open its task is **held** — not ready for any role, and nothing advances it. A
gate opens when a checkpoint fires, when a task enters a decision column, when an agent asks
(`question` / `escalation`), or when canopy parks a task. A person answers in the Reviews inbox;
the decision routes the task. `app/services/gates.py` is the only writer of `status` and
`decision`; deciding is human-only (no MCP tool can do it).
"""

from datetime import datetime

from sqlalchemy import JSON, Column, Text
from sqlmodel import Field

from app.models.base import GateStatus, TimestampMixin


class Gate(TimestampMixin, table=True):
    id: int | None = Field(default=None, primary_key=True)
    task_id: int = Field(foreign_key="task.id", index=True)
    project_id: int = Field(foreign_key="project.id", index=True)  # denormalised for the inbox
    kind: str = Field(index=True)  # GateKind (a policy may name its own)
    origin: str  # GateOrigin: checkpoint | column | agent | system
    stage: str | None = None  # the column the task was held in
    status: str = Field(default=GateStatus.open.value, index=True)
    title: str
    prompt: str | None = Field(default=None, sa_column=Column(Text))
    # For a question: [{"value": "...", "label": "..."}]; `allow_text` lives in `options` meta.
    options: list = Field(default_factory=list, sa_column=Column(JSON))
    allow_text: bool = True
    allowed_decisions: list = Field(default_factory=list, sa_column=Column(JSON))
    reasons: list = Field(default_factory=list, sa_column=Column(JSON))  # why a person is asked
    evidence: dict = Field(default_factory=dict, sa_column=Column(JSON))  # snapshot when opened
    subject_artifact_id: int | None = Field(default=None, foreign_key="taskartifact.id")
    requested_by_claim_id: int | None = Field(default=None, foreign_key="workclaim.id")
    requested_by_user_id: int | None = Field(default=None, foreign_key="app_user.id")
    # Who may decide, resolved from policy when the gate opens.
    approvers: str = "project_planners"
    approver_engineer_ids: list = Field(default_factory=list, sa_column=Column(JSON))
    exclude_requester: bool = False
    satisfied_by: list = Field(default_factory=list, sa_column=Column(JSON))
    remind_at: datetime | None = None
    escalate_at: datetime | None = None
    escalation_level: int = 0
    # Routing, resolved when the gate opens so a later policy edit doesn't re-route waiting work.
    on_approve: str | None = None
    on_changes: str | None = None
    on_reject: str | None = None
    # The decision.
    decision: str | None = None  # GateDecision
    decided_by_user_id: int | None = Field(default=None, foreign_key="app_user.id")
    decided_by_label: str | None = None  # e.g. a GitHub login that maps to no canopy user
    decided_via: str | None = None  # DecidedVia
    decided_at: datetime | None = None
    response_note: str | None = Field(default=None, sa_column=Column(Text))
    response_data: dict = Field(default_factory=dict, sa_column=Column(JSON))
    routed_at: datetime | None = None  # the routing move happened (an approval may wait)
