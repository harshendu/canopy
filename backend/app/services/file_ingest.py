"""File-drop ingest (Phase 4): parse an uploaded/dropped JSON or CSV export into normalized
ingest rows, then reuse the Phase-3 ingest service to upsert them idempotently. This is just a
different *transport* for the same ingest — the file is the alternative to a Claude MCP push.

Entity type is inferred from the connection's provider: Jira → issues, GitHub → pull requests.
Invalid rows are collected as errors and skipped (a bad row never aborts the whole file).
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import Provider
from app.models.integration import Connection
from app.schemas.entities import (
    FileIngestResult,
    IngestIssue,
    IngestPullRequest,
)
from app.services import ingest


class FileIngestError(ValueError):
    """The file couldn't be ingested at all (unsupported provider/format, unparseable bytes)."""


def _rows_from_bytes(filename: str, data: bytes) -> list[dict[str, Any]]:
    """Decode a JSON array or CSV file into a list of raw row dicts. Blank CSV cells → None."""
    name = filename.lower()
    text = data.decode("utf-8-sig")  # tolerate a BOM from spreadsheet exports
    if name.endswith(".json"):
        try:
            parsed = json.loads(text or "[]")
        except json.JSONDecodeError as exc:
            raise FileIngestError(f"invalid JSON: {exc}") from exc
        if not isinstance(parsed, list):
            raise FileIngestError("JSON file must be an array of objects")
        return [dict(row) for row in parsed]
    if name.endswith(".csv"):
        reader = csv.DictReader(io.StringIO(text))
        return [{k: (v if v != "" else None) for k, v in row.items()} for row in reader]
    raise FileIngestError("unsupported file type — use .json or .csv")


def _validate_rows(
    rows: list[dict[str, Any]], model: type[BaseModel]
) -> tuple[list[Any], list[str]]:
    parsed: list[Any] = []
    errors: list[str] = []
    for index, row in enumerate(rows):
        try:
            parsed.append(model.model_validate(row))
        except ValidationError as exc:
            errors.append(f"row {index}: {exc.errors()[0]['msg']}")
    return parsed, errors


async def ingest_file(
    session: AsyncSession, connection: Connection, filename: str, data: bytes
) -> FileIngestResult:
    """Parse `data` (by the connection's provider) and ingest the valid rows idempotently."""
    rows = _rows_from_bytes(filename, data)

    if connection.provider == Provider.jira:
        issues, errors = _validate_rows(rows, IngestIssue)
        result = await ingest.ingest_issues(session, connection, issues)
    elif connection.provider == Provider.github:
        prs, errors = _validate_rows(rows, IngestPullRequest)
        result = await ingest.ingest_pull_requests(session, connection, prs)
    else:
        raise FileIngestError(f"file ingest is not supported for {connection.provider.value}")

    return FileIngestResult(
        provider=result.provider,
        created=result.created,
        updated=result.updated,
        skipped=result.skipped,
        parsed=len(rows) - len(errors),
        errors=errors,
    )
