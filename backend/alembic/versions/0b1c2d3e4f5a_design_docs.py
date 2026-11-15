"""design docs: doc identity + review lifecycle, links, version log, kind catalog

Revision ID: 0b1c2d3e4f5a
Revises: b0c1d2e3f4a5
Create Date: 2026-11-15 09:00:00

The design-doc layer over the document graph (USER_FLOWS §V5–§V8):

- `docreference` becomes one row per *document*: `provider` + `external_id` (its identity at
  the source), `format`, personal docs (`private_to_user_id`, nullable home scope),
  `visibility` (the sharing rule), the review lifecycle (`review_status`, `review_version`,
  `current_version`, `approved_*`), `summary`, `supersedes_id`, `created_by_user_id`;
- `kind` and `source` stop being native enums (VARCHAR): kinds are an open catalog and
  `source` gains `agent` / `claude_sync` — the provider-column precedent (`f8a9b0c1d2e3`);
- `doclink` (doc ↔ any entity, with a relation and a pinned version), `docrevision` (the
  version log) and `dockinddef` (the kind catalog, seeded with the built-ins);
- `app_user.doc_snapshot_store` (repo | drive): where a person freezes approved docs.

Data (portable Core statements, no app imports — the classifier below is a frozen copy of
`app/services/doc_urls.py` as of this revision):
1. classify every existing link (provider, external id, format; Claude links canonicalized);
2. merge rows that point at the same document into one doc with links (survivor = the
   broadest home, initiative > project > task, lowest id on a tie); proposal items that named
   a removed row are re-pointed at the survivor;
3. turn each `architecturedecision.rfc_url` / `spec.source_url` into a doc + a basis link
   (the columns stay, read-only aliases for one release).

Running the data steps twice changes nothing. Downgrade is best effort: every scope link
becomes its own row again, personal docs without a home are dropped, and kinds / sources the
old enums cannot hold become `other` / `manual`.
"""

import logging
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit, urlunsplit

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision = "0b1c2d3e4f5a"
down_revision = "b0c1d2e3f4a5"
branch_labels = None
depends_on = None

_OLD_KINDS = ("prd", "design", "tech_design", "architecture", "release", "qa", "runbook", "other")
_OLD_SOURCES = ("jira_epic", "manual", "repo", "drive")
_SCOPES = ("project", "initiative", "task")

# (key, label, stage, expected) — the built-in kind catalog.
_BUILTIN_KINDS = (
    ("research", "Research", "frame", False),
    ("prd", "PRD", "define", True),
    ("design", "Design", "define", True),
    ("tech_design", "Tech design", "design", True),
    ("architecture", "Architecture", "design", True),
    ("rfc", "RFC", "decide", False),
    ("qa", "QA plan", "build", False),
    ("release", "Release notes", "release", False),
    ("runbook", "Runbook", "release", False),
    ("other", "Other", "other", False),
)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)  # naive UTC, like `models/base.py:utcnow`


def _scope_enum() -> sa.Enum:
    return sa.Enum(*_SCOPES, name="docscope")


# --- schema -----------------------------------------------------------------------------


def _enum_to_varchar(table: str, column: str, *, name: str, values: tuple[str, ...],
                     length: int) -> None:
    dialect = op.get_bind().dialect.name
    old = sa.Enum(*values, name=name)
    if dialect == "postgresql":
        op.alter_column(
            table, column, existing_type=old, type_=sa.String(length=length),
            existing_nullable=False, postgresql_using=f"{column}::text",
        )
        op.execute(f"DROP TYPE IF EXISTS {name}")
    elif dialect in ("mysql", "mariadb"):
        op.alter_column(
            table, column, existing_type=old, type_=sa.String(length=length),
            existing_nullable=False,
        )
    # SQLite: the column is already a VARCHAR (no CHECK); lengths are not enforced.


def _varchar_to_enum(table: str, column: str, *, name: str, values: tuple[str, ...],
                     length: int) -> None:
    dialect = op.get_bind().dialect.name
    new = sa.Enum(*values, name=name)
    if dialect == "postgresql":
        new.create(op.get_bind(), checkfirst=True)
        op.alter_column(
            table, column, existing_type=sa.String(length=length), type_=new,
            existing_nullable=False, postgresql_using=f"{column}::{name}",
        )
    elif dialect in ("mysql", "mariadb"):
        op.alter_column(
            table, column, existing_type=sa.String(length=length), type_=new,
            existing_nullable=False,
        )


