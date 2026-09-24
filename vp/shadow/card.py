"""The shadow report card: a record, its diagnostics, its rules and the
counterfactual, with peer context (docs/shadow.md, task 96).

The card is plain data (JSON), rendered by the page in either reading level
and exported as it is. Nothing here writes to the venue; the network is
reached only through the functions passed in.
"""

from __future__ import annotations

import random
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from vp.domains import DOMAINS, Domain
from vp.markets.schema import BinaryMarket
from vp.markets.store import read_history, read_markets
from vp.shadow import counterfactual, diagnostics, record, rules
from vp.strategy.spec import Spec

CARD_VERSION = 1
Fetch = Callable[[str], Any]


def _epoch(text: str) -> float:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()


def load_markets(root: Path, domains: Iterable[str]) -> dict[str, BinaryMarket]:
    """Our datasets' resolved markets, by condition id."""
    out: dict[str, BinaryMarket] = {}
    for d in domains:
        path = root / "markets" / d / "resolved.parquet"
        if path.exists():
            out.update(
                {m.condition_id: m for m in read_markets(path) if m.condition_id}
            )
    return out


def negatives(
    root: Path,
    domain: str,
    markets: Mapping[str, BinaryMarket],
    since: datetime,
    until: datetime,
    exclude: set[str],
    history: Callable[[str], record.Series] | None = None,
    sample: int = 200,
) -> tuple[list[rules.Market], float]:
    """The domain's markets closing in the window that the person did not
    bet, priced from their histories, and how many markets each stands for.

    Local histories are used where the dataset has them; when fewer than
    ``sample`` fall in the window, a seeded sample of the rest is priced
    through ``history`` (the venue)."""
    window = []
    for m in markets.values():
        closed = record._closed(m)
        if m.domain == domain and closed and since <= closed <= until:
            window.append((m, closed))
    out = []
    candidates = [
        (m, c) for m, c in window if m.condition_id not in exclude and m.market_id
    ]
    local = [
        (m, c)
        for m, c in candidates
        if (root / "histories" / domain / f"{m.market_id}.parquet").exists()
    ]
    chosen = list(local)
    if history is not None and len(local) < sample:
        rest = sorted(
            ((m, c) for m, c in candidates if (m, c) not in local),
            key=lambda mc: str(mc[0].market_id),
        )
        random.Random(0).shuffle(rest)
        chosen += rest[: sample - len(local)]
    for m, closed in chosen:
        path = root / "histories" / domain / f"{m.market_id}.parquet"
        if path.exists():
            series = [
                (_epoch(r["timestamp"]), float(r["implied_probability"]))
                for r in read_history(path)
                if r.get("implied_probability") is not None
            ]
        else:
            token = m.outcomes[0].clob_token_id
            try:
                series = history(token) if history and token else []
            except Exception:  # noqa: BLE001 - an unpriced market is skipped
                series = []
        if not series:
            continue
        out.append(
            rules.Market(
                m.market_id or "",
                m.parsed.get("kind") or "",
                dict(m.parsed),
                closed,
                series,
                None if m.resolved_outcome is None else m.resolved_outcome == 1,
            )
        )
    kept = len(window) - sum(1 for m, _ in window if m.condition_id in exclude)
    return out, (kept / len(out) if out else 0.0)


