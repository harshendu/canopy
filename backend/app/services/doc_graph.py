"""The document graph: harvest, classify, and report coverage of *links* to documents.

Canopy never stores documents — it links to where they already live (a Jira epic's
fields/remote-links, Google Drive, Figma, a repo file) and makes them discoverable in
context. The pure helpers (URL extraction, mapping application, coverage) are unit-tested;
the async functions orchestrate the Jira connector + persistence.

Setup is AI-driven: `analyze_epic_doc_fields` returns a sample of epics' URL-bearing fields
so Claude can propose a field→kind mapping for the admin to confirm; `set_mapping` saves it
on the connection; `harvest` then attaches a `DocReference` to whatever canopy entity each
epic maps to (a summary task or a project, via `ExternalRef`).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import ColumnElement
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.connectors.jira import JiraConnector
from app.models.base import DocReviewStatus, DocScope, DocSource, Provider
from app.models.doc import DocLink, DocReference
from app.models.integration import Connection
from app.models.project import Project, Task
from app.services import design_docs
from app.services import mapping as ext_mapping
from app.services.doc_kinds import (
    ensure_kind,
    expected_keys,
    load_catalog,
    normalize_slug,
    resolve_kind,
)

# Mapping config is stored on the Jira connection (same JSON home as story_point_field).
_CONFIG_KEY = "doc_field_mappings"

_URL_RE = re.compile(r"https?://[^\s\"'<>)\]}]+")
# URL substrings that are chrome (avatars, icons, REST self-links), never documents.
_NOISE = (
    "avatar",
    "/secure/",
    "/rest/",
    "thumbnail",
    "/images/",
    "icon",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
)


class DocGraphError(Exception):
    """Raised for connection / configuration problems in the doc-graph flows."""


@dataclass
class HarvestResult:
    references_created: int = 0
    references_updated: int = 0
    skipped: int = 0
    epics_scanned: int = 0
    notes: list[str] = field(default_factory=list)


# --- pure helpers -----------------------------------------------------------------

def _dedup(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def is_doc_url(url: str) -> bool:
    """True if a URL looks like a real document link (not avatar/icon/REST chrome)."""
    low = url.lower()
    return url.startswith("http") and not any(n in low for n in _NOISE)


def _walk_collect_urls(node: Any, out: list[str]) -> None:
    """Collect URLs from an arbitrary value: plain strings, ADF rich text (link marks /
    inlineCard `attrs.url` / `attrs.href`), and nested lists/dicts."""
    if isinstance(node, str):
        out.extend(_URL_RE.findall(node))
    elif isinstance(node, dict):
        for key, value in node.items():
            if key in ("href", "url") and isinstance(value, str) and value.startswith("http"):
                out.append(value)
            else:
                _walk_collect_urls(value, out)
    elif isinstance(node, list):
        for item in node:
            _walk_collect_urls(item, out)


def extract_urls(value: Any) -> list[str]:
    """All distinct URLs reachable inside a Jira field value (string, ADF doc, list…)."""
    out: list[str] = []
    _walk_collect_urls(value, out)
    return _dedup([u.rstrip(".,;") for u in out])


def _coerce_kind(kind: Any) -> str:
    """Any kind is allowed (an open slug); a missing one is `other`."""
    return normalize_slug(str(kind) if kind is not None else None)


@dataclass
class HarvestedLink:
    kind: str
    url: str
    field: str  # the jira field id, "description", or "remote_link"
    title: str | None = None


def doc_links_for_epic(
    issue: dict[str, Any],
    mappings: list[dict[str, Any]],
    *,
    parse_description_links: bool,
    parse_remote_links: bool,
    remote_links: list[dict[str, Any]] | None = None,
) -> list[HarvestedLink]:
    """Apply a confirmed field→kind mapping to one epic, returning the doc links to attach.

    Explicit mappings win (they assign a real kind); the optional description/remote-link
    sweeps add anything else as `other` so nothing is silently dropped. Deduplicated by URL.
    """
    fields = issue.get("fields", {})
    out: list[HarvestedLink] = []
    seen: set[str] = set()

    def add(kind: str, url: str, source_field: str, title: str | None = None) -> None:
        clean = url.strip()
        if clean and is_doc_url(clean) and clean not in seen:
            seen.add(clean)
            out.append(HarvestedLink(kind=kind, url=clean, field=source_field, title=title))

    for entry in mappings:
        field_id = str(entry.get("jira_field", ""))
        if not field_id:
            continue
        kind = _coerce_kind(entry.get("doc_kind"))
        for url in extract_urls(fields.get(field_id)):
            add(kind, url, field_id)

    if parse_description_links:
        for url in extract_urls(fields.get("description")):
            add("other", url, "description")

    if parse_remote_links:
        for link in remote_links or []:
            add("other", str(link.get("url", "")), "remote_link", title=link.get("title"))

    return out


# --- connection config (the field mapping) ---------------------------------------

def get_mapping(connection: Connection) -> dict[str, Any]:
    """Read the doc field mapping stored on a Jira connection's config (empty if unset)."""
    cfg = connection.config.get(_CONFIG_KEY) or {}
    return {
        "mappings": list(cfg.get("mappings", [])),
        "parse_description_links": bool(cfg.get("parse_description_links", False)),
        "parse_remote_links": bool(cfg.get("parse_remote_links", True)),
    }


