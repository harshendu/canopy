from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# config.py lives at backend/app/core/, so parents[2] is backend/ and its parent is the
# repo root (where .env.example lives). Anchoring to these absolute paths means the
# backend finds .env whether it's launched from the repo root or from backend/.
_BACKEND_DIR = Path(__file__).resolve().parents[2]
_REPO_ROOT = _BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Look for .env in both the repo root and backend/ (later wins). Real environment
        # variables still take precedence over both, so Docker's env_file injection and
        # explicit `export`s are unaffected.
        env_file=(_REPO_ROOT / ".env", _BACKEND_DIR / ".env"),
        extra="ignore",
        case_sensitive=False,
    )

    PROJECT_NAME: str = "Canopy"
    API_V1_PREFIX: str = "/api/v1"

    DATABASE_URL: str = "postgresql+asyncpg://canopy:canopy@localhost:5432/canopy"
    REDIS_URL: str = "redis://localhost:6379/0"

    SECRET_KEY: str = "change-me"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480
    JWT_ALGORITHM: str = "HS256"

    # Fernet key for encrypting connector tokens at rest. If empty, one is derived
    # from SECRET_KEY (fine for dev, set explicitly in production).
    TOKEN_ENCRYPTION_KEY: str = ""

    FIRST_SUPERUSER_EMAIL: str | None = None
    FIRST_SUPERUSER_PASSWORD: str | None = None

    # Demo / seeded-data mode (local & dev only — never enable in production). When true,
    # the admin "Demo data" controls and seed/reset endpoints are unlocked, and connectors
    # whose config carries `demo: true` are served by an in-process HTTP mock so the whole
    # UI — including "Sync from Jira" / GitHub / Drive reads — works fully offline.
    DEMO_MODE: bool = False

    # NoDecode: pydantic-settings JSON-decodes list/dict fields from env *before* validators
    # run; this keeps the raw string so _split_origins can parse the comma-separated form
    # shipped in .env.example.
    BACKEND_CORS_ORIGINS: Annotated[list[str], NoDecode] = [
        "http://localhost:5173",
        "http://localhost:4173",
    ]

    GITHUB_WEBHOOK_SECRET: str = ""
    JIRA_WEBHOOK_SECRET: str = ""
    EVENTS_WEBHOOK_SECRET: str = ""

    # Cron cadence (minutes) for the Jira reconciliation poll.
    JIRA_POLL_MINUTES: int = 10

    # --- OAuth 2.0 (3LO) ---
    # The provider redirects here after consent; must match the app registration.
    OAUTH_REDIRECT_BASE_URL: str = "http://localhost:8000"
    # Where the callback redirects the browser when done.
    FRONTEND_BASE_URL: str = "http://localhost:5173"
    JIRA_OAUTH_CLIENT_ID: str = ""
    JIRA_OAUTH_CLIENT_SECRET: str = ""
    GITHUB_OAUTH_CLIENT_ID: str = ""
    GITHUB_OAUTH_CLIENT_SECRET: str = ""
    GOOGLE_OAUTH_CLIENT_ID: str = ""
    GOOGLE_OAUTH_CLIENT_SECRET: str = ""

    # --- File-drop ingest (Phase 4) ---
    # Watched shared storage canopy polls for export files to ingest, layout
    # <root>/<connection_id>/*.{json,csv}. Backend "local" (a directory) or "s3" (a bucket);
    # empty disables the poll — the upload endpoint still works regardless.
    FILE_DROP_BACKEND: str = ""  # "" (disabled) | "local" | "s3"
    FILE_DROP_LOCAL_DIR: str = ""  # required when FILE_DROP_BACKEND=local
    FILE_DROP_S3_BUCKET: str = ""  # required when FILE_DROP_BACKEND=s3 (needs the [s3] extra)
    FILE_DROP_S3_PREFIX: str = "canopy-drops"  # key prefix within the bucket
    FILE_DROP_POLL_MINUTES: int = 10

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
