"""The static demo's data: what a page with no server needs (docs/demo.md).

The demo runs on GitHub Pages: no database, no worker, no key of the
owner's. So everything that needs the engine's evidence is computed here,
ahead of time, by a scheduled GitHub Action, and the page does the rest:

* for every resolved market with a price history, the market's price and
  each statistical forecaster's probability at a few fixed cutoffs
  (``CUTOFFS``, hours before it settled), with its label, kind, parsed
  fields and fee; the page's backtest selects, sizes and settles from
  these exactly as :mod:`vp.strategy.run` and :mod:`vp.backtest.simulate`
  do (the parity tests run both on the same inputs);
* the compiler's instructions, context and answer schema
  (:mod:`vp.strategy.compiler`), so the page asks the visitor's own model
  the same question the platform asks its model;
* the words the page shows a spec in (:func:`vp.strategy.spec.render`
  ported, with its tables exported from here).

Forecasts are made through the same cutoff-bounded ``Evidence`` the
backtest uses, so nothing the page shows was computed with hindsight.
"""

from __future__ import annotations

import json
import shutil
import time
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from vp.backtest.run import BacktestConfig
from vp.domains import DOMAINS
from vp.domains.props import PROP_KINDS
from vp.forecast import Evidence, forecaster_names, make_forecaster
from vp.forecast.evidence import settled_at
from vp.llm.providers import PROVIDERS
from vp.markets.store import read_markets
from vp.strategy import compiler
from vp.strategy.run import ASSUMED_FEE_RATE
from vp.strategy.spec import (
    _LIMIT_NAMES,
    FORECASTER_NAMES_PLAIN,
    KIND_NAMES,
    Caps,
    Spec,
    plain_name,
)

#: Hours before settlement at which prices and forecasts are exported; a
#: spec's ``hours_before_close`` is run at the nearest one, and the page
#: says so.
CUTOFFS = (1, 6, 24, 72, 168)
#: The page's own files, copied beside the data.
STATIC = Path(__file__).resolve().parent.parent / "pages"
FONTS = Path(__file__).resolve().parent / "ui" / "static" / "fonts"
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def beliefs() -> list[str]:
    """The beliefs the demo can backtest: every forecaster and signal that
    needs no model (the visitor's model writes the strategy; forecasting
    hundreds of markets with it is for their own copy)."""
    return [n for n in forecaster_names() if n not in ("market", "llm")]


def export_domain(
    root: Path, domain: str, names: Iterable[str] | None = None
) -> dict[str, Any]:
    """Every scorable market of a domain, with prices and forecasts by cutoff."""
    resolved = read_markets(root / "markets" / domain / "resolved.parquet")
    labelled = [
        m
        for m in resolved
        if m.resolved_outcome is not None and settled_at(m) is not None
    ]
    labelled.sort(key=lambda m: settled_at(m) or _EPOCH)
    forecasters = [(n, make_forecaster(n, domain)) for n in (names or beliefs())]
    base = Evidence(_EPOCH, root, markets={domain: resolved})
    rows = []
    for m in labelled:
        when = settled_at(m)
        assert when is not None
        prices: dict[str, float] = {}
        beliefs_at: dict[str, dict[str, float]] = {}
        for hours in CUTOFFS:
            ev = base.at(when - timedelta(hours=hours))
            q = ev.price_at(m)
            if q is None:
                continue
            prices[str(hours)] = q
            for name, f in forecasters:
                answer = f.forecast(m, ev)
                if answer is not None:
                    beliefs_at.setdefault(name, {})[str(hours)] = answer.p_hat
        if not prices:
            continue
        rows.append(
            {
                "id": m.market_id or "",
                "q": m.question,
                "kind": m.parsed.get("kind"),
                "fields": {
                    k: v for k, v in m.parsed.items() if k != "kind" and v is not None
                },
                "event": m.event_id,
                "settled": when.isoformat(),
                "y": int(m.resolved_outcome or 0),
                "fee": None if m.fee_rate is None else [m.fee_rate, m.fee_exponent],
                "price": prices,
                "f": beliefs_at,
            }
        )
    return {"domain": domain, "cutoffs": list(CUTOFFS), "markets": rows}


def _inline(schema: dict[str, Any]) -> dict[str, Any]:
    """The schema with every ``$ref`` replaced by its definition."""
    defs = schema.get("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, list):
            return [walk(n) for n in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            return walk(defs[node["$ref"].rsplit("/", 1)[-1]])
        return {k: walk(v) for k, v in node.items() if k != "$defs"}

    return walk(schema)


def context(domains: Iterable[str]) -> dict[str, Any]:
    """The compiler's prompt and schemas and the page's tables."""
    names = beliefs()
    available = {d: DOMAINS[d] for d in domains}
    system = (
        compiler.SYSTEM
        + "\n"
        + compiler._context(available, ["market", *names], Caps(), [], None, {})
        + "\n\nIn this demo a backtest runs at one of "
        + ", ".join(f"{h}" for h in CUTOFFS)
        + " hours before a market settled: set schedule.hours_before_close"
        " to one of these."
    )
    caps = Caps()
    return {
        "system": system,
        "schema": _inline(compiler.SCHEMA),
        "spec_schema": _inline(Spec.model_json_schema()),
        "cutoffs": list(CUTOFFS),
        "caps": {
            "kelly_fraction": caps.kelly_fraction,
            "max_fraction": caps.max_fraction,
            "flat_fraction": caps.flat_fraction,
            "min_edge": caps.min_edge,
        },
        "limit_names": _LIMIT_NAMES,
        "kind_names": KIND_NAMES,
        "beliefs": {n: plain_name(n) for n in names}
        | {"market": FORECASTER_NAMES_PLAIN["market"]},
        "domains": {
            name: {
                "title": d.title,
                "summary": d.summary,
                "kinds": {k: list(v) for k, v in d.kinds.items()},
                "all_kinds": {k: list(v) for k, v in d.all_kinds.items()},
            }
            for name, d in available.items()
        },
        "props": sorted(PROP_KINDS),
        # Every provider a browser can call itself (a program cannot be).
        "providers": [
            {
                "id": p.id,
                "title": p.label,
                "kind": p.kind,
                "base_url": p.base_url,
                "needs_key": p.needs_key,
            }
            for p in PROVIDERS.values()
            if p.kind != "command"
        ],
        "fee_rate_assumed": ASSUMED_FEE_RATE,
        "half_spread": BacktestConfig("any").half_spread,
    }


def build(root: Path, out: Path, domains: Iterable[str] | None = None) -> dict:
    """Write the page and its data into ``out``; returns what was written."""
    started = time.monotonic()
    out.mkdir(parents=True, exist_ok=True)
    shutil.copytree(STATIC, out, dirs_exist_ok=True)
    shutil.copytree(FONTS, out / "fonts", dirs_exist_ok=True)
    (out / "data").mkdir(exist_ok=True)
    wanted = list(domains or DOMAINS)
    present = [
        d for d in wanted if (root / "markets" / d / "resolved.parquet").exists()
    ]
    counts = {}
    for domain in present:
        data = export_domain(root, domain)
        counts[domain] = len(data["markets"])
        (out / "data" / f"{domain}.json").write_text(
            json.dumps(data, separators=(",", ":"))
        )
    built = datetime.now(timezone.utc).isoformat(timespec="seconds")
    (out / "data" / "demo.json").write_text(
        json.dumps(context(present) | {"built": built, "markets": counts})
    )
    return {"markets": counts, "seconds": round(time.monotonic() - started, 1)}