def _is_configured(cfg: dict[str, Any]) -> bool:
    return bool(cfg["mappings"]) or cfg["parse_description_links"] or cfg["parse_remote_links"]


async def _jira(session: AsyncSession, connection_id: int) -> tuple[Connection, JiraConnector]:
    connection = await session.get(Connection, connection_id)
    if connection is None:
        raise DocGraphError(f"Connection {connection_id} not found")
    if connection.provider != Provider.jira:
        raise DocGraphError("Not a Jira connection")
    return connection, JiraConnector(connection, session)


async def set_mapping(
    session: AsyncSession,
    connection_id: int,
    *,
    mappings: list[dict[str, Any]],
    parse_description_links: bool,
    parse_remote_links: bool,
) -> dict[str, Any]:
    connection, _ = await _jira(session, connection_id)
    normalized = [
        {
            "jira_field": str(m["jira_field"]),
            "field_name": m.get("field_name"),
            # any catalog kind — a new one joins the catalog under stage `other`
            "doc_kind": await ensure_kind(session, _coerce_kind(m.get("doc_kind"))),
        }
        for m in mappings
        if m.get("jira_field")
    ]
    connection.config = {
        **connection.config,
        _CONFIG_KEY: {
            "mappings": normalized,
            "parse_description_links": parse_description_links,
            "parse_remote_links": parse_remote_links,
        },
    }
    await session.commit()
    return get_mapping(connection)


# --- AI-driven setup: sample epics for mapping inference -------------------------

async def analyze_epic_doc_fields(
    session: AsyncSession, connection_id: int, limit: int = 5
) -> dict[str, Any]:
    """Fetch a sample of epics with all fields + remote links and surface the URL-bearing
    fields (with their human names) so Claude can propose a field→kind mapping."""
    _, connector = await _jira(session, connection_id)
    registry = await connector.list_fields()
    epics = await connector.fetch_epics(limit=limit, all_fields=True)

    samples: list[dict[str, Any]] = []
    distinct: dict[str, set[str]] = {}
    for epic in epics:
        fields = epic.get("fields", {})
        candidates: list[dict[str, Any]] = []
        for field_id, value in fields.items():
            if field_id == "description":
                continue
            urls = [u for u in extract_urls(value) if is_doc_url(u)]
            if urls:
                candidates.append(
                    {
                        "field_id": field_id,
                        "field_name": registry.get(field_id, field_id),
                        "urls": _dedup(urls),
                    }
                )
                distinct.setdefault(field_id, set()).update(urls)
        desc_urls = [u for u in extract_urls(fields.get("description")) if is_doc_url(u)]
        remote = await connector.fetch_remote_links(str(epic.get("key", "")))
        samples.append(
            {
                "key": epic.get("key"),
                "summary": fields.get("summary"),
                "field_candidates": candidates,
                "description_urls": _dedup(desc_urls),
                "remote_links": remote,
            }
        )

    distinct_fields = [
        {"field_id": fid, "field_name": registry.get(fid, fid), "urls": sorted(urls)}
        for fid, urls in distinct.items()
    ]
    return {"epics": samples, "distinct_fields": distinct_fields}


