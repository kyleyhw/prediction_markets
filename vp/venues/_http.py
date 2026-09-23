"""Throttled HTTP GET with per-host spacing and session reuse.

Public market-data endpoints rate-limit by source IP and may temporarily ban a
client that bursts requests. Every call routes through :func:`throttled_get`,
which enforces a minimum spacing between consecutive requests to the same
*host bucket* (plus a little jitter so concurrent workers do not lock-step) and
reuses one :class:`requests.Session` per bucket so TCP and TLS setup is
amortised. Spacing is best-effort and process-local.

Ported from HKUDS/Vibe-Trading ``agent/backtest/loaders/_http.py`` (MIT); see
``NOTICE`` and ``docs/provenance.md``. Changes: the environment-variable helper
is inlined, and the User-Agent identifies this project rather than imitating a
browser.
"""

from __future__ import annotations

import logging
import os
import random
import threading
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

USER_AGENT = "vibe-predict/0.1 (+https://github.com/kyleyhw/prediction_markets)"

# Upper bound on the random jitter (seconds) added on top of the configured
# minimum interval, so parallel callers de-synchronise instead of all firing the
# instant the interval elapses. 0.4 s is the upstream value: large enough to
# spread a handful of workers, small relative to a 15-20 s request timeout.
_JITTER_MAX_S = 0.4

# How often (seconds) the throttle drops buckets whose spacing window has fully
# elapsed, so a process that queries many distinct hosts does not accumulate
# dead entries without bound. Once a minute is the upstream value; sweeping is
# bookkeeping only and its exact period does not affect spacing.
_SWEEP_PERIOD_S = 60.0


class HostThrottle:
    """Process-wide minimum-spacing gate keyed by an arbitrary host bucket.

    ``wait(bucket, min_interval)`` blocks until at least ``min_interval``
    seconds (plus jitter) have elapsed since the last request tagged with the
    same ``bucket``. The lock is held only for the bookkeeping arithmetic, not
    across the sleep, so distinct buckets never block one another.
    """

    def __init__(self) -> None:
        self._last: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()
        self._last_sweep: float = 0.0

    def _sweep_stale_locked(self, cutoff: float) -> None:
        """Drop buckets whose spacing window has elapsed. Caller holds the lock.

        A bucket is stale only once ``fire_at + min_interval`` has passed;
        sweeping earlier would let the next request fire immediately.
        """
        stale = [k for k, (t, interval) in self._last.items() if t + interval < cutoff]
        for k in stale:
            del self._last[k]

    def wait(self, bucket: str, min_interval: float) -> None:
        """Block until ``bucket`` may fire again, then record the reserved slot.

        The reserved fire time, jitter included, is what gets stored, so the
        next caller spaces off this caller's actual fire instant. Jitter only
        ever pushes a slot later, never earlier.
        """
        if min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            if now - self._last_sweep >= _SWEEP_PERIOD_S:
                self._sweep_stale_locked(now)
                self._last_sweep = now
            entry = self._last.get(bucket)
            last = entry[0] if entry is not None else None
            if last is None or now >= last + min_interval:
                fire_at = now
            else:
                fire_at = last + min_interval + random.uniform(0.0, _JITTER_MAX_S)
            self._last[bucket] = (fire_at, min_interval)
        sleep_for = fire_at - time.monotonic()
        if sleep_for > 0:
            time.sleep(sleep_for)


_THROTTLE = HostThrottle()


class TokenBucket:
    """At most ``rate`` requests a second on average, in bursts of ``burst``.

    Where the minimum spacing above is the engine's courtesy for one
    command at a time, a long-running process with many callers (the
    platform's market-data service and workers) needs a rate: it lets a
    burst through at once and then holds the average. Configured per host
    bucket with :func:`set_rate`; a bucket with no rate is not limited
    beyond the spacing.
    """

    def __init__(self, rate: float, burst: int) -> None:
        if rate <= 0 or burst < 1:
            raise ValueError("a token bucket needs a positive rate and burst")
        self.rate = rate
        self.burst = burst
        self._tokens = float(burst)
        self._at = time.monotonic()
        self._lock = threading.Lock()

    def take(self) -> float:
        """Take one token, sleeping until one is available; returns the wait."""
        with self._lock:
            now = time.monotonic()
            self._tokens = min(self.burst, self._tokens + (now - self._at) * self.rate)
            self._at = now
            self._tokens -= 1.0
            wait = -self._tokens / self.rate if self._tokens < 0 else 0.0
        if wait > 0:
            time.sleep(wait)
        return wait


_BUCKETS: dict[str, TokenBucket] = {}

#: Called after every request with (host bucket, status or None, seconds);
#: the platform points it at its metrics. Nothing by default.
observe: Any = None


def set_rate(host_key: str, rate: float, burst: int) -> None:
    """Limit a host bucket to ``rate`` requests a second with ``burst``."""
    _BUCKETS[host_key] = TokenBucket(rate, burst)


_SESSIONS: dict[str, requests.Session] = {}
_SESSIONS_LOCK = threading.Lock()


def _session_for(bucket: str) -> requests.Session:
    with _SESSIONS_LOCK:
        session = _SESSIONS.get(bucket)
        if session is None:
            session = requests.Session()
            _SESSIONS[bucket] = session
        return session


def positive_env_float(name: str, default: float) -> float:
    """Read a positive float from the environment, falling back on bad values.

    Args:
        name: Environment variable name.
        default: Returned when the variable is unset, unparseable or
            non-positive; a warning is logged for the latter two.
    """
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning("invalid %s=%r, using default %s", name, raw, default)
        return default
    if value <= 0:
        logger.warning("non-positive %s=%r, using default %s", name, raw, default)
        return default
    return value


def throttled_get(
    url: str,
    *,
    host_key: str,
    min_interval: float,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 15.0,
) -> requests.Response:
    """GET ``url`` after waiting out the per-host minimum interval.

    Args:
        url: Fully-qualified request URL.
        host_key: Throttle and session bucket. All calls sharing a key are
            spaced by ``min_interval`` and reuse one session.
        min_interval: Minimum seconds between consecutive calls to ``host_key``.
        params: Optional query parameters.
        headers: Optional headers merged over the default User-Agent.
        timeout: Per-request socket timeout in seconds.

    Returns:
        The response; the caller decides how to parse it.

    Raises:
        requests.RequestException: Propagated unchanged.
    """
    merged_headers = {"User-Agent": USER_AGENT}
    if headers:
        merged_headers.update(headers)
    _THROTTLE.wait(host_key, min_interval)
    bucket = _BUCKETS.get(host_key)
    if bucket is not None:
        bucket.take()
    session = _session_for(host_key)
    started = time.monotonic()
    status: int | None = None
    try:
        response = session.get(
            url, params=params, headers=merged_headers, timeout=timeout
        )
        status = response.status_code
        return response
    finally:
        if observe is not None:
            observe(host_key, status, time.monotonic() - started)


def throttled_get_json(
    url: str,
    *,
    host_key: str,
    min_interval: float,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 15.0,
) -> Any:
    """Throttled GET that raises on a non-2xx status and decodes the body as JSON."""
    response = throttled_get(
        url,
        host_key=host_key,
        min_interval=min_interval,
        params=params,
        headers=headers,
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()
