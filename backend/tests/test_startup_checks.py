"""Startup refuses publicly known or guessable secrets instead of running with them."""

import secrets

import pytest
from sqlmodel import select

import app.main as main
from app.core.config import settings
from app.core.startup_checks import (
    InsecureConfigError,
    first_superuser_password_problem,
    secret_key_problem,
)
from app.models.base import UserRole
from app.models.user import User
from app.workers.worker import WorkerSettings
from tests.conftest import TestSession

STRONG_KEY = secrets.token_urlsafe(48)
GUESSABLE_KEYS = ["", "change-me", "change-me-to-a-long-random-string", "short-but-random-7f3a9c"]


@pytest.mark.parametrize("value", GUESSABLE_KEYS)
def test_guessable_secret_keys_are_rejected(value):
    assert secret_key_problem(value) is not None


def test_random_secret_key_is_accepted():
    assert secret_key_problem(STRONG_KEY) is None


@pytest.mark.parametrize("value", ["changeme", "ChangeMe", "password", "canopy-demo", "2short"])
def test_guessable_admin_passwords_are_rejected(value):
    assert first_superuser_password_problem(value) is not None


def test_random_admin_password_is_accepted():
    assert first_superuser_password_problem(secrets.token_urlsafe(18)) is None


@pytest.mark.parametrize("value", GUESSABLE_KEYS)
async def test_api_refuses_to_start_with_a_guessable_secret_key(monkeypatch, value):
    monkeypatch.setattr(settings, "SECRET_KEY", value)
    with pytest.raises(InsecureConfigError, match="SECRET_KEY"):
        async with main.lifespan(main.app):
            pass


async def test_worker_refuses_to_start_with_a_guessable_secret_key(monkeypatch):
    monkeypatch.setattr(settings, "SECRET_KEY", "change-me")
    with pytest.raises(InsecureConfigError, match="SECRET_KEY"):
        await WorkerSettings.on_startup({})


def _seed_as(monkeypatch, password: str) -> None:
    monkeypatch.setattr(settings, "SECRET_KEY", STRONG_KEY)
    monkeypatch.setattr(settings, "FIRST_SUPERUSER_EMAIL", "admin@example.com")
    monkeypatch.setattr(settings, "FIRST_SUPERUSER_PASSWORD", password)
    monkeypatch.setattr(main, "async_session_factory", TestSession)


async def _users() -> list[User]:
    async with TestSession() as session:
        return list((await session.execute(select(User))).scalars().all())


async def test_first_admin_is_not_created_with_a_placeholder_password(monkeypatch):
    _seed_as(monkeypatch, "changeme")
    with pytest.raises(InsecureConfigError, match="FIRST_SUPERUSER_PASSWORD"):
        async with main.lifespan(main.app):
            pass
    assert await _users() == []


async def test_first_admin_is_created_with_a_strong_password(monkeypatch):
    _seed_as(monkeypatch, secrets.token_urlsafe(18))
    async with main.lifespan(main.app):
        pass
    assert [(u.email, u.role) for u in await _users()] == [("admin@example.com", UserRole.admin)]


async def test_existing_admin_does_not_block_startup(db_session, monkeypatch):
    # Seeding only checks the password it would use: an admin created earlier (and maybe since
    # rotated in the UI) must not block startup over the value left in .env.
    db_session.add(User(email="admin@example.com", hashed_password="x", role=UserRole.admin))
    await db_session.commit()
    _seed_as(monkeypatch, "changeme")
    async with main.lifespan(main.app):
        pass
    assert len(await _users()) == 1
