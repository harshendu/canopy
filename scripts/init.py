#!/usr/bin/env python3
"""Interactive first-run setup for canopy.

Collects the inputs needed to generate a `.env` file, writes it (backing up any
existing one), then optionally starts the stack — either the bundled Docker
compose stack or local dev servers (uvicorn + Vite).

Stdlib only, so it runs on a freshly checked-out machine with just `python3`.
The run step additionally needs Docker (for the compose path) or the project's
node/npm + the backend venv created by scripts/setup.sh (for the local path).

    python3 scripts/init.py                      # full wizard, then choose what to start
    python3 scripts/init.py --no-start           # interactive, just (re)generate .env
    python3 scripts/init.py --defaults           # non-interactive: SQLite + generated secrets
    python3 scripts/init.py --defaults --start docker   # non-interactive, then bring up Docker
"""

from __future__ import annotations

import argparse
import base64
import getpass
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = REPO_ROOT / ".env"
EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


# --- output helpers -------------------------------------------------------
def _c(code: str, text: str) -> str:
    if not sys.stdout.isatty():
        return text
    return f"\033[{code}m{text}\033[0m"


def header(msg: str) -> None:
    print("\n" + _c("1;36", f"▶ {msg}"))


def info(msg: str) -> None:
    print(f"  {msg}")


def success(msg: str) -> None:
    print(_c("1;32", f"✓ {msg}"))


def warn(msg: str) -> None:
    print(_c("1;33", f"! {msg}"))


def error(msg: str) -> None:
    print(_c("1;31", f"✖ {msg}"), file=sys.stderr)


# --- prompt helpers -------------------------------------------------------
def ask(question: str, default: str = "", *, allow_empty: bool = False) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        raw = input(_c("1", f"  {question}{suffix}: ")).strip()
        if raw:
            return raw
        if default:
            return default
        if allow_empty:
            return ""
        warn("Please enter a value.")


def ask_yes_no(question: str, *, default: bool = False) -> bool:
    hint = "Y/n" if default else "y/N"
    while True:
        raw = input(_c("1", f"  {question} [{hint}]: ")).strip().lower()
        if not raw:
            return default
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        warn("Please answer y or n.")


def ask_choice(question: str, options: list[tuple[str, str]]) -> str:
    info(question)
    for i, (_key, label) in enumerate(options, 1):
        print(f"    {i}) {label}")
    while True:
        raw = input(_c("1", f"  Choose [1-{len(options)}] (default 1): ")).strip()
        if not raw:
            return options[0][0]
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1][0]
        warn("Invalid choice.")


def ask_password(question: str, *, min_len: int = 8) -> str:
    while True:
        first = getpass.getpass(f"  {question}: ").strip()
        if len(first) < min_len:
            warn(f"Must be at least {min_len} characters.")
            continue
        if first != getpass.getpass("  Confirm password: ").strip():
            warn("Passwords do not match — try again.")
            continue
        return first


# --- config collection ----------------------------------------------------
def fernet_key() -> str:
    """A valid Fernet key (32 url-safe-base64 bytes) without the cryptography dep."""
    return base64.urlsafe_b64encode(os.urandom(32)).decode()


def defaults() -> dict[str, str]:
    return {
        "POSTGRES_USER": "canopy",
        "POSTGRES_PASSWORD": "canopy",
        "POSTGRES_DB": "canopy",
        "DATABASE_URL": "sqlite+aiosqlite:///./canopy.db",
        "REDIS_URL": "redis://localhost:6379/0",
        "SECRET_KEY": secrets.token_urlsafe(48),
        "ACCESS_TOKEN_EXPIRE_MINUTES": "480",
        "TOKEN_ENCRYPTION_KEY": fernet_key(),
        "FIRST_SUPERUSER_EMAIL": "architect@example.com",
        "FIRST_SUPERUSER_PASSWORD": "",
        "BACKEND_CORS_ORIGINS": "http://localhost:5173,http://localhost:4173",
        "CANOPY_API_BASE_URL": "http://localhost:8000",
        "CANOPY_API_TOKEN": "",
        "GITHUB_WEBHOOK_SECRET": "",
        "JIRA_WEBHOOK_SECRET": "",
        "OAUTH_REDIRECT_BASE_URL": "http://localhost:8000",
        "FRONTEND_BASE_URL": "http://localhost:5173",
        "JIRA_OAUTH_CLIENT_ID": "",
        "JIRA_OAUTH_CLIENT_SECRET": "",
        "GITHUB_OAUTH_CLIENT_ID": "",
        "GITHUB_OAUTH_CLIENT_SECRET": "",
        "GOOGLE_OAUTH_CLIENT_ID": "",
        "GOOGLE_OAUTH_CLIENT_SECRET": "",
    }


