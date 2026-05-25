"""Exports: point-in-time snapshots of a project / initiative / portfolio as portable
PDF or CSV — downloaded from the UI or saved to a connected Google Drive, so they can be
stored and viewed outside canopy. Snapshots reuse the same aggregation the live views use
(`summarize_project`, the initiative rollup, the portfolio rollup). Reads, so open to any
authenticated user.
"""

from datetime import UTC, date, datetime

from fastapi import APIRouter, HTTPException, Response, status
from sqlmodel import col, select

from app.api.deps import CurrentUser, SessionDep
from app.api.v1.initiatives import initiative_rollup
from app.api.v1.projects import portfolio, summarize_project
from app.connectors import get_connector
from app.connectors.gdrive import GoogleDriveConnector
from app.models.activity import ActivityEvent
from app.models.architecture import ArchitectureDecision, DriftEvent
from app.models.base import Provider
from app.models.integration import Connection
from app.models.project import Milestone, Project, Task
from app.models.team import Allocation, Engineer
from app.models.user import User
from app.schemas.entities import ExportToDriveRequest, ExportToDriveResult
from app.services import export_csv, export_pdf, integration_policy
from app.services.snapshot import InitiativeSnapshot, PortfolioSnapshot, ProjectSnapshot

router = APIRouter()

_FORMATS = {"pdf", "csv"}


def _validate_fmt(fmt: str) -> None:
    if fmt not in _FORMATS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="format must be 'pdf' or 'csv'"
        )


def _file_response(content: bytes, media_type: str, filename: str) -> Response:
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --- snapshot assembly ---
async def _project_snapshot(session: SessionDep, project_id: int) -> ProjectSnapshot:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    tasks = list(
        (await session.execute(select(Task).where(Task.project_id == project_id))).scalars().all()
    )
    milestones = list(
        (
            await session.execute(
                select(Milestone)
                .where(Milestone.project_id == project_id)
                .order_by(col(Milestone.target_date))
            )
        ).scalars().all()
    )
    decisions = list(
        (
            await session.execute(
                select(ArchitectureDecision)
                .where(ArchitectureDecision.project_id == project_id)
                .order_by(col(ArchitectureDecision.number))
            )
        ).scalars().all()
    )
    allocations = list(
        (
            await session.execute(select(Allocation).where(Allocation.project_id == project_id))
        ).scalars().all()
    )
    engineer_names = {
        e.id: e.name
        for e in (await session.execute(select(Engineer))).scalars().all()
        if e.id is not None
    }
    drift_events = list(
        (
            await session.execute(select(DriftEvent).where(DriftEvent.project_id == project_id))
        ).scalars().all()
    )
    activity_events = list(
        (
            await session.execute(
                select(ActivityEvent).where(ActivityEvent.project_id == project_id)
            )
        ).scalars().all()
    )
    summary = summarize_project(
        project,
        tasks=tasks,
        allocations=allocations,
        engineer_names=engineer_names,
        adrs=decisions,
        drift_events=drift_events,
        activity_events=activity_events,
        today=date.today(),
    )
    return ProjectSnapshot(
        generated_at=datetime.now(UTC),
        project=project,
        summary=summary,
        tasks=tasks,
        milestones=milestones,
        decisions=decisions,
        engineer_names=engineer_names,
    )


async def _initiative_snapshot(
    session: SessionDep, user: User, initiative_id: int
) -> InitiativeSnapshot:
    rollup = await initiative_rollup(session, user, initiative_id)
    return InitiativeSnapshot(generated_at=datetime.now(UTC), rollup=rollup)


async def _portfolio_snapshot(session: SessionDep, user: User) -> PortfolioSnapshot:
    resp = await portfolio(session, user)
    return PortfolioSnapshot(generated_at=datetime.now(UTC), projects=resp.projects)


# --- render dispatch: (content, media_type, filename) ---
def _render_project(snap: ProjectSnapshot, fmt: str) -> tuple[bytes, str, str]:
    stamp = snap.generated_at.date()
    key = snap.project.key
    if fmt == "csv":
        return export_csv.project_csv(snap), "text/csv", f"{key}-tasks-{stamp}.csv"
    return export_pdf.project_pdf(snap), "application/pdf", f"{key}-snapshot-{stamp}.pdf"


