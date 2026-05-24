"""Snapshot data structures: a point-in-time bundle of a project / initiative / portfolio,
assembled (in the export router) from the same aggregation logic the live views use.

These are plain holders — the PDF and CSV renderers (`export_pdf` / `export_csv`) read them
and own all formatting. Kept separate from the ORM so the renderers stay pure and testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.models.architecture import ArchitectureDecision
from app.models.project import Milestone, Project, Task
from app.schemas.entities import InitiativeRollup, ProjectSummary


@dataclass
class ProjectSnapshot:
    generated_at: datetime
    project: Project
    summary: ProjectSummary
    tasks: list[Task]
    milestones: list[Milestone]
    decisions: list[ArchitectureDecision]
    engineer_names: dict[int, str]


@dataclass
class InitiativeSnapshot:
    generated_at: datetime
    rollup: InitiativeRollup


@dataclass
class PortfolioSnapshot:
    generated_at: datetime
    projects: list[ProjectSummary]
