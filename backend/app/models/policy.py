"""Stage policies and delivery rules — docs/AGENT_EXECUTION.md §9.1 and §10.

* `StagePolicy` — the policy of one workflow column: who works it (an agent role, people, or
  nobody), what must be true to enter it (typed checks), the plan / hand-off checkpoints, a
  decision column's gate, and the lease / attempt / rework limits. Keyed by column *name* on its
  owner (a `Workflow`, or a tracker binding for mirrored projects), because saving a workflow
  replaces its `WorkflowStatus` rows; `workflow.save_workflow` carries a policy across a rename
  and drops it with a removed column. The JSON documents are validated by the pure
  `app/services/stage_policy.py` before they are stored.
* `DeliveryRule` — a team's working agreement: guidance delivered in the brief, or a
  Definition-of-Done item a hand-off must attest. Workspace (scope id 0) → team → project, nearest
  wins unless a higher rule is locked. Not called `Rule`: `RULE` is a PostgreSQL keyword.
"""

from sqlalchemy import JSON, Column, Text, UniqueConstraint
from sqlmodel import Field

from app.models.base import TimestampMixin


class StagePolicy(TimestampMixin, table=True):
    __table_args__ = (
        UniqueConstraint("owner_type", "owner_id", "status_name", name="uq_stagepolicy_column"),
    )

    id: int | None = Field(default=None, primary_key=True)
    owner_type: str = "workflow"  # workflow | binding (a tracker's statuses, mirrored projects)
    owner_id: int = Field(index=True)
    status_name: str
    worked_by: str | None = None  # None (a queue) | "human" (a decision column) | an agent role
    artifact: str | None = None  # what the stage hands off: handoff | review | qa_report
    instructions: str = Field(default="", sa_column=Column(Text, nullable=False))
    pulls_from: list | None = Field(default=None, sa_column=Column(JSON))
    enter: dict = Field(default_factory=dict, sa_column=Column(JSON))  # {"checks": [...]}
    on_changes: str | None = None
    decision: dict | None = Field(default=None, sa_column=Column(JSON))
    checkpoints: dict = Field(default_factory=dict, sa_column=Column(JSON))
    lease_minutes: int | None = None
    max_attempts: int | None = None
    max_rework: int | None = None
    updated_by_user_id: int | None = None  # audit metadata (plain integer, never blocks deletes)


class DeliveryRule(TimestampMixin, table=True):
    __table_args__ = (
        UniqueConstraint("scope_level", "scope_id", "key", name="uq_deliveryrule_key"),
    )

    id: int | None = Field(default=None, primary_key=True)
    scope_level: str = Field(index=True)  # RuleScope: workspace | team | project
    scope_id: int = Field(default=0, index=True)  # 0 for the workspace
    key: str  # a stable slug — a lower scope's rule with the same key replaces this one
    title: str
    body: str = Field(default="", sa_column=Column(Text, nullable=False))  # ≤ 800 chars
    kind: str = "guidance"  # RuleKind: guidance (in the brief) | attestation (Definition of Done)
    roles: list = Field(default_factory=list, sa_column=Column(JSON))  # agent roles; [] = all
    # Optional narrowing: {"tags": [...], "components": [ids], "paths": [globs]}.
    selector: dict = Field(default_factory=dict, sa_column=Column(JSON))
    enforcement: str = "warn"  # off | warn | block — for attestations
    locked: bool = False  # a lower scope may not override or disable it
    disabled: bool = False  # this scope switches off an inherited rule of the same key
    source_adr_id: int | None = None  # the decision it comes from (stale when superseded)
    source_url: str | None = Field(default=None, sa_column=Column(Text))
    created_by_user_id: int | None = None
