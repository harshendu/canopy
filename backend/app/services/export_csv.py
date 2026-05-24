"""CSV renderers for export snapshots — the headline tabular dataset per scope:
a project's tasks, or the sub-project / portfolio rollup table. Pure (no DB/IO)."""

from __future__ import annotations

import csv
import io

from app.models.base import TaskType
from app.schemas.entities import ProjectSummary
from app.services.snapshot import InitiativeSnapshot, PortfolioSnapshot, ProjectSnapshot


def _encode(rows: list[list[str]]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


def _date(value: object) -> str:
    return str(value) if value is not None else ""


def project_csv(snap: ProjectSnapshot) -> bytes:
    """One row per task — the project's work breakdown as a spreadsheet."""
    names = {t.id: t.name for t in snap.tasks if t.id is not None}
    rows: list[list[str]] = [
        [
            "ID",
            "Name",
            "Type",
            "Parent",
            "Start",
            "End",
            "Duration (days)",
            "% Complete",
            "Critical",
            "Status",
            "Deadline",
            "Assignee",
        ]
    ]
    for t in snap.tasks:
        parent = names.get(t.parent_id, "") if t.parent_id is not None else ""
        assignee = (
            snap.engineer_names.get(t.assignee_engineer_id, "")
            if t.assignee_engineer_id is not None
            else ""
        )
        rows.append(
            [
                str(t.id),
                t.name,
                t.type.value if isinstance(t.type, TaskType) else str(t.type),
                parent,
                _date(t.start),
                _date(t.end),
                str(t.duration),
                f"{t.percent_complete:g}",
                "yes" if t.is_critical else "no",
                t.status or "",
                _date(t.deadline),
                assignee,
            ]
        )
    return _encode(rows)


def _summary_rows(projects: list[ProjectSummary]) -> list[list[str]]:
    rows: list[list[str]] = [
        [
            "Key",
            "Name",
            "Total tasks",
            "Completed",
            "Avg % complete",
            "Project end",
            "Target date",
            "Risk score",
            "Risk level",
            "Drift score",
            "Drift level",
        ]
    ]
    for s in projects:
        rows.append(
            [
                s.key,
                s.name,
                str(s.total_tasks),
                str(s.completed_tasks),
                f"{s.avg_percent_complete:g}",
                _date(s.project_end),
                _date(s.target_date),
                str(s.risk_score),
                s.risk_level,
                str(s.drift_score),
                s.drift_level,
            ]
        )
    return rows


def initiative_csv(snap: InitiativeSnapshot) -> bytes:
    """One row per sub-project (the initiative rollup table)."""
    return _encode(_summary_rows(snap.rollup.projects))


def portfolio_csv(snap: PortfolioSnapshot) -> bytes:
    """One row per project (the portfolio table)."""
    return _encode(_summary_rows(snap.projects))
