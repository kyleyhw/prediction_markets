"""Entry points for the platform: serve the web service, migrate the database.

Reached from `vp serve` and `vp db migrate`. The command-line module
imports this lazily, inside those two commands, so the engine's commands
never load the platform.
"""

from __future__ import annotations

import uvicorn

from vp.platform.config import ConfigError, load_settings
from vp.platform.db import connect, migrate
from vp.platform.web import create_app, install_log_redaction


def serve(host: str, port: int) -> None:
    """Run the web service until interrupted."""
    settings = load_settings()
    app = create_app(settings)
    # uvicorn configures its loggers when the config is built, so the filter
    # is attached after that and before the first request is logged.
    config = uvicorn.Config(app, host=host, port=port, proxy_headers=True)
    install_log_redaction()
    print(
        f"vp serve: http://{host}:{port}/  (public URL {settings.public_url}, "
        f"database {settings.redacted_database_url})"
    )
    uvicorn.Server(config).run()


def migrate_database() -> list[str]:
    """Apply pending migrations as the owner, and return their names.

    Raises:
        ConfigError: `VP_MIGRATION_DATABASE_URL` is not set.
    """
    settings = load_settings()
    if not settings.migration_database_url:
        raise ConfigError("VP_MIGRATION_DATABASE_URL is required to migrate")
    with connect(settings.migration_database_url) as conn:
        return migrate(conn)
