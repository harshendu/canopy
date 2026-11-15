"""API shapes for stage policies and delivery rules — docs/AGENT_EXECUTION.md §9.1, §10, §13."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

_read = ConfigDict(from_attributes=True)


class StageColumnRead(BaseModel):
    """One column of a workflow with its stage policy (null = none: the built-in default, or
    a column nobody works)."""

    status: str
    category: str
    position: int
    wip_limit: int | None = None
    worked_by: str | None = None
    # What a session working it hands off (agent columns): handoff | review | qa_report.
    hands_off: str | None = None
    source: str = "none"  # policy | default | none
    policy: dict[str, Any] | None = None


class PipelineRead(BaseModel):
    scope: str  # where the columns (and so the policies) come from: project|team|template|default
    inherited: bool
    workflow_id: int | None = None
    configured: bool  # stored policies apply (False: the built-in default)
    wip_enforcement: str
    roles: list[str] = []
    columns: list[StageColumnRead]
    can_edit: bool = False


class PolicyUpdate(BaseModel):
    """Replace every policy at one scope: column name → policy document (null or absent = the
    column has none). An empty map returns the scope to the built-in default."""

    policies: dict[str, dict[str, Any] | None] = {}


class TemplateApplyRequest(BaseModel):
    template: Literal["agentic-delivery"] = "agentic-delivery"
    dry_run: bool = True
    # Where cards in columns the template doesn't have go — {"Old": "New"}; suggested by the
    # preview, and anything not named falls back to the suggestion.
    move_tasks_to: dict[str, str] = {}


class TemplateColumnRead(BaseModel):
    name: str
    category: str
    worked_by: str | None = None
    policy: dict[str, Any] | None = None


class TemplateMoveRead(BaseModel):
    from_status: str
    to_status: str
    tasks: int


class TemplatePreview(BaseModel):
    template: str
    columns: list[TemplateColumnRead]
    current_columns: list[str]
    moves: list[TemplateMoveRead]
    wip_enforcement: str
    applied: bool = False
    pipeline: PipelineRead | None = None


# --- Rules -----------------------------------------------------------------------------------


class RuleSelector(BaseModel):
    tags: list[str] = []
    components: list[int] = []
    paths: list[str] = []


class RuleCreate(BaseModel):
    scope_level: Literal["workspace", "team", "project"]
    scope_id: int = 0  # 0 for the workspace
    key: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_.-]*$")
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(default="", max_length=800)
    kind: Literal["guidance", "attestation"] = "guidance"
    roles: list[str] = []
    selector: RuleSelector = RuleSelector()
    enforcement: Literal["off", "warn", "block"] = "warn"
    locked: bool = False
    disabled: bool = False
    source_adr_id: int | None = None
    source_url: str | None = Field(default=None, max_length=2000)


class RuleUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    body: str | None = Field(default=None, max_length=800)
    kind: Literal["guidance", "attestation"] | None = None
    roles: list[str] | None = None
    selector: RuleSelector | None = None
    enforcement: Literal["off", "warn", "block"] | None = None
    locked: bool | None = None
    disabled: bool | None = None
    source_adr_id: int | None = None
    source_url: str | None = Field(default=None, max_length=2000)


class RuleRead(BaseModel):
    model_config = _read
    id: int
    scope_level: str
    scope_id: int
    key: str
    title: str
    body: str
    kind: str
    roles: list[str] = []
    selector: dict[str, Any] = {}
    enforcement: str
    locked: bool
    disabled: bool
    source_adr_id: int | None = None
    source_url: str | None = None
    created_at: datetime
    updated_at: datetime


class EffectiveRuleRead(BaseModel):
    """A rule as it applies to a project: where it came from, what it overrides, the
    enforcement after the stricter-wins merge, and whether its source decision moved on."""

    rule: RuleRead
    origin: str
    overrides: list[str] = []
    enforcement: str
    stale: bool = False
    stale_reason: str | None = None
    can_edit: bool = False
