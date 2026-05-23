#!/usr/bin/env bash
# Basic CI for canopy: bootstrap the environment, then run backend tests and the
# frontend build. Used by the pre-push hook and runnable by hand:  scripts/ci.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "═══════════ canopy CI ═══════════"

# 1. Make sure the environment exists (works on a freshly-checked-out vanilla VM).
bash "$REPO_ROOT/scripts/setup.sh"

# 2. Backend tests.
echo "▶ backend: pytest"
( cd "$REPO_ROOT/backend" && "$REPO_ROOT/backend/.venv/bin/python" -m pytest -q )

# 3. Frontend typecheck + production build.
echo "▶ frontend: build (tsc + vite)"
( cd "$REPO_ROOT/frontend" && npm run build )

echo "✓ CI passed"
