"""Run manifests and run cards (plan, task 57).

A **manifest** says exactly what produced a run: the spec version's hash,
the belief's configuration and model, the hashes of the domain packs its
model could read, the dataset version, the evidence archive's version, the
fee schedule's source, and the package versions. Its hash leaves out the
time it was written, so the same inputs give the same hash, and
:func:`manifest_diff` names what differs between two.

A **run card** is the page's summary of one backtest, computed from the
run's ``results.json`` and its manifest, never written by a model: how many
markets settled, the scores, the paired difference against the market's
own Brier score with a bootstrap interval (resampling markets, so both
forecasts move together), calibration, the bets' P&L and fees, the cost,
the sample size the observed difference would need to be told from zero,
and caveats written from the numbers (a small sample, a belief that saw the
price, prices at daily resolution).
"""

from __future__ import annotations

import hashlib
import json
import platform
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from typing import Any

import numpy as np

from vp.domains.pack import load as load_pack
from vp.strategy.spec import Spec, spec_hash, uses_model

#: Packages whose versions can change a number on a card.
PACKAGES = ("vibe-predict", "numpy", "pyarrow", "pydantic", "anthropic")
#: Below this many scored markets a card says the sample is small.
SMALL_N = 100
#: Paired bootstrap draws and the interval's confidence.
DRAWS, CONFIDENCE = 2000, 0.95


def _version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "absent"


def manifest(
    spec: Spec,
    *,
    domain: str,
    dataset_version: str,
    packs: dict[str, str] | None = None,
    evidence_version: str = "resolved-set",
) -> dict[str, Any]:
    """What produced a backtest of ``spec`` on ``domain``."""
    belief = spec.belief.model_dump(mode="json")
    model = None
    if uses_model(spec):
        from vp.forecast.llm import TIERS

        model = TIERS[spec.belief.tier]
    pack = load_pack(domain, (packs or {}).get(domain))
    body = {
        "spec_hash": spec_hash(spec),
        "domain": domain,
        "belief": belief,
        "rule_kind": spec.rule.kind,
        "model": model,
        "domain_pack": pack.sha256 if pack else None,
        "dataset_version": dataset_version,
        # Phase 17's point-in-time archive replaces the resolved set here.
        "evidence_version": evidence_version,
        "fees": "each market's feeSchedule as captured with the dataset",
        "packages": {name: _version(name) for name in PACKAGES},
        "python": platform.python_version(),
    }
    return {
        **body,
        "hash": _hash(body),
        "written_at": datetime.now(tz=UTC).isoformat(timespec="seconds"),
    }


def _hash(body: dict[str, Any]) -> str:
    text = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


def manifest_hash(m: dict[str, Any]) -> str:
    """The hash of a manifest's content, its time left out."""
    return _hash({k: v for k, v in m.items() if k not in ("hash", "written_at")})


def manifest_diff(a: dict[str, Any], b: dict[str, Any]) -> list[str]:
    """The fields that differ between two manifests, time left out."""
    out = []
    for key in sorted((a.keys() | b.keys()) - {"hash", "written_at"}):
        if key == "packages":
            for name in sorted(a.get(key, {}).keys() | b.get(key, {}).keys()):
                x, y = a.get(key, {}).get(name), b.get(key, {}).get(name)
                if x != y:
                    out.append(f"packages.{name}: {x} -> {y}")
        elif a.get(key) != b.get(key):
            out.append(f"{key}: {a.get(key)} -> {b.get(key)}")
    return out


def paired_interval(
    diffs: np.ndarray, seed: int = 0
) -> tuple[float, float, float] | None:
    """Mean of per-market differences and its bootstrap interval."""
    if diffs.size < 2:
        return None
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, diffs.size, size=(DRAWS, diffs.size))
    means = diffs[draws].mean(axis=1)
    tail = (1 - CONFIDENCE) / 2
    return (
        float(diffs.mean()),
        float(np.quantile(means, tail)),
        float(np.quantile(means, 1 - tail)),
    )


def needed_n(diffs: np.ndarray) -> int | None:
    """Markets needed to tell the observed mean difference from zero
    (5% level, 80% power), or None when there is no difference."""
    if diffs.size < 2 or diffs.mean() == 0:
        return None
    sd = float(diffs.std(ddof=1))
    return int(np.ceil((2.8 * sd / abs(float(diffs.mean()))) ** 2))