def collect_defaults() -> dict[str, str]:
    """Non-interactive config: stock defaults + a generated admin password."""
    env = defaults()
    env["FIRST_SUPERUSER_PASSWORD"] = secrets.token_urlsafe(18)
    return env


def collect() -> dict[str, str]:
    env = defaults()

    header("Database")
    info("The bundled Docker stack always runs PostgreSQL; this choice sets DATABASE_URL")
    info("for local (non-Docker) runs.")
    db = ask_choice(
        "Which database backs local runs?",
        [
            ("sqlite", "SQLite — zero-setup, dev/local only (recommended to start)"),
            ("postgres", "PostgreSQL"),
            ("mysql", "MySQL / MariaDB (needs the optional aiomysql driver)"),
        ],
    )
    if db == "sqlite":
        env["DATABASE_URL"] = "sqlite+aiosqlite:///./canopy.db"
    elif db == "postgres":
        host = ask("Postgres host", "localhost")
        port = ask("Postgres port", "5432")
        user = ask("Postgres user", "canopy")
        password = ask("Postgres password", "canopy")
        name = ask("Postgres database", "canopy")
        env["DATABASE_URL"] = (
            f"postgresql+asyncpg://{quote(user)}:{quote(password)}@{host}:{port}/{name}"
        )
        # Keep the bundled Docker `db` service in sync with these creds.
        env["POSTGRES_USER"], env["POSTGRES_PASSWORD"], env["POSTGRES_DB"] = user, password, name
    else:
        host = ask("MySQL host", "localhost")
        port = ask("MySQL port", "3306")
        user = ask("MySQL user", "canopy")
        password = ask("MySQL password", "canopy")
        name = ask("MySQL database", "canopy")
        env["DATABASE_URL"] = (
            f"mysql+aiomysql://{quote(user)}:{quote(password)}@{host}:{port}/{name}"
        )
        warn('MySQL needs the optional driver: pip install -e "backend/.[mysql]".')
        warn("The bundled Docker stack uses Postgres regardless of this setting.")

    env["REDIS_URL"] = ask("Redis URL (used by the background worker)", env["REDIS_URL"])

    header("Administrator account")
    info("Seeded on first startup so you can log in to the dashboard.")
    email = ask("Admin email", env["FIRST_SUPERUSER_EMAIL"])
    while not EMAIL_RE.fullmatch(email):
        warn("That doesn't look like an email address.")
        email = ask("Admin email", env["FIRST_SUPERUSER_EMAIL"])
    env["FIRST_SUPERUSER_EMAIL"] = email
    if ask_yes_no("Auto-generate a strong admin password?", default=True):
        password = secrets.token_urlsafe(18)
        success(f"Generated admin password: {password}")
        warn("Save it now — it's stored in .env but won't be printed again.")
        env["FIRST_SUPERUSER_PASSWORD"] = password
    else:
        env["FIRST_SUPERUSER_PASSWORD"] = ask_password("Admin password (min 8 chars)")

    header("Secrets")
    success("Generated a random SECRET_KEY and Fernet TOKEN_ENCRYPTION_KEY.")

    header("Integrations (optional)")
    if ask_yes_no("Configure webhook secrets / OAuth client credentials now?", default=False):
        if ask_yes_no("Auto-generate random GitHub & Jira webhook secrets?", default=True):
            env["GITHUB_WEBHOOK_SECRET"] = secrets.token_hex(32)
            env["JIRA_WEBHOOK_SECRET"] = secrets.token_hex(32)
            info("Set the same secrets in your GitHub / Jira webhook configuration.")
        for label, key in (
            ("Jira", "JIRA_OAUTH"),
            ("GitHub", "GITHUB_OAUTH"),
            ("Google", "GOOGLE_OAUTH"),
        ):
            if ask_yes_no(f"Set {label} OAuth client credentials?", default=False):
                env[f"{key}_CLIENT_ID"] = ask(f"{label} OAuth client id", allow_empty=True)
                env[f"{key}_CLIENT_SECRET"] = ask(f"{label} OAuth client secret", allow_empty=True)
    else:
        info("Leaving connector secrets blank — you can edit .env later.")

    return env


