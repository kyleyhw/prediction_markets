"""What your code gets and must return, in the demo's "Write your own code" tab.

Write one function::

    def decide(market: Market, past: list[Result]) -> Signal:

It is called once for every past market, at the time before the market
settled that you choose. ``market`` is what was known then; ``past`` holds
the markets of the same kind of contest that had already settled by then,
oldest first, with how they ended. Nothing later is given, so your code
cannot see the future. Return a ``Signal``:

* ``"yes"`` to buy Yes, ``"no"`` to buy No, at the stake you set;
* ``None`` to skip the market;
* or, instead of signals, a ``float`` between 0 and 1: your chance that Yes
  happens. A bet is then placed only when your chance beats the price, after
  fees, by the margin you set, sized by a quarter of the Kelly stake.

Every answer must be of one sort: signals, or chances. The page runs this
module in your browser with Pyodide; the backtest itself is the same as for
every other strategy in the demo (pages/engine.js, checked against the
platform's Python engine by tests/test_demo.py).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

Signal = Literal["yes", "no"] | None


@dataclass(frozen=True)
class Market:
    """A market as it was at the time of the decision."""

    question: str  # "Will Arsenal FC win on 2026-03-14?"
    domain: str  # "epl", "cs2", "weather", ...
    kind: str  # "match", "daily_temperature", "total", ...
    fields: dict[str, str]  # the question's parts: team_a, team_b, side, city...
    price: float  # the price of Yes then: the crowd's chance, 0 to 1
    hours_left: float  # hours until the market settled
    forecasts: dict[str, float]  # built-in forecasts of Yes then, e.g. {"elo": 0.61}


@dataclass(frozen=True)
class Result:
    """A market that had settled before the decision, and how it ended."""

    question: str
    kind: str
    fields: dict[str, str]
    settled: str  # when it settled, ISO 8601
    outcome: int  # 1 if Yes happened, 0 if not
    price: float | None  # its price of Yes the same time before it settled


class StrategyError(Exception):
    """Your code broke a rule of the interface; the message says which."""


def check(answer: Any, question: str) -> float | str | None:
    """The answer, if it is a Signal or a chance; else a StrategyError."""
    if answer is None or answer in ("yes", "no"):
        return answer
    if isinstance(answer, (int, float)) and not isinstance(answer, bool):
        if math.isfinite(answer) and 0.0 <= answer <= 1.0:
            return float(answer)
    raise StrategyError(
        f'decide() returned {answer!r} for "{question}". It must return "yes",'
        ' "no", None, or a chance between 0 and 1.'
    )


def run(namespace: dict[str, Any], data: dict[str, Any], cutoff: int) -> dict:
    """Call ``decide`` on every market of an exported domain with a price at
    ``cutoff`` hours before it settled; returns the answers by market id."""
    decide = namespace.get("decide")
    if not callable(decide):
        raise StrategyError("Your code needs a function: def decide(market, past)")
    key = str(cutoff)
    rows = data["markets"]  # in settlement order
    results = [
        Result(
            m["q"],
            m["kind"] or "",
            dict(m["fields"]),
            m["settled"],
            int(m["y"]),
            m["price"].get(key),
        )
        for m in rows
    ]
    answers: dict[str, float | str] = {}
    sort = None
    seen = 0  # how many markets had settled before the current cutoff
    times = [datetime.fromisoformat(m["settled"]) for m in rows]
    for m, settled in zip(rows, times, strict=True):
        if key not in m["price"]:
            continue
        now = settled - timedelta(hours=cutoff)
        while seen < len(rows) and times[seen] < now:
            seen += 1
        market = Market(
            m["q"],
            data["domain"],
            m["kind"] or "",
            dict(m["fields"]),
            m["price"][key],
            float(cutoff),
            {name: by[key] for name, by in m["f"].items() if key in by},
        )
        answer = check(decide(market, results[:seen]), m["q"])
        if answer is None:
            continue
        this = "chance" if isinstance(answer, float) else "signal"
        if sort is not None and this != sort:
            raise StrategyError(
                "decide() returned a signal for one market and a chance for"
                " another; return one sort for every market."
            )
        sort = this
        answers[m["id"]] = answer
    return {"sort": sort, "answers": answers}
