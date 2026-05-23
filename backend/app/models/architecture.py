from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field

from app.models.base import ADRStatus, TimestampMixin


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
    """An ADR — first-class, with a supersession chain and PR links."""

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    number: int  # sequential within a project, e.g. ADR-0007
    title: str
    status: ADRStatus = Field(default=ADRStatus.proposed)
    context: str | None = None
    decision: str | None = None
    consequences: str | None = None
    supersedes_id: int | None = Field(default=None, foreign_key="architecturedecision.id")
    pr_links: list[str] = Field(default_factory=list, sa_column=Column(JSON))


class ADRComponentLink(TimestampMixin, table=True):
    """M:N link between ADRs and the components they affect."""

    adr_id: int = Field(foreign_key="architecturedecision.id", primary_key=True)
    component_id: int = Field(foreign_key="architecturecomponent.id", primary_key=True)