def _render_initiative(snap: InitiativeSnapshot, fmt: str) -> tuple[bytes, str, str]:
    key = snap.rollup.initiative.key
    stamp = snap.generated_at.date()
    if fmt == "csv":
        return export_csv.initiative_csv(snap), "text/csv", f"{key}-rollup-{stamp}.csv"
    return export_pdf.initiative_pdf(snap), "application/pdf", f"{key}-snapshot-{stamp}.pdf"


def _render_portfolio(snap: PortfolioSnapshot, fmt: str) -> tuple[bytes, str, str]:
    stamp = snap.generated_at.date()
    if fmt == "csv":
        return export_csv.portfolio_csv(snap), "text/csv", f"portfolio-{stamp}.csv"
    return export_pdf.portfolio_pdf(snap), "application/pdf", f"portfolio-{stamp}.pdf"


async def _upload_to_drive(
    session: SessionDep, connection_id: int, content: bytes, media_type: str, filename: str
) -> ExportToDriveResult:
    connection = await session.get(Connection, connection_id)
    if connection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")
    if connection.provider != Provider.gdrive:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Not a Google Drive connection"
        )
    if not connection.authorized:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Drive connection is not authorized"
        )
    write = await integration_policy.resolve_write(session, Provider.gdrive)
    if not write.allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=write.reason)
    connector = get_connector(connection, session)
    if not isinstance(connector, GoogleDriveConnector):  # pragma: no cover - defensive
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Not a Drive connection"
        )
    data = await connector.upload_file(name=filename, content=content, mime_type=media_type)
    return ExportToDriveResult(
        file_id=str(data.get("id", "")),
        name=str(data.get("name", filename)),
        link=data.get("webViewLink"),
    )


# --- project ---
@router.get("/projects/{project_id}/export")
async def export_project(
    session: SessionDep, _: CurrentUser, project_id: int, fmt: str = "pdf"
) -> Response:
    _validate_fmt(fmt)
    snap = await _project_snapshot(session, project_id)
    return _file_response(*_render_project(snap, fmt))


@router.post("/projects/{project_id}/export/to-drive", response_model=ExportToDriveResult)
async def export_project_to_drive(
    session: SessionDep, _: CurrentUser, project_id: int, payload: ExportToDriveRequest
) -> ExportToDriveResult:
    _validate_fmt(payload.fmt)
    snap = await _project_snapshot(session, project_id)
    content, media_type, filename = _render_project(snap, payload.fmt)
    return await _upload_to_drive(session, payload.connection_id, content, media_type, filename)


# --- initiative ---
@router.get("/initiatives/{initiative_id}/export")
async def export_initiative(
    session: SessionDep, user: CurrentUser, initiative_id: int, fmt: str = "pdf"
) -> Response:
    _validate_fmt(fmt)
    snap = await _initiative_snapshot(session, user, initiative_id)
    return _file_response(*_render_initiative(snap, fmt))


@router.post("/initiatives/{initiative_id}/export/to-drive", response_model=ExportToDriveResult)
async def export_initiative_to_drive(
    session: SessionDep, user: CurrentUser, initiative_id: int, payload: ExportToDriveRequest
) -> ExportToDriveResult:
    _validate_fmt(payload.fmt)
    snap = await _initiative_snapshot(session, user, initiative_id)
    content, media_type, filename = _render_initiative(snap, payload.fmt)
    return await _upload_to_drive(session, payload.connection_id, content, media_type, filename)


# --- portfolio ---
@router.get("/portfolio/export")
async def export_portfolio(session: SessionDep, user: CurrentUser, fmt: str = "pdf") -> Response:
    _validate_fmt(fmt)
    snap = await _portfolio_snapshot(session, user)
    return _file_response(*_render_portfolio(snap, fmt))


@router.post("/portfolio/export/to-drive", response_model=ExportToDriveResult)
async def export_portfolio_to_drive(
    session: SessionDep, user: CurrentUser, payload: ExportToDriveRequest
) -> ExportToDriveResult:
    _validate_fmt(payload.fmt)
    snap = await _portfolio_snapshot(session, user)
    content, media_type, filename = _render_portfolio(snap, payload.fmt)
    return await _upload_to_drive(session, payload.connection_id, content, media_type, filename)
