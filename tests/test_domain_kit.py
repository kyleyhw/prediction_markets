"""A domain defined only by its adapter reaches everything else (plan, task
79; docs/domains.md): the strategy spec accepts it, the signals apply to
it by kind, and the evidence derives its table, with no other file
touched."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from vp.domains import DOMAINS, EPL
from vp.domains.base import Domain
from vp.forecast.archive import write_capture
from vp.forecast.evidence import Evidence
from vp.signals import registry
from vp.signals.gates import _market
from vp.sources.openfootball import rows
from vp.strategy.spec import Spec, render, validate

LIGA = Domain(
    name="testliga",
    tag_ids=("999",),
    tag_labels=("Test Liga",),
    keywords=("Test Liga",),
    exclude=(),
    parse=EPL.parse,
    title="Test Liga",
    summary="Matches in a league that exists only in this test.",
    kinds=dict(EPL.kinds),
    props=EPL.props,
    home_first=True,
    openfootball="xx.1",
    zone="Europe/Madrid",
)


@pytest.fixture
def liga(monkeypatch):
    monkeypatch.setitem(DOMAINS, LIGA.name, LIGA)
    return LIGA


def test_a_new_domain_needs_only_its_adapter(liga, tmp_path) -> None:
    spec = Spec.model_validate(
        {
            "name": "Liga favourites",
            "selector": {"domains": [liga.name], "kinds": ["match"]},
            "belief": {"forecaster": "signal:elo"},
        }
    )
    assert validate(spec) == [] and "Test Liga" in " ".join(render(spec))
    market = _market(
        domain=liga.name,
        parsed={"kind": "match", "team_a": "A CF", "team_b": "B CF", "side": "A CF"},
    )
    applying = {s for s in registry.ids() if registry.load(s).meta.applies(market)}
    assert {"elo", "glicko2", "bradley_terry", "poisson", "dixon_coles"} <= applying
    data = {
        "name": "Test Liga 2025/26",
        "matches": [
            {
                "date": "2025-08-16",
                "time": "21:00",
                "team1": "A CF",
                "team2": "B CF",
                "score": {"ft": [3, 1]},
            }
        ],
    }
    write_capture(
        tmp_path,
        "openfootball",
        rows(data, liga.name, liga.zone),
        provenance={},
        now=datetime(2026, 9, 1, tzinfo=UTC),
    )
    (top, _) = Evidence(datetime(2025, 9, 1, tzinfo=UTC), tmp_path).table(liga.name)
    assert (top.team, top.points) == ("a", 3)  # club suffix dropped
