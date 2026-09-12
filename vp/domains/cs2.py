"""Counter-Strike 2 markets.

Question forms observed in the archived December 2025 reports:

* match, as the event title: ``Counter-Strike: Spirit vs Team Falcons (BO3)``
* tournament winner: ``Will FURIA win the StarLadder Budapest Major 2025?``

Tag labels ``cs2``, ``counter strike 2`` and ``Esports`` exist on the venue;
their ids were not recorded by the archived project, so listing by tag is
left empty until measured, and discovery relies on keyword search. The
keyword ``Major`` from the archived config is dropped because it matched
"major ground offensive" questions.
"""

from __future__ import annotations

import re

from vp.domains.base import Domain

_MATCH = re.compile(
    r"^(?:Counter-Strike:\s*)?(?P<a>.+?)\s+vs\.?\s+(?P<b>.+?)"
    r"(?:\s*\((?P<fmt>BO\d)\))?\s*$",
    re.IGNORECASE,
)
_TOURNAMENT = re.compile(
    r"^Will (?P<team>.+?) win (?:the )?(?P<tournament>.+?)\?$", re.IGNORECASE
)


def parse(question: str, event_title: str | None) -> dict[str, str] | None:
    """Read a CS2 question into ``kind`` plus its fields, or ``None``."""
    for text in (question, event_title or ""):
        match = _MATCH.match(text.strip())
        if match:
            fields = {"kind": "match", "team_a": match["a"], "team_b": match["b"]}
            if match["fmt"]:
                fields["format"] = match["fmt"].upper()
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
    tag_ids=(),
    tag_labels=("cs2", "counter strike 2", "counter-strike", "esports"),
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
    exclude=("simulator", "skin", "case opening"),
    parse=parse,
)
