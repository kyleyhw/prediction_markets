"""The number gate: the assistant may state no figure that is not in its data.

A research assistant that makes up a number is worse than none, because a
person cannot tell an invented figure from a measured one. So every figure
in a draft (integers, decimals, percentages, money, cents, with thousands
separators) must match a number in the turn's tool results or in the
person's own words, allowing the same number rounded to the precision
shown, or moved between a fraction and a percentage (0.614 shown as 61%) or
between dollars and cents (0.62 shown as 62¢). A list marker at the start
of a line is not a figure. What fails is named, so the draft can be
regenerated once with the failures pointed out, and released after that
with each failing figure replaced by a pointer to the data
(docs/strategies.md, the number gate).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

# A number not glued to a word, a path or an identifier (so `map_1`,
# `claude-opus-5`, `4ee13a8` and `v2` are not figures), with an optional
# sign, dollar sign, thousands separators, decimals and a % or ¢ unit.
_FIGURE = re.compile(
    r"(?<![\w.\-/#])(?P<sign>[-−])?(?P<usd>\$)?"
    r"(?P<int>\d{1,3}(?:,\d{3})+|\d+)(?P<frac>\.\d+)?(?P<unit>%|¢)?(?![\w¢%])"
)
_LIST_MARKER = re.compile(r"^[ \t]*(\d+)[.)]\s", re.M)
# A date is its year as far as figures go: its month and day are not counts
# a draft may borrow ("won 1 match" is not licensed by 2026-03-01).
_DATE = re.compile(
    r"\b(\d{4})-\d{2}-\d{2}"
    r"(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?"
)
# A minus sign right after a digit is a separator, not a sign.
_ANY_NUMBER = re.compile(r"(?<![\d.])[-−]?\d[\d,]*(?:\.\d+)?")

#: What replaces a figure that failed twice.
POINTER = "(see the data)"


@dataclass(frozen=True)
class Figure:
    text: str
    value: float
    decimals: int
    unit: str  # "", "%", "¢" or "$"
    start: int
    end: int


def figures(text: str) -> list[Figure]:
    """The figures in a text, in order."""
    markers = {m.start(1) for m in _LIST_MARKER.finditer(text)}
    out = []
    for m in _FIGURE.finditer(text):
        if m.start() in markers:
            continue
        digits = m["int"].replace(",", "") + (m["frac"] or "")
        value = float(digits) * (-1 if m["sign"] else 1)
        unit = m["unit"] or ("$" if m["usd"] else "")
        out.append(
            Figure(
                m.group(0),
                value,
                len(m["frac"] or "") - 1 if m["frac"] else 0,
                unit,
                m.start(),
                m.end(),
            )
        )
    return out


def numbers(sources: Iterable[str]) -> set[float]:
    """Every number written in the sources."""
    found = set()
    for text in sources:
        for raw in _ANY_NUMBER.findall(_DATE.sub(r"\1", text)):
            try:
                found.add(float(raw.replace(",", "").replace("−", "-")))
            except ValueError:
                continue
    return found


def _matches(f: Figure, allowed: set[float]) -> bool:
    # The figure as written, and as a fraction (61% of 0.614, 62¢ of 0.62),
    # each with the number of decimal places it was shown to.
    candidates = [(f.value, f.decimals)]
    if f.unit in ("%", "¢", ""):
        candidates.append((f.value / 100, f.decimals + 2))
    for y in allowed:
        for x, places in candidates:
            if abs(y - x) < 1e-9 or abs(round(y, places) - x) < 1e-9:
                return True
    return False


def check(text: str, sources: Iterable[str]) -> list[Figure]:
    """The figures in ``text`` found in none of the sources."""
    allowed = numbers(sources)
    return [f for f in figures(text) if not _matches(f, allowed)]


def redact(text: str, failing: list[Figure]) -> str:
    """The text with each failing figure replaced by the pointer."""
    for f in sorted(failing, key=lambda f: f.start, reverse=True):
        text = text[: f.start] + POINTER + text[f.end :]
    return text