def run_card(
    results: dict[str, Any],
    manifest_: dict[str, Any],
    *,
    sees_price: bool = False,
    daily_bars: bool = False,
) -> dict[str, Any]:
    """The card for one backtest's ``results.json`` and manifest."""
    rows = {f["name"]: f for f in results.get("forecasters", [])}
    belief = next((f for n, f in rows.items() if n != "market"), rows.get("market"))
    card: dict[str, Any] = {
        "manifest_hash": manifest_.get("hash"),
        "spec_hash": manifest_.get("spec_hash"),
        "domain": manifest_.get("domain"),
        "scored": results.get("common", 0),
        "candidates": results.get("candidates", 0),
        "with_price": results.get("with_price", 0),
        "caveats": [],
    }
    if belief is None:
        card["caveats"].append("Nothing was scored.")
        return card
    advantage = np.asarray(belief.get("advantage") or [], dtype=float)
    diffs = np.diff(advantage, prepend=0.0) if advantage.size else advantage
    interval = paired_interval(diffs)
    stats = belief.get("stats") or {}
    card.update(
        {
            "forecaster": belief["name"],
            "brier": belief["brier"],
            "log": belief["log"],
            "brier_market": rows.get("market", {}).get("brier"),
            "skill": belief["skill"],
            "advantage": None
            if interval is None
            else {"mean": interval[0], "low": interval[1], "high": interval[2]},
            "calibration": {
                k: belief["calibration"][k]
                for k in ("reliability", "resolution", "ece")
            },
            "bets": stats.get("count", 0),
            "return": stats.get("total_return"),
            "max_drawdown": stats.get("max_drawdown"),
            "fees_usd": belief.get("fees_usd", 0.0),
            "cost_usd": belief.get("cost_usd", 0.0),
            "needed_n": needed_n(diffs),
            "sees_price": sees_price,
        }
    )
    caveats = card["caveats"]
    n = card["scored"]
    if n < SMALL_N:
        caveats.append(f"Only {n} markets were scored; treat every number as rough.")
    if interval is not None and interval[1] <= 0 <= interval[2]:
        caveats.append(
            "The interval includes zero: this run cannot tell the belief from"
            " the market."
        )
    if card["needed_n"] and card["needed_n"] > n:
        caveats.append(
            f"A difference this size needs about {card['needed_n']:,} markets"
            f" to be told from zero; this run had {n}."
        )
    if manifest_.get("rule_kind") == "follow":
        caveats.append("A follow rule forecasts nothing; judge it by its P&L alone.")
    model = manifest_.get("model")
    if model:
        from vp.forecast.llm import TRAINING_CUTOFFS, contaminated

        dates = results.get("settled_dates") or []
        clean = [i for i, d in enumerate(dates) if not contaminated(model, d)]
        card["training_cutoff"] = TRAINING_CUTOFFS.get(model)
        card["uncontaminated_n"] = len(clean)
        if TRAINING_CUTOFFS.get(model) is None:
            caveats.append(
                f"{model}'s training cutoff is not recorded, so none of this run"
                " counts as skill: the model may have read how these markets ended."
            )
        elif clean and len(clean) < len(diffs):
            later = paired_interval(diffs[clean])
            card["advantage_after_cutoff"] = (
                None
                if later is None
                else {"mean": later[0], "low": later[1], "high": later[2]}
            )
            caveats.append(
                f"Only the {len(clean)} markets settled after {model}'s training"
                " cutoff count as skill."
            )
    if sees_price:
        caveats.append(
            "The belief was shown the market's price, so its skill measures"
            " anchoring, not information; it is left out of skill rankings."
        )
    if daily_bars:
        caveats.append(
            "Some prices are daily bars, so the price at the cutoff can be up"
            " to a day old."
        )
    if results.get("fees_assumed"):
        caveats.append(
            f"{results['fees_assumed']} of the selected markets did not state a fee;"
            f" the venue's 2026 rate ({results.get('fee_rate_assumed', 0):.0%} of"
            " p(1 - p) a share) was charged instead."
        )
    if results.get("with_price", 0) < results.get("candidates", 0):
        missing = results["candidates"] - results["with_price"]
        caveats.append(f"{missing} selected markets had no price at the cutoff.")
    return card
