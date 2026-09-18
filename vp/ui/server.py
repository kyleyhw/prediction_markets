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
  fields.

The server binds to localhost by default. It reads the same files the
commands write and holds no state of its own, so it can be started and
stopped at any time; parquet reads are cached by file modification time.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pyarrow.parquet as pq

from vp.markets.store import read_markets
from vp.paper.ledger import Ledger
from vp.paper.loop import replay

logger = logging.getLogger(__name__)
STATIC = Path(__file__).parent / "static"
DOMAINS = ("cs2", "weather", "epl")


class DataView:
    """Read-only queries over a data root, with mtime-keyed caching."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._cache: dict[str, tuple[float, Any]] = {}

    def _cached(self, path: Path, load: Any) -> Any:
        key = str(path)
        mtime = path.stat().st_mtime if path.exists() else -1.0
        hit = self._cache.get(key)
        if hit is None or hit[0] != mtime:
            self._cache[key] = (mtime, load(path) if path.exists() else None)
        return self._cache[key][1]

    def overview(self) -> dict[str, Any]:
        domains: dict[str, Any] = {}
        for domain in DOMAINS:
            resolved = self.root / "markets" / domain / "resolved.parquet"
            counts = self._cached(resolved, _kind_counts)
            snaps = sorted((self.root / "snapshots" / domain).glob("*.parquet"))
            histories = self.root / "histories" / domain
            domains[domain] = {
                "resolved": counts or {},
                "histories": len(list(histories.glob("*.parquet")))
                if histories.exists()
                else 0,
                "snapshots": len(snaps),
                "latest_snapshot": snaps[-1].stem if snaps else None,
                "backtests": len(
                    list((self.root / "backtests" / domain).glob("*/summary.md"))
                ),
            }
        return {
            "root": str(self.root),
            "domains": domains,
            "paper": self.paper(limit=0),
        }

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

    def paper(self, *, limit: int = 50) -> dict[str, Any]:
        ledger = Ledger(self.root / "paper" / "ledger.jsonl")
        entries = list(ledger.entries())
        accounts = replay(ledger, 1000.0)
        settlements = [e for e in entries if e["kind"] == "settlement"]
        return {
            "entries": len(entries),
            "verified": ledger.verify() is None if entries else None,
            "last_at": entries[-1]["at"] if entries else None,
            "accounts": [
                {
                    "forecaster": name,
                    "bankroll": round(acc.bankroll, 2),
                    "exposure": round(sum(o["stake"] for o in acc.open.values()), 2),
                    "realised": round(
                        sum(
                            s["data"]["pnl"]
                            for s in settlements
                            if s["data"]["forecaster"] == name
                        ),
                        2,
                    ),
                    "curve": [1000.0]
                    + [
                        s["data"]["bankroll_after"]
                        for s in settlements
                        if s["data"]["forecaster"] == name
                    ],
                    "open": [
                        {k: v for k, v in o.items() if k != "forecaster"}
                        for o in acc.open.values()
                    ],
                    "settled": sum(
                        1 for s in settlements if s["data"]["forecaster"] == name
                    ),
                }
                for name, acc in sorted(accounts.items())
            ],
            "settlements": [s["data"] | {"at": s["at"]} for s in settlements[-limit:]],
            "recent": entries[-limit:] if limit else [],
        }

    def snapshot(self, domain: str) -> dict[str, Any]:
        snaps = sorted((self.root / "snapshots" / domain).glob("*.parquet"))
        if not snaps:
            return {"domain": domain, "stamp": None, "markets": []}
        markets = self._cached(snaps[-1], read_markets) or []
        forecasts: dict[str, list[dict[str, Any]]] = {}
        for f in self.forecasts(limit=5000):
            forecasts.setdefault(str(f.get("market_id")), []).append(
                {
                    "forecaster": f["forecaster"],
                    "p_hat": f["p_hat"],
                    "cutoff": f["cutoff"],
                }
            )
        rows = [
            {
                "market_id": m.market_id,
                "question": m.question,
                "event": m.event_title,
                "kind": m.parsed.get("kind"),
                "parsed": m.parsed,
                "has_book": bool(m.outcomes[0].bids or m.outcomes[0].asks),
                "forecasts": forecasts.get(str(m.market_id), []),
                "p_yes": m.p_yes,
                "bid": m.outcomes[0].bids[0].price
                if m.outcomes[0].bids
                else m.best_bid,
                "ask": m.outcomes[0].asks[0].price
                if m.outcomes[0].asks
                else m.best_ask,
                "end_date": m.end_date,
            }
            for m in markets
        ]
        rows.sort(key=lambda r: (not r["has_book"], r["end_date"] or ""))
        return {"domain": domain, "stamp": snaps[-1].stem, "markets": rows}

    def forecasts(self, *, limit: int = 100) -> list[dict[str, Any]]:
        path = self.root / "paper" / "forecasts.jsonl"
        if not path.exists():
            return []
        lines = path.read_text().splitlines()
        return [json.loads(ln) for ln in lines[-limit:] if ln.strip()][::-1]


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
