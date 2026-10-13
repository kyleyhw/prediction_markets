"""A connection the server drops mid-answer is retried, then given up on."""

from __future__ import annotations

import pytest
import requests

from vp.venues import _http


class Flaky:
    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    def get(self, url, **_kwargs):
        self.calls += 1
        if self.calls <= self.failures:
            raise requests.exceptions.ChunkedEncodingError("Connection reset by peer")
        response = requests.Response()
        response.status_code = 200
        return response


def _get(monkeypatch, failures: int) -> tuple[Flaky, requests.Response]:
    session = Flaky(failures)
    monkeypatch.setattr(_http, "_session_for", lambda _key: session)
    monkeypatch.setattr(_http.time, "sleep", lambda _s: None)
    return session, _http.throttled_get(
        "https://x.invalid", host_key="retry-test", min_interval=0.0
    )


def test_a_dropped_connection_is_retried(monkeypatch):
    session, response = _get(monkeypatch, failures=2)
    assert response.status_code == 200 and session.calls == 3


def test_it_gives_up_after_the_retries(monkeypatch):
    with pytest.raises(requests.exceptions.ChunkedEncodingError):
        _get(monkeypatch, failures=_http.CONNECTION_RETRIES + 1)
