#!/bin/bash
# SessionStart hook for Claude Code on the web: make `uv run` work before the
# first turn. Runs only in remote sessions; local checkouts manage their own
# environment. Idempotent: every step is a no-op once it has been done.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"

if ! command -v uv > /dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$CLAUDE_ENV_FILE"

# The interpreter pinned in .python-version; uv downloads it if absent.
uv python install
# Project and dev dependencies from uv.lock; installs the `vp` entry point.
uv sync --frozen