# --- harvest ----------------------------------------------------------------------

async def _upsert_doc(
    session: AsyncSession,
    *,
    scope_level: DocScope,
    scope_id: int,
    link: HarvestedLink,
    connection_id: int,
) -> bool:
    """Register one harvested link through the shared register-or-link path (one document is
    one record; a second scope gets a link). Returns True if a new record was created. A
    record homed at this same scope keeps tracking the epic's field (kind, title, source)."""
    result = await design_docs.register_core(
        session,
        info=design_docs.classify(link.url, strict=False),
        kind=link.kind,
        title=link.title,
        scope_level=scope_level,
        scope_id=scope_id,
        source=DocSource.jira_epic,
        created_by=None,
    )
    doc = result.doc
    if doc.scope_level == scope_level and doc.scope_id == scope_id:
        doc.kind = await ensure_kind(session, link.kind)
        if link.title:
            doc.title = link.title
        doc.source = DocSource.jira_epic.value
        doc.external_field = link.field
        doc.connection_id = connection_id
    return result.created


async def harvest(session: AsyncSession, connection_id: int) -> HarvestResult:
    """Harvest doc links from every synced epic on a Jira connection, attaching each to the
    canopy entity it maps to (a summary task or a project, via ExternalRef)."""
    connection, connector = await _jira(session, connection_id)
    cfg = get_mapping(connection)
    if not _is_configured(cfg):
        raise DocGraphError("No doc field mapping configured for this connection")

    epics = await connector.fetch_epics(all_fields=True)
    result = HarvestResult()
    for epic in epics:
        ext_id = str(epic.get("id"))
        task_ref = await ext_mapping.get_ref(session, Provider.jira, ext_id, "task")
        project_ref = await ext_mapping.get_ref(session, Provider.jira, ext_id, "project")
        if task_ref is not None:
            scope_level, scope_id = DocScope.task, task_ref.entity_id
        elif project_ref is not None:
            scope_level, scope_id = DocScope.project, project_ref.entity_id
        else:
            result.skipped += 1
            continue
        result.epics_scanned += 1

        remote_links = (
            await connector.fetch_remote_links(str(epic.get("key", "")))
            if cfg["parse_remote_links"]
            else []
        )
        links = doc_links_for_epic(
            epic,
            cfg["mappings"],
            parse_description_links=cfg["parse_description_links"],
            parse_remote_links=cfg["parse_remote_links"],
            remote_links=remote_links,
        )
        for link in links:
            created = await _upsert_doc(
                session,
                scope_level=scope_level,
                scope_id=scope_id,
                link=link,
                connection_id=connection_id,
            )
            if created:
                result.references_created += 1
            else:
                result.references_updated += 1

    await session.commit()
    return result


# --- coverage ---------------------------------------------------------------------

async def _refs_for_scope(
    session: AsyncSession, scope_level: DocScope, scope_id: int
) -> list[DocReference]:
    """Shared references at a scope, rolled up: a project includes its tasks; an initiative
    includes its projects and their tasks. Docs *linked* to any of those entities count as
    well as docs homed there; personal docs never do."""
    task_ids: list[int] = []
    project_ids: list[int] = []
    initiative_ids: list[int] = []

    if scope_level == DocScope.task:
        task_ids = [scope_id]
    else:
        if scope_level == DocScope.project:
            project_ids = [scope_id]
        else:  # initiative
            initiative_ids = [scope_id]
            project_rows = await session.execute(
                select(col(Project.id)).where(col(Project.initiative_id) == scope_id)
            )
            project_ids = [pid for pid in project_rows.scalars() if pid is not None]
        if project_ids:
            task_rows = await session.execute(
                select(col(Task.id)).where(col(Task.project_id).in_(project_ids))
            )
            task_ids = [tid for tid in task_rows.scalars() if tid is not None]

    clauses: list[ColumnElement[bool]] = []
    linked: set[int] = set()
    for level, ids in (
        (DocScope.initiative, initiative_ids),
        (DocScope.project, project_ids),
        (DocScope.task, task_ids),
    ):
        if not ids:
            continue
        clauses.append(
            (col(DocReference.scope_level) == level) & (col(DocReference.scope_id).in_(ids))
        )
        linked.update(await design_docs.doc_ids_linked_to(session, level.value, ids))
    if linked:
        clauses.append(col(DocReference.id).in_(sorted(linked)))
    if not clauses:
        return []
    predicate = clauses[0]
    for clause in clauses[1:]:
        predicate = predicate | clause
    rows = await session.execute(
        select(DocReference).where(predicate, col(DocReference.private_to_user_id).is_(None))
    )
    return list(rows.scalars())


