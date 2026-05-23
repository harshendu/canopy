#!/usr/bin/env bash
# Idempotent environment bootstrap for canopy.
# Designed to run on a vanilla VM with only the repo checked out + python3 and node/npm
# on PATH. Creates the backend venv, installs Python + Node deps, and only reinstalls
# when the env is missing/incomplete or a lockfile changed. Safe to run repeatedly.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

require() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "✖ setup: required tool '$1' not found on PATH. Install it and re-run." >&2
    exit 1
  }
}

echo "▶ canopy setup: checking toolchain"
require python3
require npm

# --- Backend: venv + deps ---
PY="$REPO_ROOT/backend/.venv/bin/python"
B_STAMP="$REPO_ROOT/backend/.venv/.ci-stamp"
b_need=0
[ -x "$PY" ] || b_need=1
if [ "$b_need" = 0 ] && ! "$PY" -c "import pytest, fastapi, sqlmodel, networkx, arq" >/dev/null 2>&1; then
  b_need=1
fi
if [ "$b_need" = 0 ] && [ -f "$B_STAMP" ] && [ "$REPO_ROOT/backend/pyproject.toml" -nt "$B_STAMP" ]; then
  b_need=1
fi
if [ "$b_need" = 1 ]; then
  echo "▶ backend: creating venv + installing deps (this is the slow first run)"
  [ -x "$PY" ] || python3 -m venv "$REPO_ROOT/backend/.venv"
  "$PY" -m pip install --quiet --upgrade pip
  ( cd "$REPO_ROOT/backend" && "$PY" -m pip install --quiet -e ".[dev]" )
else
  echo "▶ backend: env already satisfied"
fi
touch "$B_STAMP"

# --- Frontend: node deps ---
F_STAMP="$REPO_ROOT/frontend/node_modules/.ci-stamp"
f_need=0
{ [ -d "$REPO_ROOT/frontend/node_modules" ] && [ -x "$REPO_ROOT/frontend/node_modules/.bin/vite" ]; } || f_need=1
if [ "$f_need" = 0 ] && [ -f "$F_STAMP" ] && [ "$REPO_ROOT/frontend/package-lock.json" -nt "$F_STAMP" ]; then
  f_need=1
fi
if [ "$f_need" = 1 ]; then
  echo "▶ frontend: installing node deps (this is the slow first run)"
  if [ -f "$REPO_ROOT/frontend/package-lock.json" ]; then
    ( cd "$REPO_ROOT/frontend" && npm ci )
  else
    ( cd "$REPO_ROOT/frontend" && npm install )
  fi
else
  echo "▶ frontend: deps already satisfied"
fi
touch "$F_STAMP"

echo "✓ setup complete"
