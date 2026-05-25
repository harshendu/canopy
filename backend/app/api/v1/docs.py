"""Document graph: typed *links* to documents that live elsewhere (Jira epics, Drive,
Figma, repo files), plus a coverage report. Canopy links, it never stores — see
`app/services/doc_graph.py`. Scope is polymorphic (project / initiative / task), validated
at the route since there is no FK (mirrors the risk register).
"""

from fastapi import APIRouter, HTTPException, status
from sqlmodel import col, select

from app.api.deps import CurrentUser, PlannerWriter, SessionDep
from app.models.base import DocKind, DocScope
from app.models.doc import DocReference
from app.models.project import Initiative, Project, Task
from app.schemas.entities import (
    DocCoverageRead,
    DocReferenceCreate,
    DocReferenceRead,
    DocReferenceUpdate,
)
from app.services import doc_graph

router = APIRouter()


async def _validate_scope(session: SessionDep, scope_level: DocScope, scope_id: int) -> None:
    if scope_level == DocScope.task:
        exists = await session.get(Task, scope_id) is not None
    elif scope_level == DocScope.project:
        exists = await session.get(Project, scope_id) is not None
    else:
        exists = await session.get(Initiative, scope_id) is not None
    if not exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{scope_level.value} {scope_id} not found",
        )


@router.get("/docs", response_model=list[DocReferenceRead])
async def list_docs(
    session: SessionDep,
    _: CurrentUser,
    scope_level: DocScope | None = None,
    scope_id: int | None = None,
    kind: DocKind | None = None,
) -> list[DocReference]:
    """Document references, newest first. Filter by scope and/or kind."""
    stmt = select(DocReference)
    if scope_level is not None:
        stmt = stmt.where(DocReference.scope_level == scope_level)
    if scope_id is not None:
        stmt = stmt.where(DocReference.scope_id == scope_id)
    if kind is not None:
        stmt = stmt.where(DocReference.kind == kind)
    rows = await session.execute(stmt.order_by(col(DocReference.id).desc()))
    return list(rows.scalars().all())


@router.post("/docs", response_model=DocReferenceRead, status_code=status.HTTP_201_CREATED)
async def create_doc(
    session: SessionDep, _: PlannerWriter, payload: DocReferenceCreate
) -> DocReference:
    await _validate_scope(session, payload.scope_level, payload.scope_id)
    item = DocReference(**payload.model_dump())
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item


@router.get("/docs/coverage", response_model=DocCoverageRead)
async def docs_coverage(
    session: SessionDep, _: CurrentUser, scope_level: DocScope, scope_id: int
) -> dict:
    """Which expected doc kinds are present vs missing for a scope (rolled up: a project
    includes its tasks; an initiative includes its projects and their tasks)."""
    return await doc_graph.coverage(session, scope_level, scope_id)


@router.patch("/docs/{doc_id}", response_model=DocReferenceRead)
async def update_doc(
    session: SessionDep, _: PlannerWriter, doc_id: int, payload: DocReferenceUpdate
) -> DocReference:
    item = await session.get(DocReference, doc_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Doc reference not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    await session.commit()
    await session.refresh(item)
    return item


@router.delete("/docs/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_doc(session: SessionDep, _: PlannerWriter, doc_id: int) -> None:
    item = await session.get(DocReference, doc_id)
    if item is not None:
        await session.delete(item)
        await session.commit()
