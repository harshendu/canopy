#!/usr/bin/env bash
#
# Self-contained end-to-end runner: boots the full canopy stack (FastAPI +
# Vite), waits for both to answer, runs the Selenium suite against it, and
# tears everything down on exit. Extra args are forwarded to pytest, e.g.:
#
#     ./run_e2e.sh -m smoke
#     ./run_e2e.sh tests/test_planning.py -v
#
# Browser/driver discovery is handled by conftest.py (Selenium Manager finds
# Chrome automatically on a normal dev box). Override in a sandbox with
# E2E_CHROME_BINARY / E2E_CHROMEDRIVER. See README.md.
set -euo pipefail

E2E_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$E2E_DIR/.." && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
export CANOPY_BASE_URL="${CANOPY_BASE_URL:-http://127.0.0.1:$FRONTEND_PORT}"
export FIRST_SUPERUSER_EMAIL="${CANOPY_EMAIL:-architect@example.com}"
export FIRST_SUPERUSER_PASSWORD="${CANOPY_PASSWORD:-canopy-dev-password}"
export CANOPY_EMAIL="$FIRST_SUPERUSER_EMAIL"
export CANOPY_PASSWORD="$FIRST_SUPERUSER_PASSWORD"
export SECRET_KEY="${SECRET_KEY:-e2e-secret-key}"

# Default to a throwaway sqlite db unless the caller supplies their own.
if [ -z "${DATABASE_URL:-}" ]; then
  E2E_DB_FILE="$E2E_DIR/.e2e.db"
  export DATABASE_URL="sqlite+aiosqlite:///$E2E_DB_FILE"
  rm -f "$E2E_DB_FILE"
fi

PIDS=()
cleanup() {
  for p in "${PIDS[@]:-}"; do [ -n "$p" ] && kill "$p" 2>/dev/null || true; done
}
trap cleanup EXIT INT TERM

wait_http() {
  local url="$1" tries="${2:-60}"
  for _ in $(seq 1 "$tries"); do
    curl -fsS "$url" >/dev/null 2>&1 && return 0
    sleep 1
  done
  return 1
}

echo "==> backend: migrate + serve on :$BACKEND_PORT"
cd "$BACKEND"
[ -d .venv ] || python3 -m venv .venv
# shellcheck disable=SC1091
. .venv/bin/activate
python -c "import fastapi" 2>/dev/null || pip install -q -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --host 127.0.0.1 --port "$BACKEND_PORT" >"$E2E_DIR/.backend.log" 2>&1 &
PIDS+=("$!")
deactivate

echo "==> frontend: vite dev on :$FRONTEND_PORT"
cd "$FRONTEND"
[ -d node_modules ] || npm install
npm run dev -- --port "$FRONTEND_PORT" >"$E2E_DIR/.frontend.log" 2>&1 &
PIDS+=("$!")

echo "==> waiting for stack..."
wait_http "http://127.0.0.1:$BACKEND_PORT/api/v1/health" \
  || { echo "backend did not start"; tail -20 "$E2E_DIR/.backend.log"; exit 1; }
wait_http "$CANOPY_BASE_URL/" \
  || { echo "frontend did not start"; tail -20 "$E2E_DIR/.frontend.log"; exit 1; }

echo "==> running e2e suite"
cd "$E2E_DIR"
[ -d .venv ] || python3 -m venv .venv
./.venv/bin/pip install -q -r requirements.txt
./.venv/bin/python -m pytest "$@"
