"""Snapshot collector for markets that are still trading.

Each run discovers the domain's open markets, attaches order-book depth to
every outcome, and writes one Parquet file stamped with the run's UTC time::

    snapshots/<domain>/<YYYYMMDDTHHMMSSZ>.parquet

Runs are append-only: a later run never rewrites an earlier file, so the
directory accumulates a time series of books that later phases use both as
backtest input and as the paper-trading feed.
"""

from __future__ import annotations

import logging
from pathlib import Path

from vp.domains.base import Domain
from vp.markets.polymarket import PolymarketSource
from vp.markets.schema import BinaryMarket, utc_now_iso
from vp.markets.store import write_markets

logger = logging.getLogger(__name__)


def collect_snapshot(
    domain: Domain,
    source: PolymarketSource,
    root: Path,
    *,
    depth: int,
    max_markets: int | None = None,
) -> tuple[Path, int]:
    """Write one snapshot of the domain's open markets with book depth.

    Args:
        domain: Domain adapter.
        source: Market source; injectable for tests.
        root: Data root directory.
        depth: Book levels per side to attach; ``0`` skips the book requests.
        max_markets: Cap on markets per run; ``None`` for all.

    Returns:
        The written path and the number of markets in it.
    """
    stamp = utc_now_iso().replace("-", "").replace(":", "")
    markets: list[BinaryMarket] = []
    for market in source.discover(domain, closed=False):
        if depth > 0:
            try:
                market = source.with_books(market, depth=depth)
            except Exception as exc:  # noqa: BLE001 - keep the quote without its book
                logger.warning("book failed for %s: %s", market.market_id, exc)
        markets.append(market)
        if max_markets is not None and len(markets) >= max_markets:
            break
    path = root / "snapshots" / domain.name / f"{stamp}.parquet"
    write_markets(path, markets)
    return path, len(markets)
