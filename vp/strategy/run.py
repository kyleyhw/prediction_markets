"""What runs a spec: its selector, policy and belief, backtested and in paper.

The engine's backtest and paper loop are unchanged; a spec reaches them as
three plain values (docs/strategies.md): ``where``, a predicate on a market
from the selector; a :class:`~vp.backtest.sizing.Policy` from the rule and
the sizing; and a forecaster from the belief. The backtest charges each
market's own fee, as paper does.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from vp.backtest.run import BacktestConfig, BacktestResult, run_backtest
from vp.backtest.sizing import Policy
from vp.domains import DOMAINS, Domain
from vp.forecast import Forecaster, make_forecaster
from vp.forecast.baselines import MarketPrice
from vp.markets.schema import BinaryMarket
from vp.markets.store import read_markets
from vp.strategy.spec import FieldFilter, Selector, Spec, canonical, render, spec_hash

#: The name a follow rule's belief records under: the market's price, which
#: it trades on without forecasting.
FOLLOW = "follow"
#: The taker rate assumed for a market whose record states none (datasets
#: built before fee schedules were captured): the venue's published 2026
#: rate for sports and weather markets, the conservative choice, since
#: charging nothing flatters every strategy (F5). The run card counts them.
ASSUMED_FEE_RATE = 0.05


def _holds(condition: FieldFilter, value: str | None) -> bool:
    if value is None or value == "":
        return False
    text = value.lower()
    wanted = [v.lower() for v in condition.values]
    if condition.op == "is":
        return text in wanted
    if condition.op == "is_not":
        return text not in wanted
    if condition.op == "contains":
        return any(w in text for w in wanted)
    try:
        number, bound = float(value), float(condition.values[0])
    except ValueError:
        return False
    return number >= bound if condition.op == "at_least" else number <= bound


def selects(
    selector: Selector,
    *,
    live: bool,
    domains: Mapping[str, Domain] = DOMAINS,
) -> Callable[[BinaryMarket], bool]:
    """The selector as a predicate. ``live`` adds the paper-only floors."""

    def ok(market: BinaryMarket) -> bool:
        if market.domain not in selector.domains:
            return False
        kind = market.parsed.get("kind")
        if selector.kinds:
            if kind not in selector.kinds:
                return False
        else:
            domain = domains.get(market.domain or "")
            if kind is None or domain is None or kind not in domain.kinds:
                return False
        if not all(_holds(c, market.parsed.get(c.field)) for c in selector.where):
            return False
        question = market.question.lower()
        if selector.words and not any(w.lower() in question for w in selector.words):
            return False
        if any(w.lower() in question for w in selector.exclude_words):
            return False
        if live:
            if (
                selector.min_volume_usd is not None
                and (market.volume_usd or 0.0) < selector.min_volume_usd
            ):
                return False
            if (
                selector.min_liquidity_usd is not None
                and (market.liquidity_usd or 0.0) < selector.min_liquidity_usd
            ):
                return False
            if selector.max_spread is not None:
                spread = market.spread
                if spread is None and None not in (market.best_bid, market.best_ask):
                    spread = (market.best_ask or 0.0) - (market.best_bid or 0.0)
                if spread is None or spread > selector.max_spread:
                    return False
        return True

    return ok


def policy(spec: Spec) -> Policy:
    """The rule and sizing as the engine's policy."""
    rule, s = spec.rule, spec.sizing
    return Policy(
        kelly_multiplier=s.kelly_fraction,
        max_fraction=s.max_fraction,
        min_edge=rule.min_edge,
        sides=rule.sides,
        follow=rule.follow if rule.kind == "follow" else None,
        flat_fraction=s.flat_fraction,
        price_min=rule.price_min,
        price_max=rule.price_max,
        max_stake_usd=s.max_stake_usd,
        max_open=s.max_open,
        max_per_event=s.max_per_event,
    )


