"""Command-line entry point for vibe-predict.

Subcommands:

* ``vp build-dataset``: discover closed markets in a domain, keep those with
  a settlement label, store them and their price histories, and print the
  retrievability report. Run it with ``--max-markets`` for a quick check.
* ``vp snapshot``: write one snapshot of a domain's open markets with book
  depth.
* ``vp backtest``: forecast every resolved market of a domain at a cutoff,
  score against the market, simulate bets, and write a report directory.
"""

from __future__ import annotations

import argparse
import logging
from importlib.metadata import version
from pathlib import Path

from vp.backtest.run import BacktestConfig, run_backtest
from vp.domains import DOMAINS
from vp.forecast import FORECASTER_NAMES
from vp.markets.dataset import build_resolved_dataset
from vp.markets.polymarket import PolymarketSource
from vp.markets.schema import utc_now_iso
from vp.markets.snapshot import collect_snapshot


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--domain",
        required=True,
        choices=sorted(DOMAINS),
        nargs="+",
        help="one or more domains to process",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("data"),
        help="data root directory (default: data/)",
    )
    parser.add_argument(
        "--max-markets",
        type=int,
        default=None,
        help="stop after this many markets per domain (default: all)",
    )


def main() -> None:
    """Parse arguments and dispatch."""
    parser = argparse.ArgumentParser(
        prog="vp",
        description="vibe-predict: LLM forecasting of Polymarket binary contracts.",
    )
    parser.add_argument(
        "--version", action="version", version=f"vp {version('vibe-predict')}"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser(
        "build-dataset", help="store resolved markets and their price histories"
    )
    _add_common(build)
    build.add_argument(
        "--no-history", action="store_true", help="skip the price-history requests"
    )

    snap = sub.add_parser("snapshot", help="write one snapshot of open markets")
    _add_common(snap)
    snap.add_argument(
        "--depth", type=int, default=5, help="book levels per side (default: 5)"
    )

    back = sub.add_parser("backtest", help="score forecasters on resolved markets")
    back.add_argument("--domain", required=True, choices=sorted(DOMAINS))
    back.add_argument("--root", type=Path, default=Path("data"))
    back.add_argument(
        "--forecasters",
        nargs="+",
        default=["market", "constant"],
        choices=FORECASTER_NAMES,
        help="forecasters to run; market is the reference (default: market constant)",
    )
    back.add_argument(
        "--hours-before-close",
        type=float,
        default=24.0,
        help="cutoff this many hours before settlement (default: 24)",
    )
    back.add_argument(
        "--kinds", nargs="*", default=[], help="parsed kinds to include (default: all)"
    )
    back.add_argument("--max-markets", type=int, default=None)
    back.add_argument("--seed", type=int, default=0)
    back.add_argument("--fee-rate", type=float, default=0.0)
    back.add_argument("--half-spread", type=float, default=0.01)
    back.add_argument(
        "--out", type=Path, default=None, help="report directory (default: under root)"
    )

    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    if args.command == "backtest":
        config = BacktestConfig(
            domain=args.domain,
            forecasters=tuple(args.forecasters),
            hours_before_close=args.hours_before_close,
            kinds=tuple(args.kinds),
            max_markets=args.max_markets,
            seed=args.seed,
            fee_rate=args.fee_rate,
            half_spread=args.half_spread,
        )
        stamp = utc_now_iso().replace("-", "").replace(":", "")
        out = args.out or args.root / "backtests" / args.domain / stamp
        run_backtest(config, args.root, out)
        print((out / "summary.md").read_text())
        print(f"written: {out}")
        return

    source = PolymarketSource()

    for name in args.domain:
        domain = DOMAINS[name]
        if args.command == "build-dataset":
            report = build_resolved_dataset(
                domain,
                source,
                args.root,
                max_markets=args.max_markets,
                with_history=not args.no_history,
            )
            print(report.summary())
        else:
            path, count = collect_snapshot(
                domain,
                source,
                args.root,
                depth=args.depth,
                max_markets=args.max_markets,
            )
            print(f"{name}: {count} markets written to {path}")
