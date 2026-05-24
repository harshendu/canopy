"""PDF renderers for export snapshots (reportlab — pure Python, no headless browser).

A snapshot PDF leads with headline stats, then the signature **Gantt** drawn as vector bars,
then the data tables. Kept dependency-light and CI-safe (matches canopy's no-browser stance).
"""

from __future__ import annotations

import io
from datetime import date

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Flowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.models.base import TaskType
from app.models.project import Task
from app.schemas.entities import ProjectSummary
from app.services.snapshot import InitiativeSnapshot, PortfolioSnapshot, ProjectSnapshot

_HEADER_BG = colors.HexColor("#166534")  # canopy green
_CRITICAL = colors.HexColor("#dc2626")
_SUMMARY = colors.HexColor("#1e293b")
_BAR = colors.HexColor("#16a34a")
_GRID = colors.HexColor("#cbd5e1")

_styles = getSampleStyleSheet()
_CELL = ParagraphStyle("cell", parent=_styles["Normal"], fontSize=8, leading=10)
_META = ParagraphStyle(
    "meta", parent=_styles["Normal"], fontSize=9, textColor=colors.HexColor("#475569")
)


def _table_style() -> TableStyle:
    return TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), _HEADER_BG),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.4, _GRID),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]
    )


def _p(text: str) -> Paragraph:
    return Paragraph(text.replace("&", "&amp;").replace("<", "&lt;"), _CELL)


def _date(value: object) -> str:
    return str(value) if value is not None else "—"


class GanttFlowable(Flowable):
    """Draws scheduled tasks as horizontal bars on a shared date axis (vector, paginates as
    one block). Caps rows so a single page stays readable; the full set is in the tasks table."""

    def __init__(self, tasks: list[Task], max_rows: int = 26) -> None:
        super().__init__()
        scheduled = [t for t in tasks if t.start is not None and t.end is not None]
        scheduled.sort(key=lambda t: (t.start or date.min, t.id or 0))
        self.truncated = len(scheduled) > max_rows
        self.tasks = scheduled[:max_rows]
        self.label_w = 150.0
        self.row_h = 15.0
        self.header_h = 20.0
        self.width = 0.0
        self.height = 0.0

    def wrap(self, avail_width: float, avail_height: float) -> tuple[float, float]:
        self.width = avail_width
        extra = 12.0 if self.truncated else 0.0
        self.height = self.header_h + self.row_h * max(1, len(self.tasks)) + extra
        return self.width, self.height

    def draw(self) -> None:
        c = self.canv
        starts = [t.start for t in self.tasks if t.start is not None]
        ends = [t.end for t in self.tasks if t.end is not None]
        if not starts or not ends:
            c.setFont("Helvetica-Oblique", 9)
            c.setFillColor(colors.HexColor("#64748b"))
            c.drawString(0, self.height - 14, "No scheduled tasks yet — run Schedule (CPM).")
            return
        d_min, d_max = min(starts), max(ends)
        span = max(1, (d_max - d_min).days)
        chart_x = self.label_w
        chart_w = self.width - self.label_w

        # Header: date axis bounds + separator line.
        c.setFont("Helvetica-Bold", 8)
        c.setFillColor(colors.HexColor("#334155"))
        c.drawString(chart_x, self.height - 12, str(d_min))
        c.drawRightString(self.width, self.height - 12, str(d_max))
        c.setStrokeColor(_GRID)
        c.setLineWidth(0.5)
        c.line(0, self.height - self.header_h, self.width, self.height - self.header_h)

        for i, t in enumerate(self.tasks):
            assert t.start is not None and t.end is not None
            row_top = self.height - self.header_h - i * self.row_h
            bar_y = row_top - self.row_h + 3
            bar_h = self.row_h - 6
            x = chart_x + (t.start - d_min).days / span * chart_w
            w = max(2.0, (t.end - t.start).days / span * chart_w)

            c.setFont("Helvetica", 7)
            c.setFillColor(_CRITICAL if t.is_critical else colors.HexColor("#334155"))
            name = t.name if len(t.name) <= 30 else t.name[:29] + "…"
            c.drawString(2, bar_y + 1, name)

            if t.type == TaskType.milestone:
                cy = bar_y + bar_h / 2
                c.setFillColor(colors.HexColor("#7c3aed"))
                c.rect(x - 3, cy - 3, 6, 6, stroke=0, fill=1)  # marker
                continue
            fill = _CRITICAL if t.is_critical else _SUMMARY if t.type == TaskType.summary else _BAR
            c.setFillColor(fill)
            c.roundRect(x, bar_y, w, bar_h, 2, stroke=0, fill=1)
            if t.percent_complete > 0:
                done_w = w * min(1.0, t.percent_complete / 100)
                c.setFillColor(colors.HexColor("#064e3b"))
                c.roundRect(x, bar_y, done_w, bar_h, 2, stroke=0, fill=1)

        if self.truncated:
            c.setFont("Helvetica-Oblique", 7)
            c.setFillColor(colors.HexColor("#64748b"))
            c.drawString(
                2, 2, f"… first {len(self.tasks)} scheduled tasks shown; full list in the table."
            )


def _doc(buf: io.BytesIO, title: str) -> SimpleDocTemplate:
    return SimpleDocTemplate(
        buf,
        pagesize=A4,
        title=title,
        leftMargin=1.6 * cm,
        rightMargin=1.6 * cm,
        topMargin=1.6 * cm,
        bottomMargin=1.6 * cm,
    )


