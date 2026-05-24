"""Cross-dialect DDL tweaks, registered by importing app.models (app + Alembic both do).

MySQL/MariaDB default `DATETIME` to whole-second precision, which silently drops the
microseconds the app relies on (e.g. scenario staleness compares timestamps created in the
same second). Emit `DATETIME(6)` instead so MySQL keeps the sub-second precision Postgres and
SQLite already have. No-op on other dialects.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.compiler import compiles
from sqlalchemy.types import DateTime


@compiles(DateTime, "mysql")
@compiles(DateTime, "mariadb")
def _mysql_datetime_with_microseconds(element: DateTime, compiler: Any, **kw: Any) -> str:
    return "DATETIME(6)"
