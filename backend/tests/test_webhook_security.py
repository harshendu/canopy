"""Webhook intake fails closed: no configured secret means no request is accepted."""

import hashlib
import hmac
import json

import pytest
from sqlmodel import select

import app.webhooks.events as events_webhook
import app.webhooks.github as github_webhook
import app.webhooks.jira as jira_webhook
from app.core.config import settings
from app.models.activity import ActivityEvent
from app.models.project import Project
from app.webhooks.security import verify_hmac_sha256
from tests.conftest import TestSession

SECRET = "webhook-test-secret"

# (path, secret setting, signature header)
ENDPOINTS = [
    ("/webhooks/github", "GITHUB_WEBHOOK_SECRET", "X-Hub-Signature-256"),
    ("/webhooks/jira", "JIRA_WEBHOOK_SECRET", "X-Hub-Signature"),
    ("/webhooks/events", "EVENTS_WEBHOOK_SECRET", "X-Hub-Signature-256"),
]


def _sign(body: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_verify_fails_closed_without_a_secret():
    body = b"{}"
    assert verify_hmac_sha256("", body, None) is False
    assert verify_hmac_sha256("", body, _sign(body, "")) is False


def test_verify_accepts_only_a_matching_signature():
    body = b'{"a": 1}'
    assert verify_hmac_sha256(SECRET, body, _sign(body)) is True
    assert verify_hmac_sha256(SECRET, body, None) is False
    assert verify_hmac_sha256(SECRET, body, _sign(body, "a-guess")) is False
    assert verify_hmac_sha256(SECRET, b'{"a": 2}', _sign(body)) is False


@pytest.mark.parametrize(("path", "setting", "header"), ENDPOINTS)
async def test_unset_secret_rejects_every_request(client, monkeypatch, path, setting, header):
    monkeypatch.setattr(settings, setting, "")
    body = json.dumps({"project_id": 1, "kind": "incident_open"}).encode()

    unsigned = await client.post(path, content=body)
    signed = await client.post(path, content=body, headers={header: _sign(body, "")})

    for resp in (unsigned, signed):
        assert resp.status_code == 403
        assert setting in resp.json()["detail"]


@pytest.mark.parametrize(("path", "setting", "header"), ENDPOINTS)
async def test_missing_or_forged_signature_is_rejected(client, monkeypatch, path, setting, header):
    monkeypatch.setattr(settings, setting, SECRET)
    body = json.dumps({"project_id": 1, "kind": "incident_open"}).encode()

    unsigned = await client.post(path, content=body)
    forged = await client.post(path, content=body, headers={header: _sign(body, "a-guess")})

    assert unsigned.status_code == 401
    assert forged.status_code == 401


@pytest.mark.parametrize(
    ("module", "path", "setting", "header", "payload"),
    [
        (github_webhook, *ENDPOINTS[0], {"repository": {"full_name": "acme/platform"}}),
        (jira_webhook, *ENDPOINTS[1], {"issue": {"key": "PLAT-1"}}),
    ],
)
async def test_signed_sync_webhooks_are_accepted(
    client, monkeypatch, module, path, setting, header, payload
):
    monkeypatch.setattr(settings, setting, SECRET)
    monkeypatch.setattr(module, "async_session_factory", TestSession)
    body = json.dumps(payload).encode()

    resp = await client.post(path, content=body, headers={header: _sign(body)})

    assert resp.status_code == 202
    assert resp.json() == {"enqueued": 0}  # verified, but no connection tracks this repo/project


async def test_signed_event_is_recorded(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "EVENTS_WEBHOOK_SECRET", SECRET)
    monkeypatch.setattr(events_webhook, "async_session_factory", TestSession)
    project = Project(key="HOOK", name="Webhook target")
    db_session.add(project)
    await db_session.commit()
    body = json.dumps({"project_id": project.id, "kind": "deploy", "summary": "v1.2"}).encode()

    resp = await client.post(
        "/webhooks/events", content=body, headers={"X-Hub-Signature-256": _sign(body)}
    )

    assert resp.status_code == 202
    async with TestSession() as session:
        events = (await session.execute(select(ActivityEvent))).scalars().all()
    assert [(e.project_id, e.summary) for e in events] == [(project.id, "v1.2")]