# --- .env rendering / writing ---------------------------------------------
def render_env(e: dict[str, str]) -> str:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"# Generated by scripts/init.py on {stamp}. Edit freely.",
        "# This file is gitignored — do not commit it.",
        "",
        "# --- Postgres (bundled Docker `db` service) ---",
        f"POSTGRES_USER={e['POSTGRES_USER']}",
        f"POSTGRES_PASSWORD={e['POSTGRES_PASSWORD']}",
        f"POSTGRES_DB={e['POSTGRES_DB']}",
        "",
        "# --- Backend ---",
        "# DATABASE_URL is used for local (non-Docker) runs; compose overrides it to the `db` service.",
        f"DATABASE_URL={e['DATABASE_URL']}",
        f"REDIS_URL={e['REDIS_URL']}",
        "",
        "# JWT auth",
        f"SECRET_KEY={e['SECRET_KEY']}",
        f"ACCESS_TOKEN_EXPIRE_MINUTES={e['ACCESS_TOKEN_EXPIRE_MINUTES']}",
        "",
        "# Fernet key used to encrypt connector tokens at rest.",
        f"TOKEN_ENCRYPTION_KEY={e['TOKEN_ENCRYPTION_KEY']}",
        "",
        "# First superuser seeded on startup.",
        f"FIRST_SUPERUSER_EMAIL={e['FIRST_SUPERUSER_EMAIL']}",
        f"FIRST_SUPERUSER_PASSWORD={e['FIRST_SUPERUSER_PASSWORD']}",
        "",
        "# CORS (comma-separated origins for the React dev server)",
        f"BACKEND_CORS_ORIGINS={e['BACKEND_CORS_ORIGINS']}",
        "",
        "# --- Claude MCP server (plugin) ---",
        f"CANOPY_API_BASE_URL={e['CANOPY_API_BASE_URL']}",
        f"CANOPY_API_TOKEN={e['CANOPY_API_TOKEN']}",
        "",
        "# --- Connector webhook secrets (optional until configured) ---",
        f"GITHUB_WEBHOOK_SECRET={e['GITHUB_WEBHOOK_SECRET']}",
        f"JIRA_WEBHOOK_SECRET={e['JIRA_WEBHOOK_SECRET']}",
        "",
        "# --- OAuth 2.0 (3LO) ---",
        f"OAUTH_REDIRECT_BASE_URL={e['OAUTH_REDIRECT_BASE_URL']}",
        f"FRONTEND_BASE_URL={e['FRONTEND_BASE_URL']}",
        f"JIRA_OAUTH_CLIENT_ID={e['JIRA_OAUTH_CLIENT_ID']}",
        f"JIRA_OAUTH_CLIENT_SECRET={e['JIRA_OAUTH_CLIENT_SECRET']}",
        f"GITHUB_OAUTH_CLIENT_ID={e['GITHUB_OAUTH_CLIENT_ID']}",
        f"GITHUB_OAUTH_CLIENT_SECRET={e['GITHUB_OAUTH_CLIENT_SECRET']}",
        f"GOOGLE_OAUTH_CLIENT_ID={e['GOOGLE_OAUTH_CLIENT_ID']}",
        f"GOOGLE_OAUTH_CLIENT_SECRET={e['GOOGLE_OAUTH_CLIENT_SECRET']}",
        "",
    ]
    return "\n".join(lines)


def write_env(text: str) -> None:
    if ENV_PATH.exists():
        backup = ENV_PATH.with_name(f".env.bak.{datetime.now():%Y%m%d-%H%M%S}")
        shutil.copy2(ENV_PATH, backup)
        success(f"Backed up existing .env -> {backup.name}")
    ENV_PATH.write_text(text)
    try:
        os.chmod(ENV_PATH, 0o600)
    except OSError:
        pass
    success(f"Wrote {ENV_PATH}")


def load_env_file() -> dict[str, str]:
    data: dict[str, str] = {}
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        data[key.strip()] = value.strip()
    return data


# --- service launch -------------------------------------------------------
def docker_compose_cmd() -> list[str] | None:
    if shutil.which("docker"):
        try:
            subprocess.run(
                ["docker", "compose", "version"], check=True, capture_output=True
            )
            return ["docker", "compose"]
        except (subprocess.CalledProcessError, OSError):
            pass
    if shutil.which("docker-compose"):
        return ["docker-compose"]
    return None


def start_docker() -> None:
    cmd = docker_compose_cmd()
    if cmd is None:
        error("Docker (with the compose plugin) was not found on PATH.")
        info("Install Docker, then run: docker compose up --build")
        return
    header("Starting the Docker stack")
    info("Running: " + " ".join(cmd + ["up", "--build"]))
    info("Migrations and superuser seeding run automatically. Press Ctrl+C to stop.")
    info("API: http://localhost:8000/docs   Web: http://localhost:5173")
    try:
        subprocess.run(cmd + ["up", "--build"], cwd=REPO_ROOT)
    except KeyboardInterrupt:
        pass


def venv_python() -> Path:
    bindir = "Scripts" if os.name == "nt" else "bin"
    name = "python.exe" if os.name == "nt" else "python"
    return REPO_ROOT / "backend" / ".venv" / bindir / name


