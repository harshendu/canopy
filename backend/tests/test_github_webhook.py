import pytest
from sqlmodel import func, select

from app.connectors.github import GitHubConnector
from app.models.base import Provider
from app.models.integration import Connection, PullRequest


async def _connector(session) -> GitHubConnector:
    connection = Connection(
        provider=Provider.github, name="gh", config={"owner": "acme", "repo": "platform"}
    )
    session.add(connection)
    await session.flush()
    return GitHubConnector(connection, session)


def _payload(number: int, title: str, state: str = "open") -> dict:
    return {
        "repository": {"full_name": "acme/platform"},
        "pull_request": {
            "number": number,
            "title": title,
            "state": state,
            "html_url": f"https://github.com/acme/platform/pull/{number}",
            "user": {"login": "dev"},
            "updated_at": "2026-05-01T10:00:00Z",
        },
    }


@pytest.mark.asyncio
async def test_pr_webhook_upsert_idempotent(db_session):
    connector = await _connector(db_session)
    await connector.handle_webhook(_payload(1, "Add auth"))
    await connector.handle_webhook(_payload(1, "Add auth (revised)", state="closed"))

    count = (await db_session.execute(select(func.count()).select_from(PullRequest))).scalar()
    assert count == 1
    pr = (await db_session.execute(select(PullRequest))).scalar_one()
    assert pr.title == "Add auth (revised)"
    assert pr.state == "closed"


@pytest.mark.asyncio
async def test_pr_webhook_ignores_non_pr_event(db_session):
    connector = await _connector(db_session)
    result = await connector.handle_webhook({"repository": {"full_name": "acme/platform"}})
    assert result.created == 0
    count = (await db_session.execute(select(func.count()).select_from(PullRequest))).scalar()
    assert count == 0
