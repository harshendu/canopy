"""Snapshot data structures: a point-in-time bundle of a project / initiative / portfolio,
assembled (in the export router) from the same aggregation logic the live views use.

These are plain holders — the PDF and CSV renderers (`export_pdf` / `export_csv`) read them
and own all formatting. Kept separate from the ORM so the renderers stay pure and testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.models.architecture import ArchitectureDecision
from app.models.project import Milestone, Project, Task
from app.schemas.entities import InitiativeRollup, ProjectSummary


@dataclass
class DocRow:
    """One shared design doc in a snapshot (§V9): what it is, its review state and version,
    and where it lives — the link, never the content."""

    title: str
    kind: str
    status: str  # approved | in review | draft | link | superseded
    version: str
    provider: str
    url: str


@dataclass
class ProjectSnapshot:
    generated_at: datetime
    project: Project
    summary: ProjectSummary
    tasks: list[Task]
    milestones: list[Milestone]
    decisions: list[ArchitectureDecision]
    engineer_names: dict[int, str]
    docs: list[DocRow] = field(default_factory=list)


@dataclass
class InitiativeSnapshot:
    generated_at: datetime
    rollup: InitiativeRollup
    docs: list[DocRow] = field(default_factory=list)


@dataclass
class PortfolioSnapshot:
    generated_at: datetime
    projects: list[ProjectSummary]
