"""Prop markets: the side bets a match event carries besides its result.

The venue labels each sports market with a type (``sportsMarketType``);
the question forms below were read from the Premier League and
Counter-Strike events on 2026-09-23 (``tests/fixtures/props.json`` keeps
them with the venue's label, and the tests check the two agree):

* totals: ``A vs. B: O/U 2.5``, ``A vs. B: 1st Half O/U 0.5``,
  ``A vs. B: O/U 7.5 Total Corners``, ``Games Total: O/U 2.5``,
  ``Map 1 Total Rounds: Over/Under 18.5``
* team totals: ``A vs. B: A O/U 0.5``, ``A vs. B: A 2nd Half O/U 0.5``,
  ``A vs. B: A O/U 2.5 Corners``
* spreads and handicaps: ``Spread: A (-1.5)``, ``1st Half Spread: A
  (-2.5)``, ``Map Handicap: PLD (-1.5) vs your end (+1.5)`` (``Map
  Handicap: MOUZ (-1.5)`` before 2026), ``Map 1 Rounds Handicap: A (-6.5)
  vs B (+6.5)``, and ``Total Rounds Over/Under 52.5`` for a whole series
* ``Exact Score: A 0 - 0 B?``, ``1st Half Exact Score: Any Other Score?``
* ``A leading at halftime?``, ``A vs. B: Draw at halftime?``,
  ``A to win the second half?``, ``A vs. B: Second half draw?``
* ``A vs. B: Both Teams to Score in First Half``
* ``Benjamin Sesko: Anytime Goalscorer``
* ``A to score first in the 1st half vs. B?``, ``A vs. B: Neither team to
  score first?``
* ``A vs. B: Total Corners Odd or Even?``, ``Map 1: Odd/Even Total Kills?``,
  ``A vs. B: Team to Take First Corner``

Each is read into a kind and fields: ``period`` (``full``, ``1st_half``,
``2nd_half``, ``map_N``), ``stat`` (``goals``, ``corners``, ``maps``,
``rounds``, ``kills``), ``line``, ``team``, ``score``, ``player``, and the
fixture's ``team_a`` and ``team_b`` from the event title. The first outcome
is the event forecast, as everywhere: ``Over``, ``Odd``, ``Yes``, or the
team named first in a spread or handicap.
"""

from __future__ import annotations

import re

#: Every prop kind with the fields it carries besides ``kind``.
PROP_KINDS: dict[str, tuple[str, ...]] = {
    "total": ("team_a", "team_b", "period", "stat", "line"),
    "team_total": ("team_a", "team_b", "period", "stat", "line", "team"),
    "spread": ("team_a", "team_b", "period", "stat", "line", "team"),
    "exact_score": ("team_a", "team_b", "period", "score"),
    "halftime_result": ("team_a", "team_b", "team"),
    "second_half_result": ("team_a", "team_b", "team"),
    "both_teams_to_score": ("team_a", "team_b", "period"),
    "anytime_scorer": ("team_a", "team_b", "player"),
    "first_to_score": ("team_a", "team_b", "period", "team"),
    "first_corner": ("team_a", "team_b"),
    "odd_even": ("team_a", "team_b", "period", "stat"),
}

_FIXTURE = re.compile(
    r"^(?:[^:]*?:\s*)?(?P<a>.+?)\s+vs\.?\s+(?P<b>.+?)(?:\s*\(BO\d\))?(?:\s+-\s+.*)?$",
    re.IGNORECASE,
)
_NUM = r"(?P<line>[+-]?\d+(?:\.\d+)?)"
_HALF = {"1st half": "1st_half", "first half": "1st_half", "2nd half": "2nd_half"}
_HALF["second half"] = "2nd_half"


def _period(text: str | None) -> str:
    return _HALF.get((text or "").strip().lower(), "full")


def _fixture(title: str | None) -> dict[str, str]:
    m = _FIXTURE.match((title or "").strip())
    return {"team_a": m["a"], "team_b": m["b"]} if m else {}


