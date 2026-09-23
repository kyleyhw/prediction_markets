"""Forecast committees: role forecasters and a rule to combine them
(plan, task 67; docs/signals.md).

A preset (`vp/signals/committees/<name>.yaml`) names the analysts, each an
LLM forecaster with a role's guidance, and a red team that reads their
answers and argues against the likeliest mistake; the aggregator is not a
model but a rule, applied to every answer:

* ``mean_logodds``: the mean of the log-odds;
* ``trimmed``: the same after dropping the highest and lowest answers;
* ``extremise``: the mean log-odds times a factor $a \\ge 1$ (Satopää et
  al. 2014), which corrects the underconfidence of an average of
  forecasters who share information;
* ``cap``: the result kept at least ``cap`` from 0 and 1.

Every worker sees only the evidence object and the domain pack; each one's
probability, cost and rationale hash is kept in the forecast's metadata.
Committees are not offered as a default until they beat single elicitation
and the best blend on matched samples, which needs the first keyed runs.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from vp.forecast.base import Forecast, clip
from vp.forecast.evidence import Evidence
from vp.markets.schema import BinaryMarket

PRESETS = Path(__file__).parent / "committees"


def presets() -> dict[str, Path]:
    return {p.stem: p for p in sorted(PRESETS.glob("*.yaml"))}


def _logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def aggregate(
    ps: list[float],
    *,
    rule: str = "mean_logodds",
    factor: float = 1.0,
    cap: float = 0.02,
) -> float:
    """Combine probabilities by the rule, then cap."""
    xs = sorted(_logit(p) for p in ps)
    if rule == "trimmed" and len(xs) > 2:
        xs = xs[1:-1]
    mean = sum(xs) / len(xs)
    if rule == "extremise":
        mean *= factor
    p = 1.0 / (1.0 + math.exp(-mean))
    return min(max(p, cap), 1.0 - cap)


@dataclass
class Committee:
    name: str
    analysts: list[dict[str, str]]
    red_team: str | None
    rule: str = "mean_logodds"
    factor: float = 1.0
    cap: float = 0.02
    options: dict[str, Any] = field(default_factory=dict)
    calls: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def preset(cls, preset: str, **options: Any) -> Committee:
        data = yaml.safe_load(presets()[preset].read_text())
        agg = data.get("aggregate", {})
        return cls(
            name=f"committee:{preset}",
            analysts=data["analysts"],
            red_team=data.get("red_team"),
            rule=agg.get("rule", "mean_logodds"),
            factor=float(agg.get("factor", 1.0)),
            cap=float(agg.get("cap", 0.02)),
            options=options,
        )

    @property
    def model(self) -> str | None:
        return self.options.get("model")

    def _worker(self, role: str, guidance: str) -> Any:
        from vp.forecast.llm import LLMForecaster

        return LLMForecaster(
            name=f"{self.name}/{role}", instructions=guidance, **self.options
        )

    def forecast(self, market: BinaryMarket, evidence: Evidence) -> Forecast | None:
        answers: dict[str, Forecast] = {}
        for role in self.analysts:
            worker = self._worker(role["id"], role["guidance"])
            answer = worker.forecast(market, evidence)
            self.calls += worker.calls
            if answer is not None:
                answers[role["id"]] = answer
        if not answers:
            return None
        if self.red_team:
            summary = "\n".join(
                f"- {rid}: {a.p_hat:.3f} because {a.rationale[:600]}"
                for rid, a in answers.items()
            )
            worker = self._worker(
                "red_team", f"{self.red_team}\n\nThe analysts said:\n{summary}"
            )
            answer = worker.forecast(market, evidence)
            self.calls += worker.calls
            if answer is not None:
                answers["red_team"] = answer
        p = aggregate(
            [a.p_hat for a in answers.values()],
            rule=self.rule,
            factor=self.factor,
            cap=self.cap,
        )
        meta = (
            {f"{rid}.p": f"{a.p_hat:.4f}" for rid, a in answers.items()}
            | {
                f"{rid}.rationale_sha256": hashlib.sha256(
                    a.rationale.encode()
                ).hexdigest()
                for rid, a in answers.items()
            }
            | {"rule": self.rule}
        )
        return Forecast(
            market.market_id,
            self.name,
            evidence.cutoff.isoformat(),
            clip(p),
            "\n---\n".join(f"[{rid}] {a.rationale}" for rid, a in answers.items()),
            cost_usd=sum(a.cost_usd for a in answers.values()),
            meta=meta,
        )
