"""API shapes for the decision-to-code traceability ledger (PROPOSED_FLOWS §T)."""

from __future__ import annotations

from pydantic import BaseModel


class TracedTask(BaseModel):
    task_id: int
    key: str | None = None
    name: str
    status: str | None = None
    done: bool
    implements: bool
    governed: bool


class TracedPullRequest(BaseModel):
    task_id: int | None = None
    repo: str
    number: int
    url: str | None = None
    state: str
    merged: bool
    checks_state: str | None = None
    review_decision: str | None = None


class TracedReview(BaseModel):
    task_id: int
    artifact_id: int
    verdict: str | None = None
    checked: bool


class TracedFitness(BaseModel):
    fitness_id: int
    kind: str
    source: str
    target: str
    description: str | None = None
    violated: bool


class TracedDrift(BaseModel):
    drift_id: int
    kind: str
    summary: str


class DecisionTraceRead(BaseModel):
    """One decision, end to end: what implements it, the PRs and reviews behind that work, its
    fitness rules and open drift — and the verdict (computed, never stored)."""

    adr_id: int
    number: int
    title: str
    status: str
    reversibility: str | None = None
    verdict: str  # retired | pending | violated | unimplemented | at_risk | no_linked_work |
    #               in_progress | honored
    reason: str
    components: list[str] = []
    tasks: list[TracedTask] = []
    pull_requests: list[TracedPullRequest] = []
    reviews: list[TracedReview] = []
    fitness: list[TracedFitness] = []
    drift: list[TracedDrift] = []


class LedgerRow(BaseModel):
    adr_id: int
    number: int
    title: str
    status: str
    verdict: str
    reason: str
    tasks: int
    implementing: int
    done: int
    prs: int
    merged: int
    fitness: int
    violated: int
    reviews_checked: int
    open_drift: int
