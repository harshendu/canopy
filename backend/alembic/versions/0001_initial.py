"""initial schema (baseline created from SQLModel metadata)

Revision ID: 0001
Revises:
Create Date: 2026-05-23
"""

import app.models  # noqa: F401  -- registers all tables
from sqlmodel import SQLModel

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    SQLModel.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    SQLModel.metadata.drop_all(bind=op.get_bind())
