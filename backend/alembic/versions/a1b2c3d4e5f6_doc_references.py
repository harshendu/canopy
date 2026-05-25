"""doc references: a document graph linking PRDs / designs / tech-design / architecture docs

Revision ID: a1b2c3d4e5f6
Revises: d4e5f6a7b8c9
Create Date: 2026-05-25 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = 'a1b2c3d4e5f6'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def _drop_pg_type(name: str) -> None:
    """Drop a leftover native enum type (Postgres only; a no-op elsewhere)."""
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"DROP TYPE IF EXISTS {name}")


def upgrade() -> None:
    # CREATE TABLE auto-creates the native enum TYPEs on Postgres (unlike ADD COLUMN);
    # MySQL stores the enum inline and SQLite as a CHECK. `url` is TEXT (URLs exceed
    # VARCHAR(255)); dedup is enforced in the service layer, not by a DB unique index
    # (a UNIQUE over TEXT is not portable to MySQL).
    op.create_table(
        'docreference',
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column(
            'scope_level',
            sa.Enum('project', 'initiative', 'task', name='docscope'),
            nullable=False,
        ),
        sa.Column('scope_id', sa.Integer(), nullable=False),
        sa.Column(
            'kind',
            sa.Enum(
                'prd', 'design', 'tech_design', 'architecture',
                'release', 'qa', 'runbook', 'other',
                name='dockind',
            ),
            nullable=False,
        ),
        sa.Column('title', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('url', sa.Text(), nullable=False),
        sa.Column(
            'source',
            sa.Enum('jira_epic', 'manual', 'repo', 'drive', name='docsource'),
            nullable=False,
        ),
        sa.Column('owner_engineer_id', sa.Integer(), nullable=True),
        sa.Column('connection_id', sa.Integer(), nullable=True),
        sa.Column('external_field', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column(
            'link_health',
            sa.Enum('unchecked', 'ok', 'stale', 'broken', name='doclinkhealth'),
            nullable=False,
        ),
        sa.Column('last_checked_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['owner_engineer_id'], ['engineer.id'], ),
        sa.ForeignKeyConstraint(['connection_id'], ['connection.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_docreference_scope_id'), 'docreference', ['scope_id'], unique=False)
    op.create_index(
        op.f('ix_docreference_scope_level'), 'docreference', ['scope_level'], unique=False
    )
    op.create_index(op.f('ix_docreference_kind'), 'docreference', ['kind'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_docreference_kind'), table_name='docreference')
    op.drop_index(op.f('ix_docreference_scope_level'), table_name='docreference')
    op.drop_index(op.f('ix_docreference_scope_id'), table_name='docreference')
    op.drop_table('docreference')
    for _type in ('dockind', 'docscope', 'docsource', 'doclinkhealth'):
        _drop_pg_type(_type)