# Best state first: an approved doc beats one in review beats a draft beats a plain link.
_STATE_RANK = {
    DocReviewStatus.approved.value: 0,
    DocReviewStatus.in_review.value: 1,
    DocReviewStatus.draft.value: 2,
    None: 3,  # an untracked plain link
}
_STATE_NAME = {0: "approved", 1: "in_review", 2: "draft", 3: "linked"}
_NOT_PRESENT = {DocReviewStatus.superseded.value, DocReviewStatus.archived.value}


def coverage_report(
    refs: list[DocReference],
    catalog: dict[str, Any],
    *,
    scope_level: DocScope,
    scope_id: int,
    attention_ids: set[int] | None = None,
) -> dict[str, Any]:
    """Pure: the coverage report for a set of references and the kind catalog. Superseded and
    archived docs do not count as present; expected kinds come from the catalog."""
    live = [r for r in refs if r.review_status not in _NOT_PRESENT]
    by_kind = Counter(r.kind for r in live)
    present = {r.kind for r in live}
    expected = expected_keys(catalog)
    best: dict[str, int] = {}
    for ref in live:
        rank = _STATE_RANK.get(ref.review_status, 3)
        best[ref.kind] = min(best.get(ref.kind, 9), rank)
    stages: dict[str, dict[str, int]] = {}
    for ref in live:
        info = resolve_kind(catalog, ref.kind)
        bucket = stages.setdefault(info.stage, {"total": 0, "approved": 0})
        bucket["total"] += 1
        if ref.review_status == DocReviewStatus.approved.value:
            bucket["approved"] += 1
    return {
        "scope_level": scope_level,
        "scope_id": scope_id,
        "total_references": len(live),
        "present": sorted(present),
        "missing": [k for k in expected if k not in present],
        "by_kind": dict(sorted(by_kind.items())),
        "expected": [
            {
                "kind": key,
                "label": resolve_kind(catalog, key).label,
                "stage": resolve_kind(catalog, key).stage,
                "state": _STATE_NAME[best[key]] if key in best else "missing",
            }
            for key in expected
        ],
        "by_stage": [
            {"stage": stage, "total": counts["total"], "approved": counts["approved"]}
            for stage, counts in sorted(stages.items())
        ],
        "needs_attention": len(attention_ids or set()),
    }


async def coverage(
    session: AsyncSession, scope_level: DocScope, scope_id: int
) -> dict[str, Any]:
    """A doc-coverage report for a scope: which kinds are present, which expected ones are
    missing (absence of a doc is a signal, not neutral), counts by kind and by lifecycle
    stage, and the best review state of each expected kind."""
    refs = await _refs_for_scope(session, scope_level, scope_id)
    catalog = await load_catalog(session)
    return coverage_report(refs, catalog, scope_level=scope_level, scope_id=scope_id)


# Kept for callers that need the link rows of a scope (exports, the digest).
async def links_in_scope(session: AsyncSession, doc_ids: list[int]) -> list[DocLink]:
    if not doc_ids:
        return []
    rows = await session.execute(select(DocLink).where(col(DocLink.doc_id).in_(doc_ids)))
    return list(rows.scalars().all())
