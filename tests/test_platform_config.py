"""Platform configuration: required settings, parsing, and redaction."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from vp.platform.config import (
    ConfigError,
    Environment,
    Settings,
    load_settings,
)

MINIMAL = {"VP_DATABASE_URL": "postgresql:///vp_dev"}


def test_defaults_are_development_and_local() -> None:
    settings = load_settings(MINIMAL)
    assert settings.environment is Environment.DEVELOPMENT
    assert settings.data_root == Path("data")
    assert settings.is_production is False


def test_database_url_is_required_and_has_no_default() -> None:
    with pytest.raises(ConfigError, match="VP_DATABASE_URL"):
        load_settings({})
    with pytest.raises(ConfigError, match="VP_DATABASE_URL"):
        load_settings({"VP_DATABASE_URL": "   "})


def test_environment_parses_and_rejects_anything_else() -> None:
    assert load_settings(MINIMAL | {"VP_ENV": "production"}).is_production
    assert (
        load_settings(MINIMAL | {"VP_ENV": " Staging "}).environment
        is Environment.STAGING
    )
    with pytest.raises(ConfigError, match="VP_ENV"):
        load_settings(MINIMAL | {"VP_ENV": "prod"})


def test_the_password_never_reaches_a_log_line() -> None:
    """A settings object in a traceback must not carry the password."""
    # A made-up password, present to prove it is redacted.
    fake_url = "postgresql://vp:hunter2@db.internal:5432/vp"  # pragma: allowlist secret
    settings = load_settings({"VP_DATABASE_URL": fake_url})
    assert "hunter2" not in repr(settings)
    assert "hunter2" not in settings.redacted_database_url
    assert settings.redacted_database_url == (
        "postgresql://vp:[redacted]@db.internal:5432/vp"
    )
    # The real value is still available to whoever asks for it by name.
    assert settings.database_url.endswith("hunter2@db.internal:5432/vp")


def test_a_url_without_a_password_is_left_alone() -> None:
    url = "postgresql:///vp_dev?host=/var/run/postgresql"
    assert load_settings({"VP_DATABASE_URL": url}).redacted_database_url == url


def test_settings_are_frozen() -> None:
    settings = load_settings(MINIMAL)
    with pytest.raises(FrozenInstanceError):
        settings.environment = Environment.PRODUCTION  # ty: ignore[invalid-assignment]


def test_data_root_is_overridable() -> None:
    settings = Settings(database_url="x", data_root=Path("/srv/data"))
    assert settings.data_root == Path("/srv/data")