def _heading(title: str, subtitle: str, generated_at: object) -> list[object]:
    return [
        Paragraph(title, _styles["Title"]),
        Paragraph(subtitle, _META),
        Paragraph(f"Snapshot generated {generated_at}", _META),
        Spacer(1, 10),
    ]


def _summary_table(projects: list[ProjectSummary]) -> Table:
    rows: list[list[object]] = [
        ["Key", "Project", "Done / total", "Avg %", "End", "Risk", "Drift"]
    ]
    for s in projects:
        rows.append(
            [
                s.key,
                _p(s.name),
                f"{s.completed_tasks} / {s.total_tasks}",
                f"{s.avg_percent_complete:g}",
                _date(s.project_end),
                f"{s.risk_score} ({s.risk_level})",
                f"{s.drift_score} ({s.drift_level})",
            ]
        )
    table = Table(rows, repeatRows=1, colWidths=[40, 150, 70, 40, 65, 70, 70])
    table.setStyle(_table_style())
    return table


def project_pdf(snap: ProjectSnapshot) -> bytes:
    buf = io.BytesIO()
    doc = _doc(buf, f"{snap.project.key} — snapshot")
    s = snap.summary
    story: list[object] = _heading(
        f"{snap.project.name} ({snap.project.key})",
        snap.project.description or "Project snapshot",
        snap.generated_at,
    )

    stats = Table(
        [
            ["Tasks", "Completed", "Avg % complete", "Critical", "End", "Risk", "Drift"],
            [
                str(s.total_tasks),
                str(s.completed_tasks),
                f"{s.avg_percent_complete:g}",
                str(s.critical_tasks),
                _date(s.project_end),
                f"{s.risk_score} ({s.risk_level})",
                f"{s.drift_score} ({s.drift_level})",
            ],
        ],
        colWidths=[55, 65, 80, 50, 70, 80, 80],
    )
    stats.setStyle(_table_style())
    story += [stats, Spacer(1, 14)]

    story.append(Paragraph("Schedule (Gantt)", _styles["Heading2"]))
    story.append(GanttFlowable(snap.tasks))
    story.append(Spacer(1, 14))

    story.append(Paragraph("Tasks", _styles["Heading2"]))
    task_rows: list[list[object]] = [
        ["Name", "Type", "Start", "End", "Dur", "%", "Crit", "Status"]
    ]
    for t in snap.tasks:
        task_rows.append(
            [
                _p(t.name),
                t.type.value if isinstance(t.type, TaskType) else str(t.type),
                _date(t.start),
                _date(t.end),
                str(t.duration),
                f"{t.percent_complete:g}",
                "yes" if t.is_critical else "",
                t.status or "",
            ]
        )
    tasks_table = Table(task_rows, repeatRows=1, colWidths=[150, 45, 62, 62, 28, 28, 30, 70])
    tasks_table.setStyle(_table_style())
    story.append(tasks_table)

    if snap.milestones:
        story += [Spacer(1, 14), Paragraph("Milestones", _styles["Heading2"])]
        ms_rows: list[list[object]] = [["Milestone", "Target", "Status"]]
        for m in snap.milestones:
            ms_rows.append([_p(m.name), _date(m.target_date), m.status])
        ms_table = Table(ms_rows, repeatRows=1, colWidths=[300, 90, 85])
        ms_table.setStyle(_table_style())
        story.append(ms_table)

    if snap.decisions:
        story += [Spacer(1, 14), Paragraph("Decisions (ADRs)", _styles["Heading2"])]
        adr_rows: list[list[object]] = [["#", "Title", "Status"]]
        for a in snap.decisions:
            adr_rows.append([str(a.number), _p(a.title), a.status.value])
        adr_table = Table(adr_rows, repeatRows=1, colWidths=[35, 355, 85])
        adr_table.setStyle(_table_style())
        story.append(adr_table)

    doc.build(story)
    return buf.getvalue()


def initiative_pdf(snap: InitiativeSnapshot) -> bytes:
    buf = io.BytesIO()
    r = snap.rollup
    doc = _doc(buf, f"{r.initiative.key} — snapshot")
    on_track = "—" if r.on_track is None else ("on track" if r.on_track else "behind target")
    story: list[object] = _heading(
        f"{r.initiative.name} ({r.initiative.key})",
        r.initiative.outcome_statement or "Initiative snapshot",
        snap.generated_at,
    )
    head = ["Tasks", "Completed", "Avg %", "End", "Target", "Risk", "Drift", "Open ADRs", "Status"]
    stats = Table(
        [
            head,
            [
                str(r.total_tasks),
                str(r.completed_tasks),
                f"{r.avg_percent_complete:g}",
                _date(r.project_end),
                _date(r.initiative.target_date),
                f"{r.risk_score} ({r.risk_level})",
                f"{r.drift_score} ({r.drift_level})",
                str(r.open_decisions),
                on_track,
            ],
        ],
    )
    stats.setStyle(_table_style())
    story += [stats, Spacer(1, 14), Paragraph("Sub-projects", _styles["Heading2"])]
    story.append(_summary_table(r.projects))
    doc.build(story)
    return buf.getvalue()


def portfolio_pdf(snap: PortfolioSnapshot) -> bytes:
    buf = io.BytesIO()
    doc = _doc(buf, "Portfolio — snapshot")
    total = len(snap.projects)
    avg = round(sum(p.avg_percent_complete for p in snap.projects) / total, 1) if total else 0.0
    story: list[object] = _heading(
        "Portfolio",
        f"{total} project(s) · average completion {avg:g}%",
        snap.generated_at,
    )
    story.append(_summary_table(snap.projects))
    doc.build(story)
    return buf.getvalue()
