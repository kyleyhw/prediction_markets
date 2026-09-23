"""The web service's pure parts: origins, redaction, email, secrets, mail."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from vp.platform import auth
from vp.platform.config import ConfigError, MailMode, load_settings
from vp.platform.mail import Message, OutboxMailer
from vp.platform.web import RedactSecrets, redact, same_origin

PUBLIC = "http://127.0.0.1:8000"


class TestSameOrigin:
    """A state change must come from one of this service's own pages."""

    def test_the_public_origin_is_trusted(self) -> None:
        assert same_origin(PUBLIC, "anything", PUBLIC, None)

    def test_the_host_the_request_was_sent_to_is_trusted(self) -> None:
        """So http://localhost:8000 works when the public URL says 127.0.0.1."""
        assert same_origin("http://localhost:8000", "localhost:8000", PUBLIC, None)

    def test_another_site_is_refused(self) -> None:
        assert not same_origin("https://evil.example", "127.0.0.1:8000", PUBLIC, None)

    def test_an_opaque_origin_is_refused(self) -> None:
        """Sandboxed frames and some redirects send the literal `null`."""
        assert not same_origin("null", "127.0.0.1:8000", PUBLIC, None)

    def test_without_origin_only_fetch_metadata_counts(self) -> None:
        assert same_origin(None, "127.0.0.1:8000", PUBLIC, "same-origin")
        assert not same_origin(None, "127.0.0.1:8000", PUBLIC, "cross-site")
        assert not same_origin(None, "127.0.0.1:8000", PUBLIC, None)

    def test_a_null_origin_with_same_origin_fetch_metadata_is_ours(self) -> None:
        """What Chromium sends for our own form post under a strict referrer
        policy: found by driving a real browser, not by these tests."""
        assert same_origin("null", "127.0.0.1:8000", PUBLIC, "same-origin")
        assert not same_origin("null", "127.0.0.1:8000", PUBLIC, "cross-site")

    def test_fetch_metadata_saying_cross_site_is_not_overridden_by_host(self) -> None:
        assert not same_origin(
            "https://evil.example", "127.0.0.1:8000", PUBLIC, "cross-site"
        )


class TestRedaction:
    def test_a_token_in_a_query_string_is_replaced(self) -> None:
        line = 'GET /auth/verify?token=AbC_123-xyz HTTP/1.1" 200'
        assert redact(line) == 'GET /auth/verify?token=[redacted] HTTP/1.1" 200'

    def test_other_parameters_survive(self) -> None:
        assert redact("/x?a=1&token=s3cret&b=2") == "/x?a=1&token=[redacted]&b=2"

    def test_the_filter_keeps_the_access_log_argument_shape(self) -> None:
        """uvicorn's access formatter unpacks five positional arguments."""
        record = logging.LogRecord(
            "uvicorn.access",
            logging.INFO,
            __file__,
            1,
            '%s - "%s %s HTTP/%s" %d',
            ("127.0.0.1:5000", "GET", "/auth/verify?token=secret", "1.1", 200),
            None,
        )
        assert RedactSecrets().filter(record)
        assert isinstance(record.args, tuple) and len(record.args) == 5
        assert "secret" not in record.getMessage()
        assert "token=[redacted]" in record.getMessage()


class TestEmail:
    def test_addresses_are_trimmed_and_lower_cased(self) -> None:
        assert auth.normalize_email("  Ada@Example.ORG ") == "ada@example.org"

    @pytest.mark.parametrize(
        "raw", ["", "ada", "ada@", "@example.org", "ada@example", "a b@example.org"]
    )
    def test_what_cannot_be_an_address(self, raw: str) -> None:
        assert auth.normalize_email(raw) is None

    def test_an_overlong_address_is_refused(self) -> None:
        assert auth.normalize_email("a" * 250 + "@example.org") is None


def test_secrets_are_long_unique_and_stored_only_as_hashes() -> None:
    secrets = {auth.new_secret() for _ in range(200)}
    assert len(secrets) == 200
    one = next(iter(secrets))
    assert len(one) >= 43  # 32 bytes, URL-safe base64
    assert auth.digest(one) != one
    assert len(auth.digest(one)) == 64
    assert auth.digest(one) == auth.digest(one)


def test_the_outbox_writes_messages_but_never_logs_their_body(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    mailer = OutboxMailer(tmp_path / "outbox")
    with caplog.at_level(logging.INFO):
        mailer.send(Message("ada@example.org", "Sign in", "link: SECRET-LINK"))
    files = list((tmp_path / "outbox").glob("*.txt"))
    assert len(files) == 1
    assert "SECRET-LINK" in files[0].read_text()
    assert "SECRET-LINK" not in caplog.text
    assert mailer.sent[0].to == "ada@example.org"


class TestPlatformSettings:
    MINIMAL = {"VP_DATABASE_URL": "postgresql:///vp_dev"}

    def test_development_defaults(self) -> None:
        settings = load_settings(self.MINIMAL)
        assert settings.public_url == "http://127.0.0.1:8000"
        assert settings.mail_mode is MailMode.OUTBOX
        assert settings.migration_database_url is None
        assert settings.secure_cookies is False

    def test_the_migration_url_does_not_print(self) -> None:
        url = "postgresql://owner:pw@db/vp"  # pragma: allowlist secret
        settings = load_settings(self.MINIMAL | {"VP_MIGRATION_DATABASE_URL": url})
        assert settings.migration_database_url
        assert "owner:pw" not in repr(settings)

    def test_production_refuses_plain_http(self) -> None:
        with pytest.raises(ConfigError, match="https"):
            load_settings(self.MINIMAL | {"VP_ENV": "production"})

    def test_production_refuses_the_development_outbox(self) -> None:
        with pytest.raises(ConfigError, match="outbox"):
            load_settings(
                self.MINIMAL
                | {"VP_ENV": "production", "VP_PUBLIC_URL": "https://app.example"}
            )

    def test_https_turns_on_secure_cookies(self) -> None:
        settings = load_settings(
            self.MINIMAL | {"VP_PUBLIC_URL": "https://staging.example/"}
        )
        assert settings.secure_cookies is True
        assert settings.public_url == "https://staging.example"