# Each pattern is tried in order on the question; the first match wins.
_FORMS: list[tuple[str, re.Pattern[str]]] = [
    (
        "exact_score",
        re.compile(
            r"^(?P<half>1st Half )?Exact Score: (?:Any Other Score|.+? (?P<sa>\d+)"
            r" - (?P<sb>\d+) .+?)\?$",
            re.I,
        ),
    ),
    (
        "spread",
        re.compile(
            r"^(?:(?P<half>1st Half|2nd Half) )?Spread: (?P<team>.+?) \("
            + _NUM
            + r"\)$",
            re.I,
        ),
    ),
    (
        "spread",
        re.compile(
            r"^(?:Map (?P<map>\d+) (?P<rounds>Rounds) |Map )Handicap: (?P<team>.+?) \("
            + _NUM
            + r"\)(?: vs .+)?$",
            re.I,
        ),
    ),
    (
        "total",
        re.compile(r"^Map (?P<map>\d+) Total Rounds: Over/Under " + _NUM + r"$", re.I),
    ),
    ("total", re.compile(r"^Games Total: O/U " + _NUM + r"$", re.I)),
    (
        "total",
        re.compile(r"^Total (?P<rounds>Rounds) Over/Under " + _NUM + r"$", re.I),
    ),
    (
        "odd_even",
        re.compile(
            r"^Map (?P<map>\d+): Odd/Even Total (?P<stat>Kills|Rounds)\?$", re.I
        ),
    ),
    (
        "odd_even",
        re.compile(r"^.+?: Total (?P<stat>Corners) Odd or Even\?$", re.I),
    ),
    ("first_corner", re.compile(r"^.+?: Team to Take First Corner$", re.I)),
    (
        "both_teams_to_score",
        re.compile(
            r"^.+?: Both Teams to Score(?: in (?P<half>First Half|Second Half))?$", re.I
        ),
    ),
    ("anytime_scorer", re.compile(r"^(?P<player>[^:]+): Anytime Goalscorer$", re.I)),
    (
        "halftime_result",
        re.compile(
            r"^(?:(?P<team>.+?) leading at halftime"
            r"|.+?: (?P<draw>Draw) at halftime)\?$",
            re.I,
        ),
    ),
    (
        "second_half_result",
        re.compile(
            r"^(?:(?P<team>.+?) to win the second half"
            r"|.+?: Second half (?P<draw>draw))\?$",
            re.I,
        ),
    ),
    (
        "first_to_score",
        re.compile(
            r"^(?:.+?: (?P<neither>Neither) team to score first"
            r"|(?P<team>.+?) to score first)"
            r"(?: in the (?P<half>1st half|2nd half))?(?: vs\. .+?)?\?$",
            re.I,
        ),
    ),
    (
        "team_total",
        re.compile(
            r"^(?P<a>.+?) vs\. (?P<b>.+?): (?P<team>.+?) "
            r"(?:(?P<half>1st Half|2nd Half) )?"
            r"O/U " + _NUM + r"(?P<corners> Corners)?$",
            re.I,
        ),
    ),
    (
        "total",
        re.compile(
            r"^.+?: (?:(?P<half>1st Half|2nd Half) )?O/U "
            + _NUM
            + r"(?P<corners> Total Corners)?$",
            re.I,
        ),
    ),
]


def parse(question: str, event_title: str | None) -> dict[str, str] | None:
    """Read a prop question into ``kind`` plus its fields, or ``None``."""
    text = question.strip()
    for kind, pattern in _FORMS:
        m = pattern.match(text)
        if m is None:
            continue
        g = {k: v for k, v in m.groupdict().items() if v is not None}
        fields = {"kind": kind, **_fixture(event_title)}
        if kind == "team_total" and g["team"] not in (g["a"], g["b"]):
            continue  # "A vs. B: O/U 2.5" read as a team called "A vs. B"
        if "map" in g:
            fields["period"] = f"map_{g['map']}"
        elif kind in (
            "halftime_result",
            "second_half_result",
            "first_corner",
            "anytime_scorer",
        ):
            pass
        else:
            fields["period"] = _period(g.get("half"))
        if "line" in g:
            fields["line"] = g["line"].lstrip("+")
        if kind in ("total", "team_total", "spread", "odd_even"):
            if "corners" in g or g.get("stat", "").lower() == "corners":
                fields["stat"] = "corners"
            elif (
                "rounds" in g
                or g.get("stat", "").lower() == "rounds"
                or (kind == "total" and "map" in g)
            ):
                fields["stat"] = "rounds"
            elif g.get("stat", "").lower() == "kills":
                fields["stat"] = "kills"
            elif text.lower().startswith(("games total", "map handicap")):
                fields["stat"] = "maps"
            else:
                fields["stat"] = "goals"
        if kind == "exact_score":
            fields["score"] = f"{g['sa']}-{g['sb']}" if "sa" in g else "other"
        if "team" in g:
            fields["team"] = g["team"]
        elif "draw" in g:
            fields["team"] = "draw"
        elif "neither" in g:
            fields["team"] = "neither"
        if "player" in g:
            fields["player"] = g["player"]
        return fields
    return None
