"""A strategy's belief written as a Python script (docs/tutorials/your_own_strategy.md).

On your own copy, a strategy's forecasts can come from a script of your own,
which you or any AI writes: a file with one function,

    def forecast(market, evidence) -> float | None

returning the chance that the market's first outcome happens (usually
"Yes"), or ``None`` to skip the market. It may also return
``(chance, reason)``. ``market`` is the market's record
(:class:`vp.markets.schema.BinaryMarket`) and ``evidence`` is what was known
at the forecast's time (:class:`vp.forecast.evidence.Evidence`): the
backtest builds it at each market's cutoff and it refuses to serve anything
later, so a script that reads the world only through it cannot see the
future. The harness runs the script as the belief of a spec (the one the
demo downloads, or ``strategies/example/strategy.json``): the spec still
chooses the markets, when to bet and how much.
"""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path
from types import ModuleType

from vp.forecast.base import Forecast, clip
from vp.forecast.evidence import Evidence
from vp.markets.schema import BinaryMarket


def load(path: Path) -> ModuleType:
    """Import the script as a module; it must define ``forecast``."""
    spec = importlib.util.spec_from_file_location(f"strategy_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not callable(getattr(module, "forecast", None)):
        raise ValueError(f"{path} has no function forecast(market, evidence)")
    return module


class ScriptForecaster:
    """The script as a forecaster, named ``script:<file name>``."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.module = load(path)
        self.name = f"script:{path.stem}"

    def forecast(self, market: BinaryMarket, evidence: Evidence) -> Forecast | None:
        answer = self.module.forecast(market, evidence)
        reason = ""
        if isinstance(answer, tuple):
            answer, reason = answer
        if answer is None:
            return None
        p = float(answer)
        if not math.isfinite(p) or not 0.0 <= p <= 1.0:
            raise ValueError(
                f"{self.path.name} returned {answer!r} for market"
                f" {market.market_id}; a chance must be between 0 and 1"
            )
        return Forecast(
            market.market_id,
            self.name,
            evidence.cutoff.isoformat(),
            clip(p),
            str(reason),
        )
