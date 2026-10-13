"""Refuse to run with publicly known or guessable secrets.

canopy's source is public, so the placeholder values in its templates and docs are public too: a
deployment that kept `SECRET_KEY=change-me` would let anyone sign tokens for any user. These
checks run when the API and the worker start — not at import, so tests, Alembic and scripts are
unaffected — and stop startup with instructions instead of running insecurely.
"""

from app.core.config import settings
from app.schemas.auth import MIN_PASSWORD_LENGTH

# RFC 7518 §3.2: an HS256 key must be at least as long as the hash output (32 bytes).
MIN_SECRET_KEY_BYTES = 32

# Values this repo has published as defaults or examples. Anything shorter than the minimum is
# rejected by length anyway; these are listed so the error can say what's wrong.
PLACEHOLDER_SECRET_KEYS = frozenset({"change-me", "change-me-to-a-long-random-string"})
PLACEHOLDER_PASSWORDS = frozenset({"changeme", "change-me", "password", "canopy-demo"})

_GENERATE = 'python3 -c "import secrets; print(secrets.token_urlsafe(48))"'


class InsecureConfigError(RuntimeError):
    """A setting holds a value that would let anyone in, so startup must not continue."""


def secret_key_problem(value: str) -> str | None:
    """Why `value` can't be used as SECRET_KEY, or None when it can."""
    if not value:
        return "SECRET_KEY is not set"
    if value.strip() in PLACEHOLDER_SECRET_KEYS:
        return "SECRET_KEY is a placeholder published in canopy's source"
    if len(value.encode()) < MIN_SECRET_KEY_BYTES:
        return f"SECRET_KEY is shorter than {MIN_SECRET_KEY_BYTES} bytes"
    return None


def first_superuser_password_problem(value: str) -> str | None:
    """Why `value` can't be the first admin's password, or None when it can."""
    if value.strip().lower() in PLACEHOLDER_PASSWORDS:
        return "FIRST_SUPERUSER_PASSWORD is a placeholder published in canopy's source"
    if len(value) < MIN_PASSWORD_LENGTH:
        return f"FIRST_SUPERUSER_PASSWORD is shorter than {MIN_PASSWORD_LENGTH} characters"
    return None


def ensure_secure_secret_key() -> None:
    """Raise InsecureConfigError unless SECRET_KEY is a strong, non-published value."""
    problem = secret_key_problem(settings.SECRET_KEY)
    if problem:
        raise InsecureConfigError(
            f"{problem}. It signs every access token (and, unless TOKEN_ENCRYPTION_KEY is set, "
            "derives the key that encrypts connector credentials), so a guessable value lets "
            f"anyone sign in as any user. Set it to a random value of at least "
            f"{MIN_SECRET_KEY_BYTES} characters — e.g. `{_GENERATE}` — or run "
            "`python3 scripts/init.py` to generate a complete .env."
        )


def ensure_safe_first_superuser_password() -> None:
    """Raise InsecureConfigError rather than create an admin with a guessable password."""
    problem = first_superuser_password_problem(settings.FIRST_SUPERUSER_PASSWORD or "")
    if problem:
        raise InsecureConfigError(
            f"{problem}, so the first admin account was not created. Set a strong "
            "FIRST_SUPERUSER_PASSWORD (or run `python3 scripts/init.py` to generate one), then "
            "restart."
        )
