"""English Premier League markets.

Question forms observed live in September 2026 (current) and from 2024
(the oldest under the tag). A match is an event titled ``A vs. B`` (home side
first, club suffixes such as ``FC`` kept) with three Yes/No markets:

* ``Will Arsenal FC win on 2026-09-19?`` (current), ``Will PSG win against
  Barcelona?`` and ``Will Liverpool beat Tottenham?`` (2024)
* ``Will Brighton & Hove Albion FC vs. Arsenal FC end in a draw?``,
  ``Will PSG vs Barcelona be a draw?``, ``Will the match between Tottenham
  and Liverpool end in a draw?``

Season winner: ``Will Arsenal win the 2026-27 English Premier League (EPL)
Championship?`` (current) and ``Will Man City win the Premier League?``
(2024, no season in the question). Runner-up, top-scorer, relegation and
manager questions are members without structured fields.

Two Gamma tags carry the league: ``306`` (EPL) and ``82`` (Premier League);
current match events carry both. Tag 306 was also applied in 2024 to
Champions League and Europa League events involving English clubs, and the
current "qualify for the UEFA Champions League" markets are under tag 82, so
those competitions and the domestic cups are excluded: the domain is the
league itself.
"""

from __future__ import annotations

import re

from vp.domains.base import Domain

_SEASON = re.compile(
    r"^Will (?P<team>.+?) win the (?:(?P<season>\d{4}[–-]\d{2,4}) )?(?:English )?"
    r"Premier League(?: \(EPL\))?(?: Championship)?\?$",
    re.IGNORECASE,
)
_FIXTURE = re.compile(r"^(?P<a>[^?]+?)\s+vs\.?\s+(?P<b>[^?]+?)\s*$", re.IGNORECASE)
_SIDE = re.compile(
    r"^Will (?P<team>.+?) (?:win on (?P<date>\d{4}-\d{2}-\d{2})|win against .+"
    r"|beat .+|win)\?$",
    re.IGNORECASE,
)
_DRAW = re.compile(
    r"^Will (?:the match between (?P<a1>.+?) and (?P<b1>.+?)|(?P<a2>.+?) vs\.? "
    r"(?P<b2>.+?)|the match) (?:end in|be) a draw\?$",
    re.IGNORECASE,
)


def parse(question: str, event_title: str | None) -> dict[str, str] | None:
    """Read an EPL question into ``kind`` plus its fields, or ``None``."""
    text = question.strip()
    if m := _SEASON.match(text):
        return {
            "kind": "season_winner",
            "team": m["team"],
            "season": m["season"] or "",
        }
    side = _SIDE.match(text)
    draw = None if side else _DRAW.match(text)
    if side is None and draw is None:
        return None
    teams = _FIXTURE.match((event_title or "").strip())
    if teams:
        team_a, team_b = teams["a"], teams["b"]
    elif draw and (draw["a1"] or draw["a2"]):
        team_a, team_b = draw["a1"] or draw["a2"], draw["b1"] or draw["b2"]
    else:
        return None
    fields = {"kind": "match", "team_a": team_a, "team_b": team_b}
    if side:
        fields["side"] = side["team"]
        if side["date"]:
            fields["date"] = side["date"]
    else:
        fields["side"] = "draw"
    return fields


EPL = Domain(
    name="epl",
    title="Premier League",
    summary="English football: match results and the title race.",
    tag_ids=("306", "82"),
    tag_labels=("epl", "premier league"),
    keywords=("premier league", "epl "),
    exclude=(
        "fantasy",
        "champions league",
        "europa league",
        "conference league",
        "carabao",
        "efl cup",
        "fa cup",
        "community shield",
        "women's super league",
        " wfc",
    ),
    parse=parse,
)