def upgrade() -> None:
    _enum_to_varchar("docreference", "kind", name="dockind", values=_OLD_KINDS, length=48)
    _enum_to_varchar("docreference", "source", name="docsource", values=_OLD_SOURCES, length=32)

    with op.batch_alter_table("docreference") as batch:
        batch.alter_column("scope_level", existing_type=_scope_enum(), nullable=True)
        batch.alter_column("scope_id", existing_type=sa.Integer(), nullable=True)
        batch.add_column(sa.Column(
            "provider", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False,
            server_default="web",
        ))
        batch.add_column(sa.Column(
            "external_id", sqlmodel.sql.sqltypes.AutoString(length=128), nullable=True
        ))
        batch.add_column(sa.Column(
            "format", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False,
            server_default="other",
        ))
        batch.add_column(sa.Column("private_to_user_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column(
            "visibility", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False,
            server_default="unknown",
        ))
        batch.add_column(sa.Column(
            "review_status", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=True
        ))
        batch.add_column(sa.Column(
            "review_version", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True
        ))
        batch.add_column(sa.Column(
            "current_version", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True
        ))
        batch.add_column(sa.Column(
            "approved_version", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True
        ))
        batch.add_column(sa.Column("approved_by_user_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("approved_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("summary", sa.Text(), nullable=True))
        batch.add_column(sa.Column("supersedes_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("created_by_user_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_docreference_private_to_user_id_app_user", "app_user",
            ["private_to_user_id"], ["id"],
        )
        batch.create_foreign_key(
            "fk_docreference_approved_by_user_id_app_user", "app_user",
            ["approved_by_user_id"], ["id"],
        )
        batch.create_foreign_key(
            "fk_docreference_supersedes_id_docreference", "docreference",
            ["supersedes_id"], ["id"],
        )
        batch.create_foreign_key(
            "fk_docreference_created_by_user_id_app_user", "app_user",
            ["created_by_user_id"], ["id"],
        )
        batch.create_index(op.f("ix_docreference_provider"), ["provider"])
        batch.create_index(op.f("ix_docreference_external_id"), ["external_id"])
        batch.create_index(op.f("ix_docreference_private_to_user_id"), ["private_to_user_id"])
        batch.create_index(op.f("ix_docreference_review_status"), ["review_status"])

    with op.batch_alter_table("app_user") as batch:
        batch.add_column(sa.Column(
            "doc_snapshot_store", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=True
        ))

    op.create_table(
        "doclink",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("doc_id", sa.Integer(), nullable=False),
        sa.Column("entity_type", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("relation", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column("pinned_version", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True),
        sa.Column("pinned_at", sa.DateTime(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["doc_id"], ["docreference.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["app_user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("doc_id", "entity_type", "entity_id", name="uq_doclink_target"),
    )
    op.create_index(op.f("ix_doclink_doc_id"), "doclink", ["doc_id"])
    op.create_index(op.f("ix_doclink_entity_type"), "doclink", ["entity_type"])
    op.create_index(op.f("ix_doclink_entity_id"), "doclink", ["entity_id"])

    op.create_table(
        "docrevision",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("doc_id", sa.Integer(), nullable=False),
        sa.Column("version", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column("content_hash", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True),
        sa.Column("change_summary", sa.Text(), nullable=True),
        sa.Column("snapshot_url", sa.Text(), nullable=True),
        sa.Column("recorded_by_user_id", sa.Integer(), nullable=True),
        sa.Column("source", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.ForeignKeyConstraint(["doc_id"], ["docreference.id"]),
        sa.ForeignKeyConstraint(["recorded_by_user_id"], ["app_user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("doc_id", "version", name="uq_docrevision_version"),
    )
    op.create_index(op.f("ix_docrevision_doc_id"), "docrevision", ["doc_id"])

    op.create_table(
        "dockinddef",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sqlmodel.sql.sqltypes.AutoString(length=48), nullable=False),
        sa.Column("label", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("stage", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column("expected", sa.Boolean(), nullable=False),
        sa.Column("builtin", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_dockinddef_key"), "dockinddef", ["key"], unique=True)

    _seed_kinds()
    _classify_existing()
    _merge_duplicates()
    _link_decisions_and_specs()


# --- frozen URL classifier (a copy of app/services/doc_urls.py at this revision) ------------

_CLAUDE_HOSTS = {"claude.ai", "www.claude.ai", "preview.claude.ai"}
_UUID_RE = re.compile(
    r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$"
)
_SHORT_ID_RE = re.compile(r"^[A-Za-z0-9]{10,64}$")
_GOOGLE = {"document": "document", "spreadsheets": "sheet", "presentation": "deck",
           "drawings": "diagram", "forms": "other"}
_FIGMA = {"file": "canvas", "design": "canvas", "proto": "prototype", "board": "canvas",
          "slides": "deck"}
_EXT = {"md": "document", "markdown": "document", "rst": "document", "txt": "document",
        "adoc": "document", "pdf": "document", "html": "page", "htm": "page", "png": "image",
        "jpg": "image", "jpeg": "image", "gif": "image", "svg": "diagram", "drawio": "diagram",
        "mmd": "diagram", "puml": "diagram", "csv": "sheet"}


def _clip_id(value: str | None) -> str | None:
    return value if value and len(value) <= 128 else None


def _ext(path: str) -> str | None:
    name = path.rsplit("/", 1)[-1]
    return _EXT.get(name.rsplit(".", 1)[-1].lower()) if "." in name else None


def classify(raw: str) -> tuple[str, str | None, str | None, str]:
    """(provider, external_id, format_hint, canonical_url) — lenient (never raises)."""
    text = (raw or "").strip()
    try:
        parts = urlsplit(text)
    except ValueError:
        return ("web", None, None, text)
    host = (parts.hostname or "").lower()
    if not host or parts.scheme.lower() not in ("http", "https"):
        return ("web", None, None, text)
    anchor = parts.fragment or ""
    seg = [s for s in parts.path.split("/") if s]
    if host in _CLAUDE_HOSTS:
        prefix: list[str] | None = None
        slug = ""
        if len(seg) >= 2 and seg[0] == "artifact":
            prefix, slug = ["artifact"], seg[1]
        elif len(seg) >= 3 and seg[0] == "code" and seg[1] == "artifact":
            prefix, slug = ["code", "artifact"], seg[2]
        elif len(seg) >= 3 and seg[0] == "public" and seg[1] == "artifacts":
            prefix, slug = ["public", "artifacts"], seg[2]
        if prefix is not None:
            match = _UUID_RE.search(slug)
            if match:
                art = match.group(1).lower()
            else:
                tail = slug.rsplit("-", 1)[-1]
                art = tail if _SHORT_ID_RE.match(tail) else ""
            if art:
                url = urlunsplit(("https", host, "/" + "/".join([*prefix, art]), "", anchor))
                return ("claude", _clip_id(art), None, url)
        return ("claude", None, None, text)
    if host == "docs.google.com" and len(seg) >= 3 and seg[1] == "d":
        return ("gdrive", _clip_id(seg[2]), _GOOGLE.get(seg[0], "document"), text)
    if host == "drive.google.com":
        file_id = None
        if len(seg) >= 3 and seg[0] == "file" and seg[1] == "d":
            file_id = seg[2]
        elif seg[:1] in (["open"], ["uc"]):
            file_id = (parse_qs(parts.query).get("id") or [None])[0]
        elif len(seg) >= 3 and seg[0] == "drive" and seg[1] == "folders":
            file_id = seg[2]
        return ("gdrive", _clip_id(file_id), None, text)
    if host in ("github.com", "www.github.com"):
        if len(seg) >= 5 and seg[2] in ("blob", "raw"):
            path = "/".join(seg[4:])
            return ("github", _clip_id(f"{seg[0]}/{seg[1]}/{path}"), _ext(path), text)
        return ("github", None, None, text)
    if host in ("figma.com", "www.figma.com"):
        if len(seg) >= 2 and seg[0] in _FIGMA:
            return ("figma", _clip_id(seg[1]), _FIGMA[seg[0]], text)
        return ("figma", None, "canvas", text)
    if host.endswith(".atlassian.net"):
        if seg[:1] == ["wiki"]:
            page = None
            if "pages" in seg:
                at = seg.index("pages")
                if at + 1 < len(seg) and seg[at + 1].isdigit():
                    page = f"{host}/{seg[at + 1]}"
            return ("confluence", _clip_id(page), "document", text)
        if len(seg) >= 2 and seg[0] == "browse":
            return ("jira", _clip_id(f"{host}/{seg[1].upper()}"), None, text)
    return ("web", None, _ext(parts.path), text)


def _identity(provider: str, external_id: str | None, url: str) -> tuple[str, str]:
    return (provider, external_id) if external_id else (provider, url.split("#", 1)[0])


# --- data steps -------------------------------------------------------------------------

_doc = sa.table(
    "docreference",
    sa.column("id", sa.Integer),
    sa.column("created_at", sa.DateTime),
    sa.column("updated_at", sa.DateTime),
    # native enums on Postgres: bind them with their enum type (asyncpg refuses a VARCHAR)
    sa.column("scope_level", sa.Enum(*_SCOPES, name="docscope")),
    sa.column("scope_id", sa.Integer),
    sa.column("kind", sa.String),
    sa.column("title", sa.String),
    sa.column("url", sa.Text),
    sa.column("source", sa.String),
    sa.column("owner_engineer_id", sa.Integer),
    sa.column("link_health", sa.Enum("unchecked", "ok", "stale", "broken", name="doclinkhealth")),
    sa.column("provider", sa.String),
    sa.column("external_id", sa.String),
    sa.column("format", sa.String),
    sa.column("visibility", sa.String),
    sa.column("private_to_user_id", sa.Integer),
    sa.column("review_status", sa.String),
)
_link = sa.table(
    "doclink",
    sa.column("id", sa.Integer),
    sa.column("created_at", sa.DateTime),
    sa.column("updated_at", sa.DateTime),
    sa.column("doc_id", sa.Integer),
    sa.column("entity_type", sa.String),
    sa.column("entity_id", sa.Integer),
    sa.column("relation", sa.String),
    sa.column("pinned_version", sa.String),
)
_kind = sa.table(
    "dockinddef",
    sa.column("created_at", sa.DateTime),
    sa.column("updated_at", sa.DateTime),
    sa.column("key", sa.String),
    sa.column("label", sa.String),
    sa.column("stage", sa.String),
    sa.column("expected", sa.Boolean),
    sa.column("builtin", sa.Boolean),
    sa.column("sort_order", sa.Integer),
)
_item = sa.table(
    "proposalitem",
    sa.column("id", sa.Integer),
    sa.column("entity_type", sa.Enum(
        "task", "dependency", "milestone", "blocker", "risk", "outcome", "decision",
        "doc_reference", name="proposalentity",
    )),
    sa.column("entity_id", sa.Integer),
    sa.column("applied_entity_id", sa.Integer),
)


def _seed_kinds() -> None:
    bind = op.get_bind()
    present = {row[0] for row in bind.execute(sa.select(_kind.c.key))}
    now = _now()
    rows = [
        {"created_at": now, "updated_at": now, "key": key, "label": label, "stage": stage,
         "expected": expected, "builtin": True, "sort_order": i * 10}
        for i, (key, label, stage, expected) in enumerate(_BUILTIN_KINDS)
        if key not in present
    ]
    if rows:
        bind.execute(_kind.insert(), rows)


def _classify_existing() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.select(_doc.c.id, _doc.c.url, _doc.c.provider, _doc.c.external_id))
    for doc_id, url, provider, external_id in rows.fetchall():
        if external_id is not None or (provider not in (None, "web")):
            continue  # already classified (a second run)
        prov, ext, fmt, canonical = classify(url)
        values: dict[str, Any] = {"provider": prov, "external_id": ext}
        if fmt:
            values["format"] = fmt
        if canonical != url:
            values["url"] = canonical
        if prov != "web" or ext or fmt or canonical != url:
            bind.execute(_doc.update().where(_doc.c.id == doc_id).values(**values))


_BREADTH = {"initiative": 0, "project": 1, "task": 2}


def _merge_duplicates() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.select(
        _doc.c.id, _doc.c.scope_level, _doc.c.scope_id, _doc.c.kind, _doc.c.title, _doc.c.url,
        _doc.c.owner_engineer_id, _doc.c.provider, _doc.c.external_id,
        _doc.c.private_to_user_id,
    )).fetchall()
    groups: dict[tuple[str, str], list[Any]] = {}
    for row in rows:
        if row.private_to_user_id is not None:
            continue
        groups.setdefault(_identity(row.provider or "web", row.external_id, row.url), []).append(
            row
        )
    now = _now()
    for members in groups.values():
        if len(members) < 2:
            continue
        members.sort(key=lambda r: (_BREADTH.get(str(r.scope_level), 3), r.id))
        survivor, losers = members[0], members[1:]
        fill: dict[str, Any] = {}
        if not survivor.title:
            fill["title"] = next((m.title for m in losers if m.title), None)
        if survivor.owner_engineer_id is None:
            fill["owner_engineer_id"] = next(
                (m.owner_engineer_id for m in losers if m.owner_engineer_id is not None), None
            )
        if survivor.kind == "other":
            fill["kind"] = next((m.kind for m in losers if m.kind != "other"), "other")
        kinds = {m.kind for m in members if m.kind != "other"}
        if len(kinds) > 1:
            logging.getLogger("alembic.runtime.migration").warning(
                f"design docs: merged rows {[m.id for m in members]} disagree on kind "
                f"{sorted(kinds)}; kept '{fill.get('kind', survivor.kind)}'"
            )
        fill = {k: v for k, v in fill.items() if v is not None}
        if fill:
            bind.execute(_doc.update().where(_doc.c.id == survivor.id).values(**fill))
        have = {
            (r.entity_type, r.entity_id)
            for r in bind.execute(
                sa.select(_link.c.entity_type, _link.c.entity_id).where(
                    _link.c.doc_id == survivor.id
                )
            )
        }
        for loser in losers:
            target = (str(loser.scope_level), loser.scope_id)
            same_home = (str(survivor.scope_level), survivor.scope_id) == target
            if not same_home and target not in have and loser.scope_id is not None:
                bind.execute(_link.insert().values(
                    created_at=now, updated_at=now, doc_id=survivor.id,
                    entity_type=target[0], entity_id=target[1], relation="reference",
                    pinned_version=None,
                ))
                have.add(target)
            bind.execute(_link.update().where(_link.c.doc_id == loser.id).values(
                doc_id=survivor.id
            ))
            bind.execute(_item.update().where(
                _item.c.entity_type == "doc_reference", _item.c.applied_entity_id == loser.id
            ).values(applied_entity_id=survivor.id))
            bind.execute(_item.update().where(
                _item.c.entity_type == "doc_reference", _item.c.entity_id == loser.id
            ).values(entity_id=survivor.id))
            bind.execute(_doc.delete().where(_doc.c.id == loser.id))


def _find_or_create_doc(bind: Any, url: str, *, project_id: int, kind: str, title: str) -> int:
    prov, ext, fmt, canonical = classify(url)
    if ext:
        found = bind.execute(sa.select(_doc.c.id).where(
            _doc.c.provider == prov, _doc.c.external_id == ext,
            _doc.c.private_to_user_id.is_(None),
        ).order_by(_doc.c.id)).first()
    else:
        found = bind.execute(sa.select(_doc.c.id).where(
            _doc.c.url == canonical, _doc.c.private_to_user_id.is_(None),
        ).order_by(_doc.c.id)).first()
    if found is not None:
        return int(found[0])
    now = _now()
    result = bind.execute(_doc.insert().values(
        created_at=now, updated_at=now, scope_level="project", scope_id=project_id, kind=kind,
        title=title[:255], url=canonical, source="manual", link_health="unchecked",
        provider=prov, external_id=ext, format=fmt or "other", visibility="unknown",
    ))
    pk = result.inserted_primary_key
    if pk and pk[0] is not None:
        return int(pk[0])
    again = bind.execute(sa.select(sa.func.max(_doc.c.id))).scalar()
    return int(again)


def _ensure_link(bind: Any, doc_id: int, entity_type: str, entity_id: int) -> None:
    exists = bind.execute(sa.select(_link.c.id).where(
        _link.c.doc_id == doc_id, _link.c.entity_type == entity_type,
        _link.c.entity_id == entity_id,
    )).first()
    if exists is None:
        now = _now()
        bind.execute(_link.insert().values(
            created_at=now, updated_at=now, doc_id=doc_id, entity_type=entity_type,
            entity_id=entity_id, relation="basis", pinned_version=None,
        ))


def _link_decisions_and_specs() -> None:
    bind = op.get_bind()
    adr = sa.table(
        "architecturedecision", sa.column("id", sa.Integer), sa.column("project_id", sa.Integer),
        sa.column("number", sa.Integer), sa.column("title", sa.String),
        sa.column("rfc_url", sa.String),
    )
    spec = sa.table(
        "spec", sa.column("id", sa.Integer), sa.column("project_id", sa.Integer),
        sa.column("title", sa.String), sa.column("source_url", sa.Text),
    )
    for row in bind.execute(sa.select(adr).where(adr.c.rfc_url.is_not(None))).fetchall():
        url = (row.rfc_url or "").strip()
        if not url:
            continue
        doc_id = _find_or_create_doc(
            bind, url, project_id=row.project_id, kind="rfc",
            title=f"RFC for ADR-{row.number:04d}: {row.title}",
        )
        _ensure_link(bind, doc_id, "decision", row.id)
    for row in bind.execute(sa.select(spec).where(spec.c.source_url.is_not(None))).fetchall():
        url = (row.source_url or "").strip()
        if not url:
            continue
        doc_id = _find_or_create_doc(
            bind, url, project_id=row.project_id, kind="prd",
            title=f"Source of spec: {row.title}",
        )
        _ensure_link(bind, doc_id, "spec", row.id)


# --- downgrade --------------------------------------------------------------------------


def _split_links_back() -> None:
    """Best effort: each scope link becomes its own row; personal docs without a home and
    kinds / sources the old enums cannot hold are dropped / mapped."""
    bind = op.get_bind()
    now = _now()
    docs = {
        r.id: r for r in bind.execute(sa.select(
            _doc.c.id, _doc.c.kind, _doc.c.title, _doc.c.url, _doc.c.source,
            _doc.c.owner_engineer_id, _doc.c.scope_level, _doc.c.scope_id,
        )).fetchall()
    }
    for link in bind.execute(sa.select(_link).where(
        _link.c.entity_type.in_(_SCOPES)
    )).fetchall():
        doc = docs.get(link.doc_id)
        if doc is None or doc.scope_level is None:
            continue
        if (str(doc.scope_level), doc.scope_id) == (link.entity_type, link.entity_id):
            continue
        bind.execute(_doc.insert().values(
            created_at=now, updated_at=now, scope_level=link.entity_type,
            scope_id=link.entity_id, kind=doc.kind, title=doc.title, url=doc.url,
            source=doc.source, owner_engineer_id=doc.owner_engineer_id,
            link_health="unchecked", provider="web", format="other", visibility="unknown",
        ))
    bind.execute(_doc.update().where(_doc.c.kind.not_in(_OLD_KINDS)).values(kind="other"))
    bind.execute(_doc.update().where(_doc.c.source.not_in(_OLD_SOURCES)).values(source="manual"))
    bind.execute(_link.delete())
    revision_t = sa.table("docrevision", sa.column("id", sa.Integer))
    bind.execute(revision_t.delete())
    bind.execute(sa.text("UPDATE docreference SET supersedes_id = NULL"))
    # personal docs never become shared on the way down: drop them, homed or not
    bind.execute(_doc.delete().where(
        sa.or_(_doc.c.scope_level.is_(None), _doc.c.private_to_user_id.is_not(None))
    ))


def downgrade() -> None:
    _split_links_back()
    op.drop_index(op.f("ix_dockinddef_key"), table_name="dockinddef")
    op.drop_table("dockinddef")
    op.drop_index(op.f("ix_docrevision_doc_id"), table_name="docrevision")
    op.drop_table("docrevision")
    op.drop_index(op.f("ix_doclink_entity_id"), table_name="doclink")
    op.drop_index(op.f("ix_doclink_entity_type"), table_name="doclink")
    op.drop_index(op.f("ix_doclink_doc_id"), table_name="doclink")
    op.drop_table("doclink")

    with op.batch_alter_table("app_user") as batch:
        batch.drop_column("doc_snapshot_store")

    with op.batch_alter_table("docreference") as batch:
        # MySQL refuses to drop an index a foreign key still uses: constraints first.
        batch.drop_constraint("fk_docreference_created_by_user_id_app_user", type_="foreignkey")
        batch.drop_constraint("fk_docreference_supersedes_id_docreference", type_="foreignkey")
        batch.drop_constraint("fk_docreference_approved_by_user_id_app_user", type_="foreignkey")
        batch.drop_constraint("fk_docreference_private_to_user_id_app_user", type_="foreignkey")
        batch.drop_index(op.f("ix_docreference_review_status"))
        batch.drop_index(op.f("ix_docreference_private_to_user_id"))
        batch.drop_index(op.f("ix_docreference_external_id"))
        batch.drop_index(op.f("ix_docreference_provider"))
        for column in (
            "created_by_user_id", "supersedes_id", "summary", "approved_at",
            "approved_by_user_id", "approved_version", "current_version", "review_version",
            "review_status", "visibility", "private_to_user_id", "format", "external_id",
            "provider",
        ):
            batch.drop_column(column)
        batch.alter_column("scope_id", existing_type=sa.Integer(), nullable=False)
        batch.alter_column("scope_level", existing_type=_scope_enum(), nullable=False)

    _varchar_to_enum("docreference", "source", name="docsource", values=_OLD_SOURCES, length=32)
    _varchar_to_enum("docreference", "kind", name="dockind", values=_OLD_KINDS, length=48)
