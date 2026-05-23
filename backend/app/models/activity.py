from sqlmodel import Field

from app.models.base import TimestampMixin


class ActivityEvent(TimestampMixin, table=True):
    """A CI / observability event (deploy, build_failure, incident_open/close), tagged to
    a component where known. The minimal-viable substrate for the Activity feed (§B3),
    incident postmortem auto-open (§P2), and the quality-risk family (§Q1). Generic enough
    that Datadog / Sentry / GitHub Actions can be layered on top."""

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    kind: str = Field(index=True)  # see ActivityKind
    summary: str
    component_id: int | None = Field(default=None, foreign_key="architecturecomponent.id")
    source: str = "webhook"  # ci | webhook | system | ...
    reference: str | None = None  # external id / URL (deploy sha, incident id, run url)