def belief(spec: Spec, domain: str, **llm: Any) -> Forecaster:
    """The belief's forecaster for one domain; ``llm`` options pass through
    (a client, batching) for the AI model."""
    b = spec.belief
    if spec.rule.kind == "follow":
        return MarketPrice(name=FOLLOW)
    if b.forecaster == "llm":
        from vp.forecast.llm import TIERS

        return make_forecaster(
            "llm",
            domain,
            model=TIERS[b.tier],
            samples=b.samples,
            instructions=b.instructions,
            sees_price=b.sees_price,
            **llm,
        )
    return make_forecaster(b.forecaster, domain)


def backtest(
    spec: Spec,
    root: Path,
    out_dir: Path,
    *,
    max_markets: int | None = None,
    seed: int = 0,
    progress: Callable[[float, str], None] | None = None,
    wrap: Callable[[Forecaster, str], Forecaster] | None = None,
    made: list[Forecaster] | None = None,
    dataset_versions: Mapping[str, str] | None = None,
    packs: Mapping[str, str] | None = None,
    **llm: Any,
) -> dict[str, BacktestResult]:
    """Backtest the spec on each of its domains, one run directory per domain.

    The market's own price is always run beside the belief, as the
    reference every run card scores against. ``wrap`` may wrap the belief
    (the platform memoises statistical ones); the beliefs used are appended
    to ``made``, so a caller can read what they spent. Each domain's
    directory gets the spec, its rendering, the manifest (with the dataset
    version given, ``local`` otherwise) and the run card.
    """
    from vp.strategy import card

    results: dict[str, BacktestResult] = {}
    for domain in spec.selector.domains:
        if not (root / "markets" / domain / "resolved.parquet").exists():
            continue
        forecaster = belief(spec, domain, **llm)
        if made is not None:
            made.append(forecaster)
        if wrap is not None:
            forecaster = wrap(forecaster, domain)
        config = BacktestConfig(
            domain=domain,
            forecasters=("market", forecaster.name),
            hours_before_close=spec.schedule.hours_before_close,
            kinds=tuple(spec.selector.kinds),
            max_markets=max_markets,
            seed=seed,
            initial_cash=spec.sizing.initial_cash,
            kelly_multiplier=spec.sizing.kelly_fraction,
            max_fraction=spec.sizing.max_fraction,
            min_edge=spec.rule.min_edge,
            fee_rate=ASSUMED_FEE_RATE,
            market_fees=True,
        )
        forecasters: list[Forecaster] = [MarketPrice(), forecaster]
        if forecaster.name == "market":
            forecasters = [MarketPrice()]
            config = replace(config, forecasters=("market",))
        folder = out_dir / domain
        folder.mkdir(parents=True, exist_ok=True)
        # The version that ran, beside its results, in the words confirmed.
        (folder / "spec.json").write_text(canonical(spec))
        (folder / "strategy.md").write_text(
            f"# {spec.name}\n\nversion {spec_hash(spec)}\n\n"
            + "\n\n".join(render(spec))
            + "\n"
        )
        where = selects(spec.selector, live=False)
        results[domain] = run_backtest(
            config,
            root,
            out_dir / domain,
            forecasters=forecasters,
            progress=progress,
            policy=policy(spec),
            where=where,
        )
        path = folder / "results.json"
        data = json.loads(path.read_text())
        resolved = read_markets(root / "markets" / domain / "resolved.parquet")
        data["fees_assumed"] = sum(
            1 for m in resolved if m.fee_rate is None and where(m)
        )
        data["fee_rate_assumed"] = ASSUMED_FEE_RATE
        manifest = card.manifest(
            spec,
            domain=domain,
            dataset_version=(dataset_versions or {}).get(domain, "local"),
            packs=dict(packs or {}),
        )
        uses_model = spec.belief.forecaster == "llm" and spec.rule.kind == "edge"
        data["card"] = card.run_card(
            data, manifest, sees_price=spec.belief.sees_price and uses_model
        )
        path.write_text(json.dumps(data, indent=1))
        (folder / "manifest.json").write_text(json.dumps(manifest, indent=1))
        (folder / "card.json").write_text(json.dumps(data["card"], indent=1))
    return results


def paper_options(spec: Spec) -> dict[str, Any]:
    """The keyword arguments a spec gives `vp.paper.loop.run_cycle`."""
    return {
        "policy": policy(spec),
        "where": selects(spec.selector, live=True),
        "window_hours": spec.schedule.hours_before_close,
    }
