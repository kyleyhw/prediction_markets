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

# The platform's development database (Phase 13): start Postgres, point the
# service and its tests at it, and apply migrations. The engine works
# without it, so a failure here warns rather than stopping the session.
if bash "$CLAUDE_PROJECT_DIR/.claude/hooks/postgres.sh"; then
  DB='postgresql:///vp_dev?host=/var/run/postgresql'
  TEST='postgresql:///vp_test?host=/var/run/postgresql'
  export VP_DATABASE_URL="$DB&user=vp_app"
  export VP_MIGRATION_DATABASE_URL="$DB&user=postgres"
  {
    echo "export VP_DATABASE_URL='$VP_DATABASE_URL'"
    echo "export VP_MIGRATION_DATABASE_URL='$VP_MIGRATION_DATABASE_URL'"
    echo "export VP_TEST_DATABASE_URL='$TEST&user=postgres'"
    echo "export VP_TEST_APP_DATABASE_URL='$TEST&user=vp_app'"
  } >> "$CLAUDE_ENV_FILE"
  uv run vp db migrate || echo "warning: platform migrations failed" >&2
else
  echo "warning: development Postgres did not start; platform tests will skip" >&2
fi

# Commits carry the owner's identity, never the container's default.
git config user.name "Kyle"
git config user.email "kyleyhw@gmail.com"