def _shutdown(procs: list[subprocess.Popen[bytes]]) -> None:
    for proc in procs:
        if proc.poll() is None:
            proc.terminate()
    for proc in procs:
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    info("Stopped.")


def start_local(env_values: dict[str, str]) -> None:
    header("Starting local dev servers")
    if os.name == "nt":
        warn("Local mode uses scripts/setup.sh (bash); on Windows use the Docker path or WSL.")
        return

    setup = REPO_ROOT / "scripts" / "setup.sh"
    if setup.exists():
        info("Bootstrapping the toolchain (scripts/setup.sh)…")
        if subprocess.run(["bash", str(setup)], cwd=REPO_ROOT).returncode != 0:
            error("scripts/setup.sh failed — see output above.")
            return

    py = venv_python()
    if not py.exists():
        error(f"Backend venv not found at {py}. Run scripts/setup.sh first.")
        return

    child_env = {**os.environ, **env_values}
    backend_dir = REPO_ROOT / "backend"

    info("Applying database migrations (alembic upgrade head)…")
    migrated = subprocess.run(
        [str(py), "-m", "alembic", "upgrade", "head"], cwd=backend_dir, env=child_env
    )
    if migrated.returncode != 0:
        error("alembic upgrade head failed — check DATABASE_URL and that your DB is running.")
        return

    procs: list[subprocess.Popen[bytes]] = []
    info("Starting backend (uvicorn) on http://localhost:8000")
    procs.append(
        subprocess.Popen(
            [str(py), "-m", "uvicorn", "app.main:app", "--reload",
             "--host", "0.0.0.0", "--port", "8000"],
            cwd=backend_dir,
            env=child_env,
        )
    )
    if shutil.which("npm"):
        info("Starting frontend (npm run dev) on http://localhost:5173")
        procs.append(
            subprocess.Popen(["npm", "run", "dev"], cwd=REPO_ROOT / "frontend", env=child_env)
        )
    else:
        warn("npm not found — skipping frontend. Install Node, then run `npm run dev` in frontend/.")

    warn("The background worker needs Redis and isn't started here (see README to run arq).")
    success("API: http://localhost:8000/docs   Web: http://localhost:5173")
    info("Press Ctrl+C to stop all servers.")
    try:
        while all(proc.poll() is None for proc in procs):
            time.sleep(0.5)
        error("A server process exited unexpectedly — shutting the rest down.")
    except KeyboardInterrupt:
        pass
    _shutdown(procs)


# --- main -----------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(
        description="Interactive setup for canopy: generate .env and start services."
    )
    parser.add_argument(
        "--defaults",
        action="store_true",
        help="Run non-interactively with default values (SQLite, generated secrets + admin password).",
    )
    parser.add_argument(
        "--start",
        choices=["docker", "local", "none"],
        help="What to start after writing .env (skips the prompt).",
    )
    parser.add_argument(
        "--no-start", action="store_true", help="Alias for --start none."
    )
    args = parser.parse_args()

    print(_c("1;36", "canopy setup"))
    info(f"Repo: {REPO_ROOT}")

    regenerate = True
    if ENV_PATH.exists() and not args.defaults:
        warn(f"An .env already exists at {ENV_PATH}")
        regenerate = ask_yes_no("Regenerate it? (the current one is backed up first)", default=False)
    if regenerate:
        if args.defaults:
            env = collect_defaults()
            header("Using defaults (non-interactive)")
            info(f"Database: {env['DATABASE_URL']}")
            info(f"Admin:    {env['FIRST_SUPERUSER_EMAIL']}")
            success(f"Generated admin password: {env['FIRST_SUPERUSER_PASSWORD']}")
            warn("Saved to .env — capture it now (won't be shown again).")
        else:
            env = collect()
        write_env(render_env(env))
    else:
        info("Keeping the existing .env.")

    # Resolve the start target without prompting when a flag (or --defaults) decides it.
    target = args.start
    if target is None and args.no_start:
        target = "none"
    if target is None and args.defaults:
        target = "none"
    if target is None:
        target = ask_choice(
            "What would you like to start now?",
            [
                ("docker", "Docker stack — postgres, redis, backend, worker, frontend (recommended)"),
                ("local", "Local dev servers — backend (uvicorn) + frontend (Vite)"),
                ("none", "Nothing — I'll start it myself later"),
            ],
        )

    if target == "docker":
        start_docker()
    elif target == "local":
        start_local(load_env_file())
    else:
        info("Skipped. Later: `docker compose up --build`, or re-run this with no flags.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        error("Aborted.")
        sys.exit(130)
