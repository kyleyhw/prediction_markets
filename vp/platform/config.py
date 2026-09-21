"""Platform configuration: the only module that reads the environment.

Every other module takes its settings as arguments. One reader means the
whole configuration surface can be read on one page, a missing setting
fails at start rather than at the first request that needs it, and a test
(`tests/test_config_gate.py`) can prove no second reader has appeared.

Two rules the type system cannot express:

* **No secret has a default.** A missing `VP_DATABASE_URL` is a start-up
  error, never an empty string or a localhost guess, because a default
  that happens to work in development is how a service reaches the wrong
  database in production.
* **Secrets do not print.** `database_url` is excluded from the dataclass
  repr and exposed for logs only through `redacted_database_url`, so a
  settings object in a traceback or a log line cannot leak a password.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

#: Every platform setting is read from an environment variable with this
#: prefix, so an unprefixed name in the process environment is never ours.
PREFIX = "VP_"


class ConfigError(RuntimeError):
    """A required setting is missing, or a setting will not parse."""


class Environment(StrEnum):
    """Which deployment this process belongs to.

    The value gates nothing by itself; it is what other modules consult
    before relaxing a check, and what the report and the logs record.
    """

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


@dataclass(frozen=True)
class Settings:
    """The platform's settings, loaded once at process start.

    Attributes:
        database_url: libpq connection string for the platform database.
            Required, secret, and kept out of the repr.
        environment: the deployment this process belongs to.
        data_root: where the engine's Parquet files live for this process.
            A local path today; object storage replaces it in task 30.
    """

    database_url: str = field(repr=False)
    environment: Environment = Environment.DEVELOPMENT
    data_root: Path = Path("data")

    @property
    def is_production(self) -> bool:
        """Whether this process serves real users."""
        return self.environment is Environment.PRODUCTION

    @property
    def redacted_database_url(self) -> str:
        """The database URL with any password replaced, safe to log."""
        return _redact(self.database_url)


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Read the settings from the environment.

    Args:
        env: the mapping to read, for tests. Defaults to `os.environ`,
            which is the only place in the package that is read.

    Returns:
        The settings.

    Raises:
        ConfigError: a required setting is missing, or one will not parse.
    """
    source = os.environ if env is None else env
    return Settings(
        database_url=_require(source, "DATABASE_URL"),
        environment=_environment(source),
        data_root=Path(source.get(PREFIX + "DATA_ROOT", "data")),
    )


def _require(env: Mapping[str, str], name: str) -> str:
    """Return a required setting, or raise naming the variable."""
    value = env.get(PREFIX + name, "").strip()
    if not value:
        raise ConfigError(f"{PREFIX + name} is required and has no default")
    return value


def _environment(env: Mapping[str, str]) -> Environment:
    """Return the deployment, defaulting to development."""
    raw = env.get(PREFIX + "ENV", Environment.DEVELOPMENT.value).strip().lower()
    try:
        return Environment(raw)
    except ValueError:
        allowed = ", ".join(e.value for e in Environment)
        raise ConfigError(
            f"{PREFIX}ENV must be one of: {allowed}; got {raw!r}"
        ) from None


def _redact(url: str) -> str:
    """Replace the password in a connection URL with a fixed placeholder."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return "[unparsable url]"
    if parts.password is None:
        return url
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    return urlunsplit(
        parts._replace(netloc=f"{parts.username or ''}:[redacted]@{host}")
    )
