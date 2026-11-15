"""Assemble design-doc read models: each doc with its catalog entry and its labelled links.

Batched — one query for the links and one per linked entity type — so a Docs tab with many
docs stays a handful of queries.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.models.doc import DocLink, DocReference, DocRevision
from app.schemas.docs import (
    DesignDocDetail,
    DesignDocRead,
    DocHealthFlagRead,
    DocLinkRead,
    DocRevisionRead,
    EntityDocRead,
)
from app.services import design_docs
from app.services.doc_health import HealthFlag
from app.services.doc_kinds import KindInfo, load_catalog, resolve_kind


def _link_read(link: DocLink, labels: dict[tuple[str, int], str]) -> DocLinkRead:
    read = DocLinkRead.model_validate(link)
    read.label = labels.get((link.entity_type, link.entity_id))
    return read


def _doc_read(
    doc: DocReference,
    links: list[DocLink],
    labels: dict[tuple[str, int], str],
    catalog: dict[str, KindInfo],
    health: list[HealthFlag],
) -> DesignDocRead:
    info = resolve_kind(catalog, doc.kind)
    base = DesignDocRead.model_validate(
        {
            **doc.model_dump(),
            "kind_label": info.label,
            "stage": info.stage,
            "personal": doc.private_to_user_id is not None,
            "links": [],
        }
    )
    base.links = [_link_read(link, labels) for link in links]
    base.health = [DocHealthFlagRead(**vars(flag)) for flag in health]
    return base


async def design_doc_reads(
    session: AsyncSession, docs: Sequence[DocReference]
) -> list[DesignDocRead]:
    ids = [d.id for d in docs if d.id is not None]
    links = await design_docs.links_for(session, ids)
    labels = await design_docs.entity_labels(
        session, ((link.entity_type, link.entity_id) for group in links.values() for link in group)
    )
    catalog = await load_catalog(session)
    health = await design_docs.health_for(session, docs)
    return [
        _doc_read(d, links.get(d.id or 0, []), labels, catalog, health.get(d.id or 0, []))
        for d in docs
    ]


async def design_doc_detail(session: AsyncSession, doc: DocReference) -> DesignDocDetail:
    read = await design_doc_read(session, doc)
    rows = (
        await session.execute(
            select(DocRevision)
            .where(DocRevision.doc_id == doc.id)
            .order_by(col(DocRevision.created_at).desc(), col(DocRevision.id).desc())
        )
    ).scalars().all()
    return DesignDocDetail(
        **read.model_dump(),
        revisions=[DocRevisionRead.model_validate(r) for r in rows],
    )


async def design_doc_read(session: AsyncSession, doc: DocReference) -> DesignDocRead:
    return (await design_doc_reads(session, [doc]))[0]


async def entity_doc_reads(
    session: AsyncSession, pairs: Sequence[tuple[DocLink, DocReference]]
) -> list[EntityDocRead]:
    docs = await design_doc_reads(session, [doc for _, doc in pairs])
    labels = await design_docs.entity_labels(
        session, ((link.entity_type, link.entity_id) for link, _ in pairs)
    )
    return [
        EntityDocRead(link=_link_read(link, labels), doc=doc_read)
        for (link, _), doc_read in zip(pairs, docs, strict=True)
    ]
