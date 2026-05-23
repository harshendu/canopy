#!/usr/bin/env bash
# Point this repo's git hooks at the version-controlled .githooks/ directory.
# Run once per clone:  ./scripts/install-hooks.sh
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
git -C "$REPO_ROOT" config core.hooksPath .githooks
chmod +x "$REPO_ROOT/.githooks/"* 2>/dev/null || true
echo "✓ git hooks installed (core.hooksPath = .githooks)"
echo "  pre-commit : backend pytest / frontend build, only for the layers you change"
echo "  pre-push   : basic CI — bootstraps the env then runs backend tests + frontend build"
