"""Entry points for the platform's processes and the operator's commands.

One image, three processes: `vp serve` (the web service), `vp worker` (a
pool of job runners for some kinds of job) and `vp ingest` (the
market-data service). `vp db migrate` applies migrations, and `vp jobs` and
`vp admin` are the operator's. The command-line module imports this lazily,
inside those commands, so the engine's commands never load the platform.
"""

from __future__ import annotations

import logging
import signal
import threading

import uvicorn
from psycopg_pool import ConnectionPool

from vp.platform.config import ConfigError, Settings, load_settings
from vp.platform.db import connect, migrate
from vp.platform.web import create_app, install_log_redaction

logger = logging.getLogger(__name__)


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


def open_pool(settings: Settings, size: int = 4) -> ConnectionPool:
    """A pool of `vp_app` connections in autocommit mode (see `vp.platform.db`)."""
    return ConnectionPool(
        settings.database_url,
        min_size=1,
        max_size=size,
        kwargs={"autocommit": True},
        open=True,
    )


def build_services(settings: Settings, pool: ConnectionPool):  # noqa: ANN201
    """The handlers' services for this process: storage, the cache, the source."""
    from vp.platform.handlers import Services
    from vp.platform.storage import SharedRoot, open_store

    store = open_store(settings)
    work = settings.cache / "jobs"
    work.mkdir(parents=True, exist_ok=True)

    def notify(channel: str, payload: str) -> None:
        with pool.connection() as conn:
            conn.execute("select pg_notify(%s, %s)", (channel, payload))

    return Services(
        settings=settings,
        pool=pool,
        store=store,
        shared=SharedRoot(store, settings.cache),
        notify=notify,
        work_dir=work,
    )


def work(kinds: list[str] | None, concurrency: int, metrics_port: int | None) -> None:
    """Run a worker pool until interrupted."""
    from vp.platform import jobs
    from vp.platform.handlers import handlers
    from vp.platform.observe import (
        job_finished,
        refresh_queue,
        serve_metrics,
        setup_telemetry,
    )

    settings = load_settings()
    setup_telemetry(settings, "vp-worker")
    _venue_rates()
    if metrics_port:
        serve_metrics(metrics_port)
    pool = open_pool(settings, size=concurrency + 3)
    table = handlers(_extra_handlers())
    chosen = tuple(kinds or sorted(table))
    worker = jobs.Worker(
        pool,
        table,
        chosen,
        services=build_services(settings, pool),
        concurrency=concurrency,
        listen_url=settings.database_url,
        on_job=job_finished,
    )
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    if "scheduler" in chosen:
        _keep_scheduler(pool, stop)

    def gauges() -> None:
        while not stop.wait(15):
            try:
                refresh_queue(pool)
            except Exception:  # noqa: BLE001 - a missed reading is harmless
                logger.exception("queue gauges")

    threading.Thread(target=gauges, daemon=True).start()
    print(f"vp worker: {', '.join(chosen)} x{concurrency} as {worker.name}")
    worker.run(stop)


def _keep_scheduler(pool: ConnectionPool, stop: threading.Event) -> None:
    """Queue the scheduler for the next minute, every minute, from this process.

    The scheduler re-queues itself; this is the safety net for the minute
    after one dies, and what starts it on a fresh database.
    """
    from vp.platform import jobs

    def loop() -> None:
        while not stop.is_set():
            try:
                jobs.ensure_scheduler(pool)
            except Exception:  # noqa: BLE001 - try again next minute
                logger.exception("could not queue the scheduler")
            stop.wait(60)

    threading.Thread(target=loop, daemon=True).start()


def _extra_handlers() -> dict:
    """Handlers that live with their services (ingest, evidence)."""
    from vp.platform.evidence import collect_evidence
    from vp.platform.ingest import reconcile

    return {"reconcile": reconcile, "evidence": collect_evidence}


def owner_connection():  # noqa: ANN201
    """The operator's connection, as the owner."""
    settings = load_settings()
    if not settings.migration_database_url:
        raise ConfigError("VP_MIGRATION_DATABASE_URL is required for operator commands")
    return connect(settings.migration_database_url)


# Measured request rates the venue tolerates are recorded in the Phase 13
# report; these are set below them, per host, for every platform process.
VENUE_RATES = {
    "polymarket_gamma": (10.0, 20),
    "polymarket_clob": (20.0, 40),
    "polymarket_data": (10.0, 20),
}


def _venue_rates() -> None:
    from vp.venues._http import set_rate

    for host, (rate, burst) in VENUE_RATES.items():
        set_rate(host, rate, burst)


def ingest(
    domains: list[str] | None,
    metrics_port: int | None,
    snapshot_minutes: float,
    discover_minutes: float,
) -> None:
    """Run the market-data service until interrupted."""
    import asyncio

    from vp.domains import DOMAINS
    from vp.platform.ingest import Ingest
    from vp.platform.observe import FeedMetrics, serve_metrics, setup_telemetry
    from vp.platform.storage import open_store

    settings = load_settings()
    setup_telemetry(settings, "vp-ingest")
    _venue_rates()
    if metrics_port:
        serve_metrics(metrics_port)
    pool = open_pool(settings, size=4)
    service = Ingest(
        pool,
        open_store(settings),
        domains or list(DOMAINS),
        snapshot_seconds=snapshot_minutes * 60,
        discover_seconds=discover_minutes * 60,
        metrics=FeedMetrics(),
    )

    async def main() -> None:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
        await service.run(stop)

    print(f"vp ingest: {', '.join(service.domains)}")
    asyncio.run(main())
