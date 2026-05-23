from datetime import date

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field

from app.models.base import (
    ADRCommentKind,
    ADRStatus,
    Reversibility,
    TimestampMixin,
)


class ArchitectureComponent(TimestampMixin, table=True):
    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    name: str
    kind: str = "service"  # service | module | datastore | external | ui
    description: str | None = None
    repo_url: str | None = None


class ComponentLink(TimestampMixin, table=True):
    """A directed relationship between two architecture components (the system map edges)."""

    __table_args__ = (UniqueConstraint("source_id", "target_id", name="uq_component_link"),)

    id: int | None = Field(default=None, primary_key=True)
    source_id: int = Field(foreign_key="architecturecomponent.id", index=True)
    target_id: int = Field(foreign_key="architecturecomponent.id", index=True)
    kind: str = "depends_on"  # depends_on | calls | publishes_to | reads_from


class ArchitectureDecision(TimestampMixin, table=True):
    """An ADR — a first-class *decision*, with a supersession chain, PR links, a review
    lifecycle, and a comment thread. The decision (not the task) is the architect's unit
    of work; tasks can be blocked on an ADR reaching `accepted`."""

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    number: int  # sequential within a project, e.g. ADR-0007
    title: str
    status: ADRStatus = Field(default=ADRStatus.proposed)
    context: str | None = None
    decision: str | None = None
    consequences: str | None = None
    alternatives: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    reversibility: Reversibility | None = None
    decision_owner_id: int | None = Field(default=None, foreign_key="engineer.id")
    proposed_by_id: int | None = Field(default=None, foreign_key="engineer.id")
    decide_by: date | None = None  # required while status is `deferred`
    rfc_url: str | None = None  # optional link to an external RFC doc (Drive/repo)
    supersedes_id: int | None = Field(default=None, foreign_key="architecturedecision.id")
    pr_links: list[str] = Field(default_factory=list, sa_column=Column(JSON))


class ADRComponentLink(TimestampMixin, table=True):
    """M:N link between ADRs and the components they affect."""

    adr_id: int = Field(foreign_key="architecturedecision.id", primary_key=True)
    component_id: int = Field(foreign_key="architecturecomponent.id", primary_key=True)


class ADRStakeholder(TimestampMixin, table=True):
    """An engineer who must review an ADR (their latest comment carries their decision)."""

    adr_id: int = Field(foreign_key="architecturedecision.id", primary_key=True)
    engineer_id: int = Field(foreign_key="engineer.id", primary_key=True)


class ADRComment(TimestampMixin, table=True):
    """A message on an ADR's thread. `kind` doubles as a formal review action when an
    engineer approves / requests changes / rejects (plain `comment` otherwise)."""

    id: int | None = Field(default=None, primary_key=True)
    adr_id: int = Field(foreign_key="architecturedecision.id", index=True)
    engineer_id: int | None = Field(default=None, foreign_key="engineer.id")
    author_name: str | None = None  # fallback label when no engineer is linked
    body: str
    kind: ADRCommentKind = Field(default=ADRCommentKind.comment)


class ComponentCodeBinding(TimestampMixin, table=True):
    """Where a component lives in code — the linchpin for drift detection. A component
    can have several bindings (e.g. a service split across paths)."""

    id: int | None = Field(default=None, primary_key=True)
    component_id: int = Field(foreign_key="architecturecomponent.id", index=True)
    connection_id: int | None = Field(default=None, foreign_key="connection.id")
    repo: str | None = None  # owner/repo (defaults to the connection's configured repo)
    path_glob: str  # e.g. "backend/app/services/**"
    module_prefix: str | None = None  # e.g. "app.services" — maps imports back to this component


class DriftEvent(TimestampMixin, table=True):
    """A detected divergence between the declared architecture and the code (or the
    decision record). Triaged via the drift queue; reconciliation sets `status`."""

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    kind: str  # unexpected_dependency | dead_dependency | unimplemented_adr | implicit_decision
    rule_key: str = Field(index=True)  # stable id for dedupe + suppression
    summary: str
    detail: str | None = None
    suspected_cause: str | None = None  # PR/commit reference, when known
    affected_component_ids: list[int] = Field(default_factory=list, sa_column=Column(JSON))
    status: str = "open"  # open | accepted | rejected | false_positive


class DriftSuppression(TimestampMixin, table=True):
    """A per-project rule the detector learns to ignore (from `false_positive` triage)."""

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    rule_key: str = Field(index=True)
