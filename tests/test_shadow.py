"""The shadow forecaster on a synthetic record (docs/shadow.md, tasks 92
to 96). Offline: the venue is replaced by functions over fixed data.

The person bets the favourite of 60 match markets at 70 cents a day before
the close, in three fills each; 42 of them win. The dataset around them has
300 markets whose favourite stood at 50 cents a day out and 10 at 70."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tests.test_strategy import make_market
from vp.markets.schema import Outcome
from vp.markets.store import write_history, write_markets
from vp.shadow import card, counterfactual, diagnostics, proof, record, rules

START = datetime(2026, 5, 1, 18, tzinfo=UTC)
DOMAIN = "epl"


def _close(i: int) -> datetime:
    return START + timedelta(days=i)


def _market(i: int, first_price: float, won_first: bool | None, prefix: str = "c"):
    return make_market(
        market_id=f"{prefix}{i}",
        condition_id=f"{prefix}{i}",
        domain=DOMAIN,
        closed_time=(_close(i % 60) + timedelta(hours=5)).isoformat(),
        end_date=_close(i % 60).isoformat(),
        resolved_outcome=None if won_first is None else int(won_first),
        outcomes=(
            Outcome("Yes", f"{prefix}{i}a", first_price),
            Outcome("No", f"{prefix}{i}b", 1 - first_price),
        ),
        parsed={"kind": "match", "home": "Arsenal" if i % 2 else "Chelsea"},
    )


def _series(i: int, day_out: float, won: bool) -> list[tuple[float, float]]:
    c = _close(i % 60)
    return [
        ((c - timedelta(hours=48)).timestamp(), day_out - 0.05),
        ((c - timedelta(hours=24)).timestamp(), day_out),
        ((c - timedelta(hours=1)).timestamp(), 0.75 if won else 0.6),
    ]


def _activity() -> list[dict]:
    rows = []
    for i in range(60):
        at = (_close(i) - timedelta(hours=24)).timestamp()
        for k, size in enumerate((10.0, 20.0, 10.0 * (1 + i % 5))):
            rows.append(
                {
                    "type": "TRADE",
                    "side": "BUY",
                    "timestamp": at + k,
                    "condition_id": f"c{i}",
                    "token_id": f"c{i}a",
                    "outcome_index": 0,
                    "outcome": "Yes",
                    "size": size,
                    "usdc_size": size * 0.7,
                    "price": 0.7,
                    "title": f"Match {i}",
                }
            )
    # Sold part of one bet; a split elsewhere; a sale of shares never bought.
    rows.append(
        {
            "type": "TRADE",
            "side": "SELL",
            "timestamp": rows[5]["timestamp"] + 60,
            "condition_id": "c1",
            "token_id": "c1a",
            "outcome_index": 0,
            "size": 5.0,
            "usdc_size": 3.75,
            "price": 0.75,
        }
    )
    rows.append({"type": "SPLIT", "timestamp": START.timestamp(), "condition_id": "z"})
    rows.append(
        {
            "type": "TRADE",
            "side": "BUY",
            "timestamp": START.timestamp(),
            "condition_id": "z",
            "token_id": "za",
            "outcome_index": 0,
            "size": 1.0,
            "usdc_size": 0.5,
            "price": 0.5,
        }
    )
    rows.append(
        {
            "type": "TRADE",
            "side": "SELL",
            "timestamp": START.timestamp(),
            "condition_id": "q",
            "token_id": "qa",
            "outcome_index": 0,
            "size": 3.0,
            "usdc_size": 1.5,
            "price": 0.5,
        }
    )
    return rows


WON = {i: i % 10 < 7 for i in range(60)}


@pytest.fixture
def root(tmp_path: Path) -> Path:
    mine = [_market(i, 0.7, WON[i]) for i in range(60)]
    others = [_market(i, 0.5, i % 2 == 0, "n") for i in range(300)]
    others += [_market(i, 0.7, i % 3 > 0, "p") for i in range(10)]
    write_markets(tmp_path / "markets" / DOMAIN / "resolved.parquet", mine + others)
    for m in others:
        i, day_out = int(m.market_id[1:]), m.outcomes[0].implied_probability or 0.5
        write_history(
            tmp_path / "histories" / DOMAIN / f"{m.market_id}.parquet",
            market_id=m.market_id,
            clob_token_id=f"{m.market_id}a",
            outcome="Yes",
            points=[
                {
                    "timestamp": datetime.fromtimestamp(t, tz=UTC).isoformat(),
                    "implied_probability": p,
                }
                for t, p in _series(i, day_out, bool(m.resolved_outcome))
            ],
        )
    return tmp_path


def _history(token: str) -> list[tuple[float, float]]:
    i = int(token[1:-1])
    return _series(i, 0.7, WON[i])


def test_the_record_aggregates_fills_and_sets_aside_what_is_not_a_bet() -> None:
    rec = record.build("0xABC", _activity(), cap=10_000)
    assert len(rec.bets) == 60 and rec.set_aside == ["z"]
    one = next(b for b in rec.bets if b.condition_id == "c1")
    assert one.fills == 3 and one.sells == 1 and one.entry == pytest.approx(0.7)
    assert one.held == pytest.approx(one.bought - 5)
    assert not rec.truncated and record.build("0x1", _activity(), cap=10).truncated


def test_outcomes_come_from_settlement_and_prices_from_the_series(root: Path) -> None:
    rec = record.build("0xabc", _activity(), cap=10_000)
    markets = card.load_markets(root, [DOMAIN])
    # One market is closed but has no settlement anywhere: it stays unscored.
    markets["c0"] = _market(0, 0.7, None)
    counts = record.attach(rec, markets, lambda c: None, _history)
    assert counts["scored"] == 59 and counts["in_domains"] == 60
    b = next(b for b in rec.bets if b.condition_id == "c3")
    assert b.won is True and b.close == 0.75 and b.before == pytest.approx(0.65)
    # Measured from settlement, as the backtest measures it.
    assert b.favourite and b.hours_before_close == pytest.approx(29, abs=0.01)


def test_diagnostics_measure_edge_closing_line_and_habits(root: Path) -> None:
    # Outside our datasets there is no event time, so no closing line.
    rec = record.build("0xabc", _activity(), cap=10_000)
    record.attach(
        rec,
        {},
        lambda c: {
            "winner_index": 0 if WON[int(c[1:])] else 1,
            "resolved_at": _close(int(c[1:])).isoformat(),
        },
        _history,
    )
    assert "clv" not in diagnostics.diagnose(rec.bets)["overall"]
    rec = record.build("0xabc", _activity(), cap=10_000)
    record.attach(rec, card.load_markets(root, [DOMAIN]), lambda c: None, _history)
    d = diagnostics.diagnose(rec.bets)
    o = d["overall"]
    assert o["scored"] == 60 and o["win_rate"] == pytest.approx(0.7)
    assert o["edge"]["mean"] == pytest.approx(0.0, abs=1e-9)
    # Closes at 0.75 on the 42 winners and 0.6 on the 18 losers.
    assert o["clv"]["mean"] == pytest.approx((42 * 0.05 - 18 * 0.1) / 60)
    assert o["skill_vs_close"] < 0
    assert d["habits"]["favourite"]["bets"] == 0 and d["habits"]["chased_share"] == 1.0
    assert [r["band"] for r in d["calibration"]] == [[0.7, 0.8]]
    assert list(d["by_domain"]) == [DOMAIN]


def test_a_rule_is_found_validated_and_is_a_spec(root: Path) -> None:
    c = card.analyse(
        "0xabc",
        _activity(),
        root,
        resolve=lambda c: None,
        history=_history,
        leaderboard=lambda cat: [
            {"pnl": 10.0, "volume": 100.0},
            {"pnl": -1.0, "volume": 100.0},
        ],
    )
    found = c["rules"][DOMAIN]
    best = found["rules"][0]
    assert best["validated"], best
    r = best["rule"]
    assert (r["kind"], r["side"], r["hours"]) == ("match", "favourite", 24)
    assert r["price_min"] <= 0.7 <= r["price_max"]
    assert best["held_out"]["coverage"] == 1.0 and best["held_out"]["lift"] >= 3
    spec = rules.Rule(**r).spec("mine")
    assert rules.from_spec(spec) == rules.Rule(**r)
    assert best["spec"]["rule"]["follow"] == "favourite"
    # The counterfactual splits the gap exactly.
    cf = c["counterfactual"][DOMAIN]
    parts = cf["sizing"]["mean"] + cf["timing"]["mean"] + cf["selection"]["mean"]
    assert cf["you"] - cf["rule"] == pytest.approx(parts)
    # Every entry was at the rule's own price; the one early sale is the
    # only timing there is (exits count as timing).
    assert 0 < abs(cf["timing"]["mean"]) < 0.001
    assert c["peer"]["listed"] == 2 and c["peer"]["category"] == "SPORTS"
    assert any("search only" in note for note in c["caveats"])
    assert card.csv_rows(c)[0] == ["section", "measure", "value"]


def test_counterfactual_needs_enough_bets() -> None:
    rule = rules.Rule(DOMAIN, "match", "favourite", 0.6, 0.8, 24)
    assert counterfactual.compare([], [], rule) is None


def test_ownership_is_proven_by_signature_or_proxy() -> None:
    # A published EIP-191 example (web3.js `accounts.sign("Some data", key)`).
    sig = (
        "0xb91467e570a6466aa9e9876cbcd013baba02900b8979d43fe208a4a4f339f5fd"  # pragma: allowlist secret
        "6007e74cd82e037b800186422fc2da167c747ef045e5d18a5f5d4300f8e1a0291c"  # pragma: allowlist secret
    )
    signer = "0x2c7536e3605d9c16a7a3d7b1898e529396a65c23"
    assert proof.recover("Some data", sig) == signer
    assert proof.owns(signer, "Some data", sig, lambda a: None)
    proxy = "0x" + "1" * 40
    assert proof.owns(proxy, "Some data", sig, lambda a: {"proxyWallet": proxy})
    assert not proof.owns(proxy, "Some data", sig, lambda a: None)
    assert not proof.owns(signer, "Other data", sig, lambda a: None)
    assert not proof.owns(signer, "Some data", "0x1234", lambda a: None)
    assert "authorises no transaction" in proof.message(signer, "n1")
