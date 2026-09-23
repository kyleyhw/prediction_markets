"""Historical dataset of resolved markets, with a retrievability measurement.

Building the dataset is also the measurement the plan calls for: the archived
project found some closed-market endpoints returning 400 or 404, so whether
resolved markets and their price histories can be fetched at all is recorded
in a :class:`BuildReport` rather than assumed. Every market the discovery
route yields is classified, and every history request that fails is counted
with its error, so a run's report says what the venue actually served.

Layout under the data root::

    markets/<domain>/resolved.parquet    one row per resolved market
    histories/<domain>/<market_id>.parquet  price series of outcome 0
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from vp.domains.base import Domain
from vp.markets.polymarket import PolymarketSource
from vp.markets.schema import BinaryMarket
from vp.markets.store import write_history, write_markets

logger = logging.getLogger(__name__)


@dataclass
class BuildReport:
    """What discovery and history fetching yielded for one domain."""

    domain: str
    markets_seen: int = 0
    resolved_with_label: int = 0
    resolved_void: int = 0
    pending: int = 0
    still_open: int = 0
    histories_fetched: int = 0
    histories_empty: int = 0
    histories_by_bar: dict[int, int] = field(default_factory=dict)
    history_errors: list[tuple[str, str]] = field(default_factory=list)
    markets_path: Path | None = None

    def summary(self) -> str:
        """Human-readable summary, one line per count."""
        lines = [
            f"domain: {self.domain}",
            f"markets seen (closed, in domain): {self.markets_seen}",
            f"resolved with a label: {self.resolved_with_label}",
            f"resolved but void or split (no label): {self.resolved_void}",
            f"closed but pending (no settlement record): {self.pending}",
            f"still open: {self.still_open}",
            f"histories fetched: {self.histories_fetched} "
            f"(empty: {self.histories_empty}, errors: {len(self.history_errors)})",
        ]
        for bar, count in sorted(self.histories_by_bar.items()):
            lines.append(f"  served at {bar}-minute bars: {count}")
        for market_id, error in self.history_errors[:10]:
            lines.append(f"  history error {market_id}: {error}")
        if self.markets_path is not None:
            lines.append(f"written: {self.markets_path}")
        return "\n".join(lines)


def build_resolved_dataset(
    domain: Domain,
    source: PolymarketSource,
    root: Path,
    *,
    max_markets: int | None = None,
    with_history: bool = True,
    history_limit: int | None = None,
    have_history: frozenset[str] = frozenset(),
) -> BuildReport:
    """Discover closed markets in ``domain``, keep the labelled ones, persist.

    Args:
        domain: Domain adapter deciding membership and parsing.
        source: Market source; injectable for tests.
        root: Data root directory.
        max_markets: Stop after this many labelled markets; ``None`` for all.
            A small value is the quick retrievability check.
        with_history: Also fetch and store each labelled market's price
            history for its first outcome.
        history_limit: Fetch histories only for this many markets, those
            that ended most recently; ``None`` for all.
        have_history: Keys of markets whose history is already stored. A
            settled market's history no longer changes, so these are skipped.
    """
    report = BuildReport(domain=domain.name)
    labelled: list[BinaryMarket] = []

    for market in source.discover(domain, closed=True):
        report.markets_seen += 1
        if not market.trading_closed:
            report.still_open += 1
            continue
        if market.resolution_state != "resolved":
            report.pending += 1
            continue
        if market.resolved_outcome is None:
            report.resolved_void += 1
            continue
        report.resolved_with_label += 1
        labelled.append(market)
        if max_markets is not None and len(labelled) >= max_markets:
            break

    markets_path = root / "markets" / domain.name / "resolved.parquet"
    write_markets(markets_path, labelled)
    report.markets_path = markets_path

    if with_history:
        wanted = sorted(labelled, key=lambda m: m.end_date or "", reverse=True)
        if history_limit is not None:
            wanted = wanted[:history_limit]
        for market in wanted:
            key = market.market_id or market.condition_id or "unknown"
            if key in have_history:
                continue
            try:
                series = source.history(market, outcome_index=0)
            except Exception as exc:  # noqa: BLE001 - one failure must not end the run
                report.history_errors.append((key, str(exc)))
                logger.warning("history failed for %s: %s", key, exc)
                continue
            points = series.get("points") or []
            bar = series.get("bar_minutes")
            report.histories_fetched += 1
            if not points:
                report.histories_empty += 1
            elif isinstance(bar, int):
                report.histories_by_bar[bar] = report.histories_by_bar.get(bar, 0) + 1
            write_history(
                root / "histories" / domain.name / f"{key}.parquet",
                market_id=market.market_id,
                clob_token_id=market.outcomes[0].clob_token_id,
                outcome=market.outcomes[0].name,
                points=points,
                bar_minutes=bar if isinstance(bar, int) else None,
            )
    return report
