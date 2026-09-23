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
* **Secrets do not print.** Both database URLs are excluded from the
  dataclass repr and exposed for logs only through `redacted_database_url`,
  so a settings object in a traceback or a log line cannot leak a password.

Two database URLs, deliberately. `VP_DATABASE_URL` is what the service
connects with and must be the `vp_app` role, which row-level security
binds; the service refuses to start otherwise. `VP_MIGRATION_DATABASE_URL`
is the owner's, needed only by `vp db migrate`, so the web process never
holds a credential that bypasses tenancy.

The object store is a URL: `file:<path>` (the default, under the data
root) or `s3://<bucket>` with an endpoint and keys, which is how MinIO
stands in locally for the cloud's object storage (flag F16). The S3 keys,
the platform's model API key, the master key that wraps workspace keys and
the metrics token are secrets like the database URLs: out of the repr, no
defaults, and a feature whose secret is absent is off rather than guessed.

Production refuses two development conveniences outright: a public URL
that is not HTTPS, since session cookies must be `Secure`, and the
development mail outbox, since a sign-in link written to a file on the
server reaches nobody.
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


class MailMode(StrEnum):
    """Where sign-in emails go.

    Only the development outbox exists: messages are written to files under
    the data root. A real provider is chosen with the deploy (flag F3), and
    production will not start until it exists.
    """

    OUTBOX = "outbox"


class Telemetry(StrEnum):
    """Where traces go: nowhere, the log, or an OTLP collector."""

    NONE = "none"
    CONSOLE = "console"
    OTLP = "otlp"


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
        database_url: libpq connection string the service connects with, as
            `vp_app`. Required, secret, and kept out of the repr.
        environment: the deployment this process belongs to.
        data_root: where the engine's Parquet files live for this process.
            A local path today; object storage replaces it in task 30.
        public_url: the origin users reach the service at, used in sign-in
            links and as the trusted origin for state-changing requests.
        migration_database_url: the owner's connection string, for
            migrations only. Optional, secret, and kept out of the repr.
        mail_mode: where sign-in emails go.
    """

    database_url: str = field(repr=False)
    environment: Environment = Environment.DEVELOPMENT
    data_root: Path = Path("data")
    public_url: str = "http://127.0.0.1:8000"
    migration_database_url: str | None = field(default=None, repr=False)
    mail_mode: MailMode = MailMode.OUTBOX
    store_url: str = ""
    s3_endpoint: str | None = None
    s3_region: str = "us-east-1"
    s3_access_key: str | None = field(default=None, repr=False)
    s3_secret_key: str | None = field(default=None, repr=False)
    cache_dir: Path | None = None
    anthropic_api_key: str | None = field(default=None, repr=False)
    open_meteo_key: str | None = field(default=None, repr=False)
    master_key: str | None = field(default=None, repr=False)
    telemetry: Telemetry = Telemetry.NONE
    otlp_endpoint: str | None = None
    metrics_token: str | None = field(default=None, repr=False)
    # Set by `vp serve --workers` for its processes, under the name
    # prometheus_client itself reads; not a setting anyone configures.
    metrics_dir: Path | None = None

    @property
    def store(self) -> str:
        """The object store URL, defaulting to a directory under the data root."""
        return self.store_url or f"file:{self.data_root / 'store'}"

    @property
    def cache(self) -> Path:
        """Where object-store files are cached on local disk."""
        return self.cache_dir or self.data_root / "cache"

    @property
    def secure_cookies(self) -> bool:
        """Whether cookies carry `Secure`, which follows the public scheme."""
        return self.public_url.startswith("https://")

    @property
    def outbox_dir(self) -> Path:
        """Where the development mailer writes messages."""
        return self.data_root / "outbox"

    @property
    def is_production(self) -> bool:
        """Whether this process serves real users."""
        return self.environment is Environment.PRODUCTION

    @property
    def redacted_database_url(self) -> str:
        """The database URL with any password replaced, safe to log."""
        return _redact(self.database_url)


#: The directory prometheus_client's multiprocess mode keeps metrics in.
METRICS_DIR = "PROMETHEUS_MULTIPROC_DIR"


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
    environment = _environment(source)
    public_url = source.get(PREFIX + "PUBLIC_URL", "").strip().rstrip("/")
    mail_raw = source.get(PREFIX + "MAIL", MailMode.OUTBOX.value).strip().lower()
    try:
        mail_mode = MailMode(mail_raw)
    except ValueError:
        raise ConfigError(f"{PREFIX}MAIL must be 'outbox'; got {mail_raw!r}") from None
    settings = Settings(
        database_url=_require(source, "DATABASE_URL"),
        environment=environment,
        data_root=Path(source.get(PREFIX + "DATA_ROOT", "data")),
        public_url=public_url or "http://127.0.0.1:8000",
        migration_database_url=(
            source.get(PREFIX + "MIGRATION_DATABASE_URL", "").strip() or None
        ),
        mail_mode=mail_mode,
        store_url=_optional(source, "STORE") or "",
        s3_endpoint=_optional(source, "S3_ENDPOINT"),
        s3_region=_optional(source, "S3_REGION") or "us-east-1",
        s3_access_key=_optional(source, "S3_ACCESS_KEY"),
        s3_secret_key=_optional(source, "S3_SECRET_KEY"),
        cache_dir=Path(c) if (c := _optional(source, "CACHE_DIR")) else None,
        anthropic_api_key=_optional(source, "ANTHROPIC_API_KEY"),
        open_meteo_key=_optional(source, "OPEN_METEO_KEY"),
        master_key=_optional(source, "MASTER_KEY"),
        telemetry=_telemetry(source),
        otlp_endpoint=_optional(source, "OTLP_ENDPOINT"),
        metrics_token=_optional(source, "METRICS_TOKEN"),
        metrics_dir=Path(d) if (d := source.get(METRICS_DIR, "").strip()) else None,
    )
    if settings.store.startswith("s3://") and not (
        settings.s3_access_key and settings.s3_secret_key
    ):
        raise ConfigError(
            f"{PREFIX}STORE is s3:// but {PREFIX}S3_ACCESS_KEY or "
            f"{PREFIX}S3_SECRET_KEY is missing"
        )
    if not settings.store.startswith(("s3://", "file:")):
        raise ConfigError(f"{PREFIX}STORE must start with file: or s3://")
    if settings.is_production:
        if not settings.secure_cookies:
            raise ConfigError(f"{PREFIX}PUBLIC_URL must be https:// in production")
        if settings.mail_mode is MailMode.OUTBOX:
            raise ConfigError(
                "the development mail outbox cannot serve production; "
                "a mail provider is chosen with the deploy (flag F3)"
            )
    return settings


def _optional(env: Mapping[str, str], name: str) -> str | None:
    """Return an optional setting, or None when unset or blank."""
    return env.get(PREFIX + name, "").strip() or None


def _telemetry(env: Mapping[str, str]) -> Telemetry:
    raw = (env.get(PREFIX + "TELEMETRY", "") or "none").strip().lower()
    try:
        return Telemetry(raw)
    except ValueError:
        raise ConfigError(
            f"{PREFIX}TELEMETRY must be none, console or otlp; got {raw!r}"
        ) from None


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
