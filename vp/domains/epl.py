"""English Premier League markets.

The archived project recorded the Gamma tag id ``306`` for the Premier League
(and ``100350`` for Soccer, which is too broad to list by). No EPL question
strings were captured, so the parsers follow the forms seen for sibling
leagues and for matches generally:

* season winner, by analogy with ``Will Union Berlin win the 2025–26
  Bundesliga?``: ``Will Arsenal win the 2025–26 Premier League?``
* match, as an event title: ``Arsenal vs Chelsea``; the per-side questions
  under such an event are expected to read ``Will Arsenal win?`` or name a
  draw. These forms are unverified until the first live run and the parser
  returns ``None`` rather than guess on anything else.
"""

from __future__ import annotations

import re

from vp.domains.base import Domain

_SEASON = re.compile(
    r"^Will (?P<team>.+?) win the (?P<season>\d{4}[–-]\d{2,4}) (?:English )?"
    r"Premier League\?$",
    re.IGNORECASE,
)
_MATCH = re.compile(r"^(?P<a>[^?]+?)\s+vs\.?\s+(?P<b>[^?]+?)\s*$", re.IGNORECASE)
_SIDE = re.compile(r"^Will (?P<team>.+?) win\?$", re.IGNORECASE)
_DRAW = re.compile(r"draw", re.IGNORECASE)


def parse(question: str, event_title: str | None) -> dict[str, str] | None:
    """Read an EPL question into ``kind`` plus its fields, or ``None``."""
    text = question.strip()
    if m := _SEASON.match(text):
        return {"kind": "season_winner", "team": m["team"], "season": m["season"]}
    teams = _MATCH.match((event_title or "").strip()) or _MATCH.match(text)
    if teams:
        fields = {"kind": "match", "team_a": teams["a"], "team_b": teams["b"]}
        if side := _SIDE.match(text):
            fields["side"] = side["team"]
        elif _DRAW.search(text):
            fields["side"] = "draw"
        return fields
    return None


EPL = Domain(
    name="epl",
    tag_ids=("306",),
    tag_labels=("epl", "premier league"),
    keywords=("premier league", "epl "),
    exclude=("fantasy",),
    parse=parse,
)
