"""widen long free-text columns to TEXT (MySQL/Postgres portability)

Unbounded `str` columns compile to VARCHAR(255) on MySQL (SQLModel's AutoString default),
which truncates / errors on the prose fields (descriptions, ADR context/decision, retro and
comment bodies, mitigations, notes, …). Convert those to TEXT so they hold long content on
every dialect. SQLite already treats VARCHAR and TEXT as the same (TEXT affinity), so this is
a no-op there; Postgres and MySQL get a native ALTER (no table rebuild, so FK-referenced
tables are safe).

Revision ID: d4e5f6a7b8c9
Revises: c79dbfbe188b
Create Date: 2026-05-24 06:20:00.000000
"""
from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = 'd4e5f6a7b8c9'
down_revision = 'c79dbfbe188b'
branch_labels = None
depends_on = None

# (table, column, nullable) for every long free-text column.
_TEXT_COLUMNS = [
    ("initiative", "outcome_statement", True),
    ("initiative", "status_note", True),
    ("project", "description", True),
    ("project", "status_note", True),
    ("milestone", "description", True),
    ("task", "description", True),
    ("riskmitigation", "note", False),
    ("baseline", "note", True),
    ("blocker", "reason", False),
    ("architecturecomponent", "description", True),
    ("architecturedecision", "context", True),
    ("architecturedecision", "decision", True),
    ("architecturedecision", "consequences", True),
    ("adrcomment", "body", False),
    ("driftevent", "summary", False),
    ("driftevent", "detail", True),
    ("driftevent", "suspected_cause", True),
    ("adrfitnessfunction", "description", True),
    ("retrospective", "body", True),
    ("retrospectivecomment", "body", False),
    ("riskitem", "description", True),
    ("riskitem", "mitigation", True),
    ("riskitem", "contingency", True),
    ("draftplan", "description", True),
    ("draftplan", "source", True),
    ("drafttask", "description", True),
    ("scenario", "description", True),
    ("scenariotask", "description", True),
    ("scenariomilestone", "description", True),
    ("scenarioavailability", "note", True),
    ("engineeravailability", "note", True),
    ("activityevent", "summary", False),
]


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        return  # VARCHAR and TEXT share TEXT affinity on SQLite
    for table, column, nullable in _TEXT_COLUMNS:
        op.alter_column(
            table, column,
            type_=sa.Text(),
            existing_type=sqlmodel.sql.sqltypes.AutoString(),
            existing_nullable=nullable,
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        return
    for table, column, nullable in _TEXT_COLUMNS:
        op.alter_column(
            table, column,
            type_=sqlmodel.sql.sqltypes.AutoString(),
            existing_type=sa.Text(),
            existing_nullable=nullable,
        )
