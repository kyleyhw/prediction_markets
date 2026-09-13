"""The dashboard's JSON API against a data root built by the other tests'
fixtures: a resolved set, a backtest run, a paper ledger and a snapshot."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from urllib.request import urlopen

import pytest

from tests.test_forecast import EPL, root  # noqa: F401 - fixture
from tests.test_paper import NOW, make_source, resolved_record
from vp.backtest.run import BacktestConfig, run_backtest
from vp.domains import CS2
from vp.forecast.baselines import Constant
from vp.paper.ledger import Ledger
from vp.paper.loop import run_cycle
from vp.ui.server import _tables, make_server


@pytest.fixture
def served(root: Path):  # noqa: F811
    run_backtest(
        BacktestConfig(
            domain="epl", forecasters=("market", "constant"), kinds=("match",)
        ),
        root,
        root / "backtests" / "epl" / "20260913T000000Z",
    )
    ledger = Ledger(root / "paper" / "ledger.jsonl")
    run_cycle(
        CS2,
        [Constant(0.9, name="sure")],
        make_source([resolved_record("pending", None)]),
        root,
        ledger,
        depth=1,
        now=NOW,
    )
    server = make_server(root, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def get(base: str, path: str):
    with urlopen(base + path) as resp:
        return resp.status, resp.headers.get("Content-Type"), resp.read()


def test_page_and_api(served: str) -> None:
    status, ctype, body = get(served, "/")
    assert status == 200 and "text/html" in ctype and b"vibe-predict" in body
    status, ctype, body = get(served, "/#backtests")
    assert status == 200

    o = json.loads(get(served, "/api/overview")[2])
    assert o["domains"]["epl"]["resolved"]["markets"] == len(EPL)
    assert o["domains"]["epl"]["resolved"]["kinds"] == {"match": 6}
    assert (
        o["domains"]["epl"]["backtests"] == 1 and o["domains"]["cs2"]["snapshots"] == 1
    )
    assert (
        o["paper"]["accounts"][0]["forecaster"] == "sure"
        and o["paper"]["verified"] is True
    )

    runs = json.loads(get(served, "/api/backtests")[2])
    assert len(runs) == 1 and runs[0]["domain"] == "epl"
    assert runs[0]["tables"][0][0][0] == "Forecaster" and runs[0]["figures"] == [
        "cumulative_score.png",
        "equity.png",
        "reliability.png",
    ]
    status, ctype, body = get(served, "/api/backtests/epl/20260913T000000Z/equity.png")
    assert status == 200 and ctype == "image/png" and body[:4] == b"\x89PNG"

    p = json.loads(get(served, "/api/paper?limit=5")[2])
    assert (
        p["entries"] == 3
        and len(p["recent"]) == 3
        and p["accounts"][0]["open"][0]["side"] == "yes"
    )

    s = json.loads(get(served, "/api/snapshots/cs2")[2])
    assert s["markets"][0]["kind"] == "match" and s["markets"][0]["ask"] == 0.51
    assert json.loads(get(served, "/api/snapshots/epl")[2])["markets"] == []
    assert json.loads(get(served, "/api/forecasts")[2])[0]["forecaster"] == "sure"


def test_not_found_and_traversal(served: str) -> None:
    from urllib.error import HTTPError

    for path in (
        "/api/nope",
        "/api/snapshots/nba",
        "/api/backtests/epl/x/../../secret.png",
    ):
        with pytest.raises(HTTPError) as err:
            urlopen(served + path)
        assert err.value.code == 404


def test_markdown_tables() -> None:
    text = "# t\n\nline\n\n| a | b |\n| :--- | ---: |\n| 1 | 2 |\n\n| c |\n| --- |\n| 3 |\n"
    assert _tables(text) == [[["a", "b"], ["1", "2"]], [["c"], ["3"]]]