def peer(
    card_return: float | None, staked: float, board: list[dict[str, Any]], category: str
) -> dict[str, Any] | None:
    """Where the record's profit per dollar traded sits among the venue's
    listed addresses, anonymised to a percentile."""
    ratios = sorted(r["pnl"] / r["volume"] for r in board if r.get("volume"))
    if not ratios or card_return is None:
        return None
    below = sum(1 for x in ratios if x < card_return)
    return {
        "category": category,
        "listed": len(ratios),
        "percentile": below / len(ratios),
        "median_listed": ratios[len(ratios) // 2],
        "yours": card_return,
        "caveats": [
            "The list shows the top addresses only: survivorship by construction.",
            "Its profit is all-time and gross of fees; its volume includes "
            "market making.",
            f"Your figure is profit per dollar staked on {staked:,.0f} USD of "
            "scored bets.",
        ],
    }


def analyse(
    address: str,
    activity: Iterable[Mapping[str, Any]],
    root: Path,
    *,
    resolve: Fetch,
    history: Callable[[str], record.Series],
    leaderboard: Callable[[str], list[dict[str, Any]]] | None = None,
    pnl: Callable[[str], list[dict[str, float]]] | None = None,
    cap: int = 50_000,
    max_histories: int = 300,
    proposed: Mapping[str, list[Spec]] | None = None,
    domains: Mapping[str, Domain] = DOMAINS,
    progress: Callable[[float, str], None] | None = None,
) -> dict[str, Any]:
    """The whole card for one address."""
    rec = record.build(address, activity, cap)
    markets = load_markets(root, domains)
    counts = record.attach(
        rec,
        markets,
        resolve,
        history,
        max_histories=max_histories,
        progress=(lambda f, m: progress(0.1 + 0.7 * f, m)) if progress else None,
    )
    bets = rec.bets
    out: dict[str, Any] = {
        "version": CARD_VERSION,
        "address": rec.address,
        "generated_at": datetime.now(tz=UTC).isoformat(timespec="seconds"),
        "record": {
            **counts,
            "events": rec.events,
            "set_aside": len(rec.set_aside),
            "first_at": rec.first_at.isoformat() if rec.first_at else None,
            "last_at": rec.last_at.isoformat() if rec.last_at else None,
            "truncated": rec.truncated,
        },
        "diagnostics": diagnostics.diagnose(bets),
        "rules": {},
        "counterfactual": {},
        "model": "not used" if not proposed else "proposed rules",
    }
    if progress:
        progress(0.85, "rules")
    by_domain = Counter(b.domain for b in bets if b.domain and b.scored)
    for domain, _ in by_domain.most_common():
        mine = [b for b in bets if b.domain == domain]
        times = [b.first_at for b in mine]
        closes = [b.closed_at for b in mine if b.closed_at]
        negs, weight = negatives(
            root,
            domain,
            markets,
            min(times),
            max(closes + times),
            {b.condition_id for b in mine},
            history=history,
        )
        found = rules.extract(
            domain,
            mine,
            negs,
            weight,
            proposed=(proposed or {}).get(domain, []),
            name=f"Rule version of {rec.address[:8]}",
        )
        out["rules"][domain] = found
        best = next((r for r in found["rules"] if r["validated"]), None)
        if best is not None:
            rule = rules.Rule(**best["rule"])
            out["counterfactual"][domain] = counterfactual.compare(mine, negs, rule)
    main = by_domain.most_common(1)
    category = (
        domains[main[0][0]].leaderboard if main and main[0][0] in domains else "OVERALL"
    )
    overall = out["diagnostics"]["overall"]
    if leaderboard is not None:
        try:
            out["peer"] = peer(
                overall["return"], overall["staked"], leaderboard(category), category
            )
        except Exception:  # noqa: BLE001 - peer context is optional
            out["peer"] = None
    if pnl is not None:
        try:
            series = pnl(address)
            step = max(len(series) // 400, 1)
            kept = series[::step]
            if series and kept[-1] is not series[-1]:
                kept.append(series[-1])
            out["venue_pnl"] = kept
        except Exception:  # noqa: BLE001 - the venue's series is optional
            out["venue_pnl"] = None
    out["caveats"] = caveats(out)
    if progress:
        progress(1.0, "done")
    return out


def caveats(card: dict[str, Any]) -> list[str]:
    rec = card["record"]
    notes = [
        "The record shows what was bought and at what price, not what was believed: "
        "an entry price is only a lower bound on the belief behind it.",
        "Returns are before fees; the venue's activity does not carry them. "
        "Fee drag is an upper bound, as if every buy paid the taker fee.",
    ]
    if rec["truncated"]:
        notes.append(
            "The record was cut at the import limit; its oldest part is missing."
        )
    if rec["set_aside"]:
        notes.append(
            f"{rec['set_aside']} markets with splits, merges or conversions were "
            "set aside as market making or bookkeeping rather than bets."
        )
    if rec["scored"] and rec["priced"] < rec["scored"]:
        notes.append(
            f"Closing prices were read for {rec['priced']} of {rec['scored']} "
            "scored bets (the newest first); measures against the close use "
            "those only."
        )
    if card["model"] == "not used":
        notes.append(
            "Rules were found by search only; the AI model's proposals need a key."
        )
    return notes


def venue_history(token: str) -> record.Series:
    """A token's price series from the venue: hourly where it serves them,
    daily for older markets (measured 2026-09-13)."""
    from vp.venues import polymarket

    for fidelity in (60, 1440):
        points = polymarket.fetch_history(token, interval="max", fidelity=fidelity)[
            "points"
        ]
        if points:
            return [
                (_epoch(p["timestamp"]), float(p["implied_probability"]))
                for p in points
            ]
    return []


def from_venue(
    address: str, root: Path, *, cap: int = 50_000, max_histories: int = 300, **kw: Any
) -> dict[str, Any]:
    """The card for an address, read from the venue now."""
    from vp.venues import polymarket

    return analyse(
        address,
        polymarket.fetch_activity(address, max_items=cap),
        root,
        resolve=polymarket.fetch_resolution,
        history=venue_history,
        leaderboard=lambda category: polymarket.fetch_leaderboard(category, limit=50),
        pnl=polymarket.fetch_user_pnl,
        cap=cap,
        max_histories=max_histories,
        **kw,
    )


def csv_rows(card: dict[str, Any]) -> list[list[str]]:
    """The card's headline numbers as rows for a spreadsheet."""
    rows = [["section", "measure", "value"]]
    for k, v in card["diagnostics"]["overall"].items():
        if isinstance(v, dict):
            for kk, vv in v.items():
                rows.append(["overall", f"{k}.{kk}", str(vv)])
        else:
            rows.append(["overall", k, str(v)])
    for k, v in card["diagnostics"]["habits"].items():
        if isinstance(v, dict):
            for kk, vv in v.items():
                rows.append(["habits", f"{k}.{kk}", str(vv)])
        else:
            rows.append(["habits", k, str(v)])
    for domain, found in card["rules"].items():
        for r in found["rules"]:
            rows.append(
                [
                    "rule",
                    domain,
                    r["words"] + (" (validated)" if r["validated"] else ""),
                ]
            )
    return rows
