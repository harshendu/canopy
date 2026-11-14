"""The document-kind catalog: kinds are data, not schema (USER_FLOWS §V5).

A doc's `kind` is an open slug. The workspace catalog (`DocKindDef`) gives each kind a label,
a delivery-lifecycle **stage** and an **expected** flag; coverage and the lifecycle views read
the stage and the flag, never the kind's name — the way flow metrics read status categories,
never status names. Registering an unknown kind adds it under stage `other`; a planner then
labels and stages it, and an admin can merge one kind into another.

The pure helpers (slug normalization, the built-in set, stage lookups) are unit-tested; the
async functions read and write the catalog.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.models.base import DocKind, DocStage, utcnow
from app.models.doc import DocKindDef, DocReference

KIND_MAX = 48
FORMAT_MAX = 32
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def normalize_slug(raw: str | None, *, max_length: int = KIND_MAX, default: str = "other") -> str:
    """`"Threat Model"` → `threat_model`, `"tech-design"` → `tech_design`; empty → `default`."""
    slug = _SLUG_RE.sub("_", (raw or "").strip().lower()).strip("_")
    slug = slug[:max_length].rstrip("_")
    return slug or default


def humanize(slug: str) -> str:
    """A default label for a new kind: `threat_model` → `Threat model`."""
    words = slug.replace("_", " ").strip()
    return words[:1].upper() + words[1:] if words else slug


@dataclass(frozen=True)
class BuiltinKind:
    key: str
    label: str
    stage: DocStage
    expected: bool


# The starting catalog. The four expected kinds are the ones coverage has always flagged.
BUILTIN_KINDS: tuple[BuiltinKind, ...] = (
    BuiltinKind(DocKind.research, "Research", DocStage.frame, False),
    BuiltinKind(DocKind.prd, "PRD", DocStage.define, True),
    BuiltinKind(DocKind.design, "Design", DocStage.define, True),
    BuiltinKind(DocKind.tech_design, "Tech design", DocStage.design, True),
    BuiltinKind(DocKind.architecture, "Architecture", DocStage.design, True),
    BuiltinKind(DocKind.rfc, "RFC", DocStage.decide, False),
    BuiltinKind(DocKind.qa, "QA plan", DocStage.build, False),
    BuiltinKind(DocKind.release, "Release notes", DocStage.release, False),
    BuiltinKind(DocKind.runbook, "Runbook", DocStage.release, False),
    BuiltinKind(DocKind.other, "Other", DocStage.other, False),
)
BUILTIN_KEYS = frozenset(k.key for k in BUILTIN_KINDS)


@dataclass(frozen=True)
class KindInfo:
    """A resolved catalog entry (or the fallback for a kind the catalog has not seen)."""

    key: str
    label: str
    stage: str
    expected: bool


def fallback_info(key: str) -> KindInfo:
    for builtin in BUILTIN_KINDS:
        if builtin.key == key:
            return KindInfo(key, builtin.label, builtin.stage.value, builtin.expected)
    return KindInfo(key, humanize(key), DocStage.other.value, False)


def resolve_kind(catalog: dict[str, KindInfo], key: str) -> KindInfo:
    """The catalog entry for `key`, or its built-in/fallback definition."""
    return catalog.get(key) or fallback_info(key)


def expected_keys(catalog: dict[str, KindInfo]) -> list[str]:
    """The kinds whose absence the coverage report flags, in catalog order."""
    return [k.key for k in catalog.values() if k.expected]


# --- DB side -----------------------------------------------------------------------


def _info(row: DocKindDef) -> KindInfo:
    return KindInfo(row.key, row.label, row.stage, row.expected)


async def ensure_builtins(session: AsyncSession) -> None:
    """Insert any missing built-in kinds (a fresh test database, a demo reseed). Idempotent;
    the migration seeds them on real databases."""
    present = set((await session.execute(select(DocKindDef.key))).scalars().all())
    for order, builtin in enumerate(BUILTIN_KINDS):
        if builtin.key in present:
            continue
        session.add(
            DocKindDef(
                key=builtin.key,
                label=builtin.label,
                stage=builtin.stage.value,
                expected=builtin.expected,
                builtin=True,
                sort_order=order * 10,
            )
        )
    await session.flush()


async def catalog_rows(session: AsyncSession) -> list[DocKindDef]:
    return list(
        (
            await session.execute(
                select(DocKindDef).order_by(col(DocKindDef.sort_order), col(DocKindDef.key))
            )
        ).scalars().all()
    )


async def load_catalog(session: AsyncSession) -> dict[str, KindInfo]:
    """The whole catalog, keyed by kind, in presentation order (built-ins fill any gaps)."""
    rows = (
        await session.execute(
            select(DocKindDef).order_by(col(DocKindDef.sort_order), col(DocKindDef.key))
        )
    ).scalars().all()
    catalog: dict[str, KindInfo] = {r.key: _info(r) for r in rows}
    for builtin in BUILTIN_KINDS:
        catalog.setdefault(builtin.key, fallback_info(builtin.key))
    return catalog


async def ensure_kind(session: AsyncSession, raw: str | None) -> str:
    """Normalize a kind and make sure the catalog knows it (an unknown kind is added under
    stage `other`, labelled from its slug). Returns the normalized key."""
    key = normalize_slug(raw)
    existing = (
        await session.execute(select(DocKindDef).where(DocKindDef.key == key))
    ).scalar_one_or_none()
    if existing is not None:
        return key
    builtin = next((b for b in BUILTIN_KINDS if b.key == key), None)
    max_order = max(
        (r for r in (await session.execute(select(DocKindDef.sort_order))).scalars().all()),
        default=0,
    )
    session.add(
        DocKindDef(
            key=key,
            label=builtin.label if builtin else humanize(key),
            stage=(builtin.stage if builtin else DocStage.other).value,
            expected=builtin.expected if builtin else False,
            builtin=builtin is not None,
            sort_order=max_order + 10,
        )
    )
    await session.flush()
    return key


async def usage_counts(session: AsyncSession) -> dict[str, int]:
    rows = (await session.execute(select(DocReference.kind))).scalars().all()
    counts: dict[str, int] = {}
    for kind in rows:
        counts[kind] = counts.get(kind, 0) + 1
    return counts


async def update_kind(
    session: AsyncSession,
    key: str,
    *,
    label: str | None = None,
    stage: DocStage | None = None,
    expected: bool | None = None,
    sort_order: int | None = None,
) -> DocKindDef:
    """Relabel / re-stage a kind (creating its catalog row on first edit)."""
    norm = await ensure_kind(session, key)
    row = (
        await session.execute(select(DocKindDef).where(DocKindDef.key == norm))
    ).scalar_one()
    if label is not None and label.strip():
        row.label = label.strip()
    if stage is not None:
        row.stage = stage.value
    if expected is not None:
        row.expected = expected
    if sort_order is not None:
        row.sort_order = sort_order
    row.updated_at = utcnow()
    await session.flush()
    return row


class KindMergeError(ValueError):
    pass


async def merge_kind(session: AsyncSession, source: str, target: str) -> int:
    """Fold kind `source` into `target`: every doc of `source` takes `target`, and the
    `source` catalog row is removed (a built-in row is kept, just emptied). Returns the number
    of docs rewritten."""
    src = normalize_slug(source)
    dst = await ensure_kind(session, target)
    if src == dst:
        raise KindMergeError("A kind cannot be merged into itself")
    result = await session.execute(
        update(DocReference).where(col(DocReference.kind) == src).values(kind=dst)
    )
    row = (
        await session.execute(select(DocKindDef).where(DocKindDef.key == src))
    ).scalar_one_or_none()
    if row is not None and not row.builtin:
        await session.delete(row)
    await session.flush()
    return int(getattr(result, "rowcount", 0) or 0)
