"""Metrics and traces for the web service, the workers and the ingest service.

Metrics are Prometheus counters, gauges and histograms in one registry per
process. The web serves them at `/metrics` behind the metrics token; a
worker and the ingest service serve them on their own port. What is
measured is what the objectives and the report need (plan, task 36):

* requests: count and latency by route and status;
* jobs: how many finished by kind and outcome, how long they took, and the
  queue's depth and oldest age by kind (read from `vp_queue_stats`, which
  returns counts only);
* the venue: requests, latency and status by host, so a 429 is visible;
* the market feed: reconnects, tokens tracked, and the age of the books
  (the quote-freshness objective is the 99th percentile under 60 s);
* resolutions: the delay between the venue resolving and us recording it;
* money: model spend by forecaster;
* the ledger: append latency.

Traces use OpenTelemetry: one span per request, per job and per venue
call, exported to the log, to an OTLP collector, or nowhere
(`VP_TELEMETRY`). Tracing is off unless configured.
"""

from __future__ import annotations

import contextlib
import logging
import os
import time
from collections.abc import Iterator
from typing import Any

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    start_http_server,
)

from vp.platform.config import Settings, Telemetry

logger = logging.getLogger(__name__)

REGISTRY = CollectorRegistry()

HTTP_REQUESTS = Counter(
    "vp_http_requests",
    "Requests served",
    ["route", "method", "status"],
    registry=REGISTRY,
)
HTTP_SECONDS = Histogram(
    "vp_http_seconds",
    "Request latency",
    ["route"],
    registry=REGISTRY,
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
)
JOBS_FINISHED = Counter(
    "vp_jobs_finished", "Jobs finished", ["kind", "outcome"], registry=REGISTRY
)
JOB_SECONDS = Histogram(
    "vp_job_seconds",
    "Job run time",
    ["kind"],
    registry=REGISTRY,
    buckets=(0.1, 0.5, 1, 5, 15, 60, 300, 900, 3600),
)
JOB_START_SECONDS = Histogram(
    "vp_job_start_seconds",
    "Time from queued to started",
    ["kind"],
    registry=REGISTRY,
    buckets=(0.01, 0.05, 0.1, 0.5, 1, 5, 15, 60, 300),
)
QUEUE_DEPTH = Gauge(
    "vp_queue_depth", "Jobs by kind and state", ["kind", "state"], registry=REGISTRY
)
QUEUE_OLDEST = Gauge(
    "vp_queue_oldest_seconds",
    "Age of the oldest queued job",
    ["kind"],
    registry=REGISTRY,
)
VENUE_REQUESTS = Counter(
    "vp_venue_requests", "Venue requests", ["host", "status"], registry=REGISTRY
)
VENUE_SECONDS = Histogram(
    "vp_venue_seconds", "Venue request latency", ["host"], registry=REGISTRY
)
WS_RECONNECTS = Counter(
    "vp_ws_reconnects", "Market channel reconnects", registry=REGISTRY
)
TOKENS_TRACKED = Gauge("vp_tokens_tracked", "Tokens subscribed", registry=REGISTRY)
QUOTE_AGE_P99 = Gauge(
    "vp_quote_age_p99_seconds", "99th percentile age of the books", registry=REGISTRY
)
QUOTE_AGE_MAX = Gauge("vp_quote_age_max_seconds", "Oldest book", registry=REGISTRY)
INGEST_LAG = Histogram(
    "vp_ingest_lag_seconds",
    "Venue event timestamp to our receipt",
    registry=REGISTRY,
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30),
)
RESOLUTION_DELAY = Histogram(
    "vp_resolution_delay_seconds",
    "Venue resolution to our record",
    registry=REGISTRY,
    buckets=(60, 300, 900, 1800, 3600, 7200, 21600, 86400),
)
SPEND_USD = Counter(
    "vp_spend_usd", "Model spend charged", ["forecaster"], registry=REGISTRY
)
LEDGER_APPEND_SECONDS = Histogram(
    "vp_ledger_append_seconds",
    "Ledger append latency",
    registry=REGISTRY,
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.5),
)
ERRORS = Counter("vp_errors", "Unhandled errors", ["component"], registry=REGISTRY)


def exposition() -> bytes:
    """The registry in Prometheus text format; under `vp serve --workers`,
    every web process's metrics added together."""
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        from prometheus_client import multiprocess

        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        return generate_latest(registry)
    return generate_latest(REGISTRY)


def serve_metrics(port: int) -> None:
    """Serve this process's metrics on a port (workers, ingest)."""
    start_http_server(port, registry=REGISTRY)


# ------------------------------------------------------------------- hooks


def job_finished(job: Any, outcome: str, seconds: float) -> None:
    JOBS_FINISHED.labels(job.kind, outcome).inc()
    if job.attempts == 1:
        JOB_START_SECONDS.labels(job.kind).observe(job.waited_seconds)
    JOB_SECONDS.labels(job.kind).observe(seconds)


def venue_call(host: str, status: int | None, seconds: float) -> None:
    VENUE_REQUESTS.labels(host, str(status) if status else "error").inc()
    VENUE_SECONDS.labels(host).observe(seconds)


class FeedMetrics:
    """What the ingest service reports about the market channel."""

    def reconnect(self) -> None:
        WS_RECONNECTS.inc()

    def lag(self, seconds: float) -> None:
        INGEST_LAG.observe(max(seconds, 0.0))

    def freshness(self, ages: list[float], tokens: int) -> None:
        TOKENS_TRACKED.set(tokens)
        if not ages:
            return
        ordered = sorted(ages)
        QUOTE_AGE_P99.set(ordered[min(len(ordered) - 1, int(0.99 * len(ordered)))])
        QUOTE_AGE_MAX.set(ordered[-1])


def refresh_queue(pool: Any) -> None:
    """Read the queue's depth and oldest age into the gauges."""
    with pool.connection() as conn:
        rows = conn.execute("select * from vp_queue_stats()").fetchall()
    QUEUE_DEPTH.clear()
    QUEUE_OLDEST.clear()
    for kind, state, count, oldest in rows:
        QUEUE_DEPTH.labels(kind, state).set(count)
        if state == "queued" and oldest is not None:
            QUEUE_OLDEST.labels(kind).set(oldest)


# ------------------------------------------------------------------ traces

_tracer: Any = None


def setup_telemetry(settings: Settings, service: str) -> None:
    """Configure tracing for this process as the settings say, and hook the
    venue client's calls into the metrics."""
    global _tracer
    from vp.venues import _http

    _http.observe = venue_call
    if settings.telemetry is Telemetry.NONE:
        return
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import (
        BatchSpanProcessor,
        ConsoleSpanExporter,
        SpanExporter,
    )

    exporter: SpanExporter
    if settings.telemetry is Telemetry.OTLP:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )

        exporter = OTLPSpanExporter(endpoint=settings.otlp_endpoint)
    else:
        exporter = ConsoleSpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": service}))
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer("vibe-predict")


@contextlib.contextmanager
def span(name: str, **attributes: Any) -> Iterator[None]:
    """A trace span when tracing is on; nothing when it is off."""
    if _tracer is None:
        yield
        return
    with _tracer.start_as_current_span(name, attributes=attributes):
        yield


@contextlib.contextmanager
def timed(histogram: Histogram) -> Iterator[None]:
    started = time.monotonic()
    try:
        yield
    finally:
        histogram.observe(time.monotonic() - started)
