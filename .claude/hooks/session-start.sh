#!/bin/bash
# SessionStart hook for Claude Code on the web: make `uv run` work before the
# first turn, and commit as the repository owner. Runs only in remote
# sessions; local checkouts manage their own environment. Idempotent: every
# step is a no-op once it has been done.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"

# The container ships an old uv that cannot download the pinned interpreter;
# the installer is quick and overwrites in place, so run it every time.
curl -LsSf https://astral.sh/uv/install.sh | sh > /dev/null 2>&1 || true
export PATH="$HOME/.local/bin:$PATH"
echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$CLAUDE_ENV_FILE"

# The interpreter pinned in .python-version; uv downloads it if absent.
uv python install
# Project and dev dependencies from uv.lock; installs the `vp` entry point.
uv sync --frozen

# Commits carry the owner's identity, never the container's default.
git config user.name "Kyle"
git config user.email "kyleyhw@gmail.com"
