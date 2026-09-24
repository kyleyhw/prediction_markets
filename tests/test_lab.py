"""The Research Lab (plan, task 123): its studies on a data root built
here, and pages whose recorded output is checked by rerunning it."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests.test_forecast import epl_match
from vp import lab
from vp.lab import studies
from vp.markets.store import write_history, write_markets


def _root(tmp_path: Path) -> Path:
    """Forty matches: ten at each of four prices, the cheap ones winning less
    often than priced and the dear ones more often (a longshot bias)."""
    markets = []
    start = datetime(2026, 1, 1, 17, tzinfo=timezone.utc)
    for i in range(40):
        price = (0.1, 0.3, 0.6, 0.9)[i % 4]
        wins = {0.1: 0, 0.3: 2, 0.6: 7, 0.9: 10}[price]
        label = int((i // 4) < wins)
        closed = start + timedelta(days=i)
        mid = str(100 + i)
        markets.append(
            epl_match(
                mid, "Arsenal FC", "Chelsea FC", "Arsenal FC", label, closed.isoformat()
            )
        )
        write_history(
            tmp_path / "histories" / "epl" / f"{mid}.parquet",
            market_id=mid,
            clob_token_id=f"{mid}0",
            outcome="Yes",
            points=[
                {
                    "timestamp": (closed - timedelta(days=2)).isoformat(),
                    "implied_probability": price,
                }
            ],
            bar_minutes=1440,
        )
    write_markets(tmp_path / "markets" / "epl" / "resolved.parquet", markets)
    return tmp_path


def test_the_longshot_table_bins_prices_against_outcomes(tmp_path: Path) -> None:
    root = _root(tmp_path)
    out = studies.longshot(root, "epl")
    assert out.startswith("40 labelled epl markets")
    rows = {
        line.split(" | ")[0]: line
        for line in out.splitlines()
        if line.startswith("| 0.")
    }
    assert "| 10 | 0.100 | 0.000 |" in rows["| 0.05 to 0.15"]
    assert "| 10 | 0.900 | 1.000 |" in rows["| 0.85 to 0.95"]
    # Buying every long shot at the ask lost the whole stake.
    assert rows["| 0.05 to 0.15"].endswith("| -1.000 |")
    assert out == studies.longshot(root, "epl")  # the same every time


def test_power_says_how_many_markets_a_claim_needs(tmp_path: Path) -> None:
    out = studies.power(_root(tmp_path), "epl", "constant")
    assert "`constant` against the market on 40 epl markets" in out
    assert "| +0.10 |" in out and "| 0.10 | 271 |" in out


def test_a_page_records_its_output_and_a_change_is_caught(tmp_path: Path) -> None:
    page = tmp_path / "study.md"
    page.write_text(
        "# A study\n\n```bash lab\nvp lab longshot --domain epl\n```\n\nText.\n"
    )
    answers = {"n": 1}

    def runner(argv: list[str]) -> str:
        assert argv == ["lab", "longshot", "--domain", "epl"]
        return f"answer {answers['n']}\nruntime: 1.3 s\n"

    assert lab.check(page, runner) == [
        f"{page}: `vp lab longshot --domain epl` has no recorded output"
    ]
    assert lab.update(page, runner) == 1
    assert "```text\nanswer 1\n```" in page.read_text()
    assert "runtime" not in page.read_text()
    assert lab.check(page, runner) == []
    answers["n"] = 2
    assert len(lab.check(page, runner)) == 1
    assert lab.update(page, runner) == 1 and lab.check(page, runner) == []
