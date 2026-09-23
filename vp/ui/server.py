"""A local, read-only dashboard over the data root.

``vp ui`` serves one page and a handful of JSON endpoints from the standard
library's HTTP server: no framework, no build step, no dependency, nothing
writable. The page is ``static/index.html`` and renders four views:

* **Overview**: what is on disk per domain (resolved markets by kind,
  snapshots, backtest runs) and the paper accounts.
* **Backtests**: every run's score and bet tables, parsed from its
  ``summary.md``, with its three figures.
* **Paper**: ledger integrity, each forecaster's bankroll and open
  positions, settlements, and the most recent entries.
* **Markets**: the latest snapshot of a domain with quotes and parsed
  fields, and one market's book depth and price across recent snapshots.

The page itself is described in ``docs/interface.md``; ``vp serve`` serves
the same page and the same view behind sign-in.

The server binds to localhost by default. It reads the same files the
commands write and holds no state of its own, so it can be started and
stopped at any time; parquet reads are cached by file modification time.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from collections import Counter, OrderedDict
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import duckdb
import pyarrow.parquet as pq

from vp.domains import DOMAINS as DOMAIN_ADAPTERS
from vp.markets.schema import BinaryMarket
from vp.markets.store import read_markets
from vp.paper.ledger import ChainLedger, Ledger, verify_entries
from vp.paper.loop import replay

logger = logging.getLogger(__name__)
STATIC = Path(__file__).parent / "static"
DOMAINS = tuple(DOMAIN_ADAPTERS)
START_CASH = 1000.0


# Parsed files, keyed by path, loader and modification time, shared by every
# view in the process: the hosted service builds a view per request, and a
# weather snapshot is too large to decode on each. Bounded, because the
# hosted service sees a new capture every few minutes.
_CACHE: OrderedDict[str, tuple[float, Any]] = OrderedDict()
_CACHE_LOCK = threading.Lock()
CACHE_SIZE = 64


class DataView:
    """Read-only queries over a data root, with mtime-keyed caching.

    The hosted service subclasses it (`vp.platform.views.WorkspaceView`) to
    read a workspace's ledger, runs and forecasts from Postgres while the
    shared market files come from the same data root; the methods below it
    overrides are the seams.
    """

    def __init__(self, root: Path) -> None:
        self.root = root

    def _cached(self, path: Path, load: Any) -> Any:
        key = f"{path}#{load.__name__}"
        mtime = path.stat().st_mtime if path.exists() else -1.0
        with _CACHE_LOCK:
            hit = _CACHE.get(key)
            if hit is not None:
                _CACHE.move_to_end(key)
        if hit is None or hit[0] != mtime:
            hit = (mtime, load(path) if path.exists() else None)
            with _CACHE_LOCK:
                _CACHE[key] = hit
                while len(_CACHE) > CACHE_SIZE:
                    _CACHE.popitem(last=False)
        return hit[1]

    # -- the seams --

    def ledger(self) -> ChainLedger:
        """The paper ledger the views read."""
        return Ledger(self.root / "paper" / "ledger.jsonl")

    def start_cash(self) -> float:
        return START_CASH

    def backtest_count(self, domain: str) -> int:
        return len(list((self.root / "backtests" / domain).glob("*/summary.md")))

    def overview(self) -> dict[str, Any]:
        domains: dict[str, Any] = {}
        for domain in DOMAINS:
            resolved = self.root / "markets" / domain / "resolved.parquet"
            counts = self._cached(resolved, _kind_counts)
            snaps = sorted((self.root / "snapshots" / domain).glob("*.parquet"))
            histories = self.root / "histories" / domain
            adapter = DOMAIN_ADAPTERS[domain]
            domains[domain] = {
                "title": adapter.title or domain,
                "summary": adapter.summary,
                "resolved": counts or {},
                "histories": len(list(histories.glob("*.parquet")))
                if histories.exists()
                else 0,
                "snapshots": len(snaps),
                "latest_snapshot": snaps[-1].stem if snaps else None,
                "backtests": self.backtest_count(domain),
            }
        paper = self.paper(limit=0)
        # The summary pages need the number of open positions, not the
        # positions: with thousands open, the list was most of a 1 MB answer.
        paper = paper | {
            "accounts": [
                {k: v for k, v in a.items() if k != "open"} for a in paper["accounts"]
            ]
        }
        return {"root": str(self.root), "domains": domains, "paper": paper}

    def backtests(self) -> list[dict[str, Any]]:
        runs = []
        for summary in sorted(self.root.glob("backtests/*/*/summary.md"), reverse=True):
            run_dir = summary.parent
            text = summary.read_text()
            results = run_dir / "results.json"
            runs.append(
                {
                    "domain": run_dir.parent.name,
                    "stamp": run_dir.name,
                    "results": (
                        json.loads(results.read_text()) if results.exists() else None
                    ),
                    "lines": [
                        ln
                        for ln in text.splitlines()
                        if ln and not ln.startswith(("#", "|"))
                    ],
                    "tables": _tables(text),
                    "figures": sorted(p.name for p in run_dir.glob("*.png")),
                }
            )
        return runs

    def paper(self, *, limit: int = 50, now: datetime | None = None) -> dict[str, Any]:
        entries = list(self.ledger().entries())
        cash = self.start_cash()
        accounts = replay(_Read(entries), cash)
        orders = [e for e in entries if e["kind"] == "order"]
        settlements = [e for e in entries if e["kind"] == "settlement"]
        since = (now or datetime.now(tz=timezone.utc)) - timedelta(hours=24)
        recent = [e for e in entries if _parse_at(e["at"]) >= since]
        return {
            "entries": len(entries),
            "verified": verify_entries(entries) is None if entries else None,
            "last_at": entries[-1]["at"] if entries else None,
            "start_cash": cash,
            "accounts": [
                _account(name, acc, orders, settlements, cash)
                for name, acc in sorted(accounts.items())
            ],
            "today": {
                "since": since.isoformat(timespec="seconds").replace("+00:00", "Z"),
                **Counter(e["kind"] for e in recent),
                "pnl": round(
                    sum(e["data"]["pnl"] for e in recent if e["kind"] == "settlement"),
                    2,
                ),
            },
            "settlements": [s["data"] | {"at": s["at"]} for s in settlements[-limit:]],
            "recent": entries[-limit:] if limit else [],
        }

    def snapshot(self, domain: str) -> dict[str, Any]:
        snaps = sorted((self.root / "snapshots" / domain).glob("*.parquet"))
        if not snaps:
            return {"domain": domain, "stamp": None, "markets": []}
        forecasts = self.latest_forecasts(domain)
        rows = [
            row | {"forecasts": forecasts.get(str(row["market_id"]), [])}
            for row in self._cached(snaps[-1], _snapshot_rows) or []
        ]
        return {"domain": domain, "stamp": snaps[-1].stem, "markets": rows}

    def latest_forecasts(self, domain: str) -> dict[str, list[dict[str, Any]]]:
        """Recent forecasts by market id, as the market list shows them."""
        forecasts: dict[str, list[dict[str, Any]]] = {}
        for f in self.forecasts(limit=5000):
            forecasts.setdefault(str(f.get("market_id")), []).append(
                {
                    "forecaster": f["forecaster"],
                    "p_hat": f["p_hat"],
                    "cutoff": f["cutoff"],
                }
            )
        return forecasts

    def market(
        self, domain: str, market_id: str, *, history: int = 30
    ) -> dict[str, Any] | None:
        """One market from the latest snapshot, with its book and price series.

        The series is the first outcome's price in each of the last
        ``history`` snapshots that carry the market, which is the only price
        history an open market has until the market-data service lands.
        """
        snaps = sorted((self.root / "snapshots" / domain).glob("*.parquet"))
        found = [
            m
            for m in (self._cached(snaps[-1], read_markets) or [] if snaps else [])
            if m.market_id == market_id
        ]
        if not found:
            return None
        market = found[0]
        series = market_series(snaps[-history:], market_id)
        forecasts = [
            {"forecaster": f["forecaster"], "p_hat": f["p_hat"], "cutoff": f["cutoff"]}
            for f in self.forecasts(limit=5000)
            if str(f.get("market_id")) == market_id
        ]
        first = market.outcomes[0]
        return _market_row(market, forecasts) | {
            "event_id": market.event_id,
            "slug": market.slug,
            "status": market.status,
            "spread": market.spread,
            "last_trade_price": market.last_trade_price,
            "volume_usd": market.volume_usd,
            "liquidity_usd": market.liquidity_usd,
            "fetched_at": market.fetched_at,
            "book": {
                "bids": [{"price": b.price, "size": b.size} for b in first.bids],
                "asks": [{"price": a.price, "size": a.size} for a in first.asks],
            },
            "series": series,
        }

    def forecasts(self, *, limit: int = 100) -> list[dict[str, Any]]:
        path = self.root / "paper" / "forecasts.jsonl"
        if not path.exists():
            return []
        lines = path.read_text().splitlines()
        return [json.loads(ln) for ln in lines[-limit:] if ln.strip()][::-1]


def market_series(paths: list[Path], market_id: str) -> list[dict[str, Any]]:
    """The first outcome's price in each snapshot file that carries the market.

    DuckDB reads only the three columns it needs across all the files in
    one scan, where decoding every record of every snapshot would read the
    whole of each (a weather snapshot holds thousands of markets).
    """
    if not paths:
        return []
    rows = duckdb.execute(
        "select fetched_at, outcome_0_price from read_parquet(?) "
        "where market_id = ? and outcome_0_price is not null order by fetched_at",
        [[str(p) for p in paths], market_id],
    ).fetchall()
    return [{"at": at, "p_yes": price} for at, price in rows]


class _Read:
    """Entries already read, so a replay does not read the ledger again."""

    def __init__(self, entries: list[dict[str, Any]]) -> None:
        self._entries = entries

    def entries(self) -> Iterator[dict[str, Any]]:
        return iter(self._entries)


def _parse_at(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _account(
    name: str,
    account: Any,
    orders: list[dict[str, Any]],
    settlements: list[dict[str, Any]],
    cash: float = START_CASH,
) -> dict[str, Any]:
    """One paper account: balance, its curve, fees paid and forward skill."""
    own = [s for s in settlements if s["data"]["forecaster"] == name]
    scored = [s["data"] for s in own if s["data"].get("brier_market") is not None]
    brier = sum(d["brier"] for d in scored) / len(scored) if scored else None
    market = sum(d["brier_market"] for d in scored) / len(scored) if scored else None
    first = next((o["at"] for o in orders if o["data"]["forecaster"] == name), None)
    return {
        "forecaster": name,
        "bankroll": round(account.bankroll, 2),
        "exposure": round(sum(o["stake"] for o in account.open.values()), 2),
        "realised": round(sum(s["data"]["pnl"] for s in own), 2),
        "fees": round(
            sum(
                o["data"].get("fee") or 0.0
                for o in orders
                if o["data"]["forecaster"] == name
            ),
            4,
        ),
        "curve": [cash] + [s["data"]["bankroll_after"] for s in own],
        "curve_at": [first] + [s["at"] for s in own],
        "open": [
            {k: v for k, v in o.items() if k != "forecaster"}
            for o in account.open.values()
        ],
        "open_count": len(account.open),
        "settled": len(own),
        "scored": len(scored),
        "brier": brier,
        "brier_market": market,
        "skill": 1.0 - brier / market if brier is not None and market else None,
    }


def _market_row(
    market: BinaryMarket, forecasts: list[dict[str, Any]]
) -> dict[str, Any]:
    first = market.outcomes[0]
    return {
        "market_id": market.market_id,
        "domain": market.domain,
        "question": market.question,
        "event": market.event_title,
        "outcomes": [o.name for o in market.outcomes],
        "kind": market.parsed.get("kind"),
        "parsed": market.parsed,
        "has_book": bool(first.bids or first.asks),
        "forecasts": forecasts,
        "p_yes": market.p_yes,
        "bid": first.bids[0].price if first.bids else market.best_bid,
        "ask": first.asks[0].price if first.asks else market.best_ask,
        "end_date": market.end_date,
        "fee_rate": market.fee_rate,
        "fee_exponent": market.fee_exponent,
    }


def _snapshot_rows(path: Path) -> list[dict[str, Any]]:
    """A capture's market rows without forecasts, in the list's order."""
    rows = [_market_row(m, []) for m in read_markets(path)]
    rows.sort(key=lambda r: (not r["has_book"], r["end_date"] or ""))
    return rows


def _kind_counts(path: Path) -> dict[str, Any]:
    table = pq.read_table(path, columns=["resolved_outcome", "parsed"])
    labels = table.column("resolved_outcome").to_pylist()
    kinds = Counter(
        dict(p).get("kind", "unparsed") for p in table.column("parsed").to_pylist()
    )
    return {
        "markets": len(labels),
        "positive": sum(1 for y in labels if y == 1),
        "kinds": dict(kinds.most_common()),
    }


def _tables(markdown: str) -> list[list[list[str]]]:
    """Every pipe table in the text as rows of cells, separator rows dropped."""
    tables: list[list[list[str]]] = []
    current: list[list[str]] = []
    for line in markdown.splitlines() + [""]:
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if not all(re.fullmatch(r":?-+:?", c) for c in cells):
                current.append(cells)
        elif current:
            tables.append(current)
            current = []
    return tables


class Handler(SimpleHTTPRequestHandler):
    """Routes ``/api/*`` to the data view and everything else to the page."""

    def __init__(self, *args: Any, view: DataView, **kwargs: Any) -> None:
        self.view = view
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        logger.debug(format, *args)

    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        parts = [p for p in url.path.split("/") if p]
        if not parts or parts[0] != "api":
            # Static assets (the fonts) are served as files; every other
            # non-API path is the single page, whose views live in the hash.
            asset = STATIC.joinpath(*parts) if parts else None
            if not (asset and ".." not in parts and asset.is_file()):
                self.path = "/index.html"
            return super().do_GET()
        query = parse_qs(url.query)
        limit = int(query.get("limit", ["50"])[0])
        try:
            self._api(parts[1:], limit)
        except Exception as exc:  # noqa: BLE001 - report, do not crash the server
            logger.exception("api error")
            self._json({"error": str(exc)}, status=500)

    def _api(self, parts: list[str], limit: int) -> None:
        match parts:
            case ["overview"]:
                self._json(self.view.overview())
            case ["backtests"]:
                self._json(self.view.backtests())
            case ["backtests", domain, stamp, name] if name.endswith(".png"):
                path = self.view.root / "backtests" / domain / stamp / name
                if not path.exists() or ".." in (domain, stamp, name):
                    self.send_error(404)
                    return
                data = path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            case ["paper"]:
                self._json(self.view.paper(limit=limit))
            case ["snapshots", domain] if domain in DOMAINS:
                self._json(self.view.snapshot(domain))
            case ["markets", domain, market_id] if domain in DOMAINS:
                market = self.view.market(domain, market_id)
                if market is None:
                    self.send_error(404)
                    return
                self._json(market)
            case ["forecasts"]:
                self._json(self.view.forecasts(limit=limit))
            case _:
                self.send_error(404)

    def _json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def make_server(
    root: Path, host: str = "127.0.0.1", port: int = 8765
) -> ThreadingHTTPServer:
    """Build the server; ``port=0`` picks a free port (used by tests)."""
    handler = partial(Handler, view=DataView(root))
    return ThreadingHTTPServer((host, port), handler)


def serve(root: Path, host: str = "127.0.0.1", port: int = 8765) -> None:
    """Serve until interrupted."""
    server = make_server(root, host, port)
    print(f"vp ui: http://{host}:{server.server_port}/  (root {root})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
