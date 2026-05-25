"""A task's external resource links: its Jira issue, the GitHub PRs implementing it, and the
design docs (GitHub/Drive) scoped to it. Canopy links out to the systems that own the work — it
does not store the resources themselves (same boundary as the document graph)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.models.base import DocScope, Provider
from app.models.doc import DocReference
from app.models.integration import Connection, ExternalRef, PullRequest
from app.schemas.entities import (
    DocReferenceRead,
    JiraIssueLink,
    PullRequestRead,
    TaskExternalLinksRead,
)


def jira_browse_url(base_url: str | None, key: str) -> str | None:
    """Build a human Jira *browse* URL from a connection's base_url. OAuth connections store the
    non-browsable API base (``api.atlassian.com/ex/jira/{cloudId}``) from which the site host can't
    be derived, so return None there — the UI then shows the key without a link."""
    if not base_url or "api.atlassian.com" in base_url:
        return None
    return f"{base_url.rstrip('/')}/browse/{key}"


async def _jira_base_url(session: AsyncSession) -> str | None:
    result = await session.execute(
        select(Connection).where(
            Connection.provider == Provider.jira, col(Connection.active).is_(True)
        )
    )
    conn = result.scalars().first()
    if conn is None:
        return None
    base = conn.config.get("base_url")
    return str(base) if base else None


async def collect_task_links(session: AsyncSession, task_id: int) -> TaskExternalLinksRead:
    ref_result = await session.execute(
        select(ExternalRef).where(
            ExternalRef.provider == Provider.jira,
            ExternalRef.entity_type == "task",
            ExternalRef.entity_id == task_id,
        )
    )
    ref = ref_result.scalars().first()
    jira: JiraIssueLink | None = None
    if ref is not None:
        key = ref.external_key or ref.external_id
        jira = JiraIssueLink(key=key, url=jira_browse_url(await _jira_base_url(session), key))

    pr_result = await session.execute(
        select(PullRequest)
        .where(PullRequest.task_id == task_id)
        .order_by(col(PullRequest.number).desc())
    )
    prs = [PullRequestRead.model_validate(pr) for pr in pr_result.scalars().all()]

    doc_result = await session.execute(
        select(DocReference)
        .where(
            DocReference.scope_level == DocScope.task,
            DocReference.scope_id == task_id,
        )
        .order_by(col(DocReference.id).desc())
    )
    docs = [DocReferenceRead.model_validate(d) for d in doc_result.scalars().all()]

    return TaskExternalLinksRead(jira=jira, pull_requests=prs, docs=docs)
