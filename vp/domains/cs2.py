"""Counter-Strike 2 markets.

Question forms observed live (September 2026) and in the archived December
2025 reports. The match-winner market's question equals its event title:

* ``Counter-Strike: Spirit vs Team Falcons (BO3)``
* ``Counter-Strike: Rare Atom vs DEPO (BO3) - Asia Championships Closed
  Qualifier Playoffs`` (a stage after the dash)
* ``ESL Counter-Strike Quarterfinals: G2 vs Liquid`` (the stage before the
  colon, 2024 form) and ``CS: Sashi vs HOTU``
* per-map winner: ``Counter-Strike: G2 vs Legacy - Map 1 Winner``
* tournament winner: ``Will FURIA win the StarLadder Budapest Major 2025?``,
  ``Will M80 win ESL Challenger Atlanta 2024?``

A match event also carries props (``Games Total: O/U 2.5``, ``Map Handicap:
INF (-1.5) vs against All authority (+1.5)``, ``Map 1: Odd/Even Total
Kills?``). They are binary and stay in the domain, but they are not
match-winner contracts, so the parser reads the question only, never the
event title, and returns ``None`` for them. The outcome names of a match
market are the venue's short team names (``NaVi``, ``EF``) and can be
truncated, so the parsed names from the question are the ones to use.

Gamma tag ids measured live: ``100677`` (CS2), ``100780`` (counter strike 2),
``100602`` (counter-strike); ``104507`` (``Counter stike 2``, a venue typo) and
``100635`` (csgo) also occur. ``64`` (Esports) is too broad to list or admit
by. The keyword ``Major`` from the archived config is dropped because it
matched "major ground offensive" questions.
"""

from __future__ import annotations

import re

from vp.domains.base import Domain

_MATCH = re.compile(
    r"^(?:(?P<prefix>[^:]*?):\s*)?(?P<a>.+?)\s+vs\.?\s+(?P<b>.+?)"
    r"(?:\s*\((?P<fmt>BO\d)\))?(?:\s*-\s*(?P<suffix>.+?))?\s*$",
    re.IGNORECASE,
)
_MAP = re.compile(r"^Map (?P<n>\d+) Winner$", re.IGNORECASE)
_PROP = re.compile(r"handicap|total|odd|even|spread", re.IGNORECASE)
_FORMAT = re.compile(r"\((BO\d)\)", re.IGNORECASE)
_TOURNAMENT = re.compile(
    r"^Will (?P<team>.+?) win (?:the )?(?!an? |any )(?P<tournament>.+?)\?$",
    re.IGNORECASE,
)


def parse(question: str, event_title: str | None) -> dict[str, str] | None:
    """Read a CS2 question into ``kind`` plus its fields, or ``None``."""
    match = _MATCH.match(question.strip())
    if match and not _PROP.search(match["prefix"] or ""):
        fields = {"kind": "match", "team_a": match["a"], "team_b": match["b"]}
        fmt = match["fmt"] or ((m := _FORMAT.search(event_title or "")) and m.group(1))
        if fmt:
            fields["format"] = fmt.upper()
        if suffix := match["suffix"]:
            if map_ := _MAP.match(suffix):
                fields["map"] = map_["n"]
            else:
                fields["stage"] = suffix
        return fields
    match = _TOURNAMENT.match(question.strip())
    if match:
        return {
            "kind": "tournament_winner",
            "team": match["team"],
            "tournament": match["tournament"],
        }
    return None


CS2 = Domain(
    name="cs2",
    title="Counter-Strike 2",
    summary="Esports: who wins Counter-Strike matches and tournaments.",
    tag_ids=("100677", "100780", "100602"),
    tag_labels=("cs2", "counter strike 2", "counter-strike", "counter stike 2", "csgo"),
    keywords=(
        "counter-strike",
        "counter strike",
        "cs2",
        "cs:go",
        "iem ",
        "esl pro league",
        "blast premier",
        "blast rivals",
        "pgl ",
        "starladder",
    ),
    # Dota 2 series share tournament names and team names (found in the
    # resolved set, 2026-09-23).
    exclude=("simulator", "skin", "case opening", "dota"),
    parse=parse,
    kinds={
        "match": ("team_a", "team_b", "format", "map", "stage"),
        "tournament_winner": ("team", "tournament"),
    },
    props=("total", "spread", "odd_even"),
)
