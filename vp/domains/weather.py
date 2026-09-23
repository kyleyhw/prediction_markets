"""Weather markets.

Question forms observed in the archived December 2025 reports:

* daily temperature bucket: ``Will the highest temperature in London be
  between 54-55°F on December 7?``, ``... be 53°F or below on December 7?``,
  ``... be 62°F or higher on December 8?``, and the one-degree form seen
  live in September 2026, ``Will the highest temperature in Cape Town be
  17°C on September 12?``, which is the bucket ``[17, 17]``. A range may use
  an en dash or drop the word "between" (``be 64–65°F on December 4?``). Of
  131,285 resolved daily-temperature questions seen in September 2026, all
  but 23 parse; the 23 are malformed early-2025 forms (``be between 42°F
  and 43°F``, a missing "be") not worth a pattern.
* record rank: ``Will 2025 be the hottest year on record?``,
  ``Will November 2025 be the 1st hottest on record?``,
  ``Will 2026 rank as the sixth-hottest year on record or lower?``
* global anomaly: ``Will global temperature increase by between 1.10ºC and
  1.14ºC in November 2025?``

The daily buckets are the most useful for a forecaster because they resolve
within days against a named station's observation; a bucket is stored as an
inclusive low and high in the question's unit, with an open end left empty.
The Gamma tag id measured live is ``84`` (Weather), which every daily
temperature event carries alongside ``103040`` (Daily Temperature) and a city
tag; record-rank events carry ``832`` (Global Temp) and ``87`` (climate). The
exclusion list is the archived one: keywords such as "Rain" and "Golden" pull
in sports teams.
"""

from __future__ import annotations

import re

from vp.domains.base import Domain

_DAILY = re.compile(
    r"^Will the (?P<stat>highest|lowest) temperature in (?P<city>.+?) be "
    r"(?P<bucket>.+?) on (?P<date>.+?)\?$",
    re.IGNORECASE,
)
_BETWEEN = re.compile(
    r"^(?:between )?(?P<lo>-?\d+(?:\.\d+)?)\s*[-–]\s*(?P<hi>-?\d+(?:\.\d+)?)"
    r"\s*(?P<unit>°[CF])$"
)
_BELOW = re.compile(r"^(?P<hi>-?\d+(?:\.\d+)?)\s*(?P<unit>°[CF]) or below$")
_ABOVE = re.compile(r"^(?P<lo>-?\d+(?:\.\d+)?)\s*(?P<unit>°[CF]) or higher$")
_EXACT = re.compile(r"^(?P<v>-?\d+(?:\.\d+)?)\s*(?P<unit>°[CF])$")
_RECORD = re.compile(
    r"^Will (?P<period>.+?) (?:be|rank as) the (?:(?P<rank>\S+?)[- ])?hottest"
    r"(?: (?:year|month))? on record(?P<tail> or lower)?\?$",
    re.IGNORECASE,
)
_ANOMALY = re.compile(
    r"^Will global temperature increase by (?P<bucket>.+?) in (?P<period>.+?)\?$",
    re.IGNORECASE,
)


def _bucket(text: str) -> dict[str, str] | None:
    text = text.strip()
    if m := _BETWEEN.match(text):
        return {"low": m["lo"], "high": m["hi"], "unit": m["unit"]}
    if m := _BELOW.match(text):
        return {"low": "", "high": m["hi"], "unit": m["unit"]}
    if m := _ABOVE.match(text):
        return {"low": m["lo"], "high": "", "unit": m["unit"]}
    if m := _EXACT.match(text):
        return {"low": m["v"], "high": m["v"], "unit": m["unit"]}
    return None


def parse(question: str, event_title: str | None) -> dict[str, str] | None:
    """Read a weather question into ``kind`` plus its fields, or ``None``."""
    text = question.strip()
    if m := _DAILY.match(text):
        bucket = _bucket(m["bucket"])
        if bucket is None:
            return None
        return {
            "kind": "daily_temperature",
            "statistic": m["stat"].lower(),
            "city": m["city"],
            "date": m["date"],
            **bucket,
        }
    if m := _RECORD.match(text):
        return {
            "kind": "record_rank",
            "period": m["period"],
            "rank": m["rank"] or "1st",
            "or_lower": "true" if m["tail"] else "false",
        }
    if m := _ANOMALY.match(text):
        return {"kind": "global_anomaly", "bucket": m["bucket"], "period": m["period"]}
    return None


WEATHER = Domain(
    name="weather",
    title="Weather",
    summary="How hot it gets: daily highs in cities and global temperature records.",
    tag_ids=("84",),
    tag_labels=(
        "weather",
        "climate & weather",
        "climate change",
        "temperature",
        "daily temperature",
        "highest temperature",
        "lowest temperature",
        "global temp",
    ),
    keywords=(
        "temperature in",
        "hottest",
        "coldest",
        "global temperature",
        "hurricane",
        "rainfall",
        "snowfall",
    ),
    exclude=(
        "vs.",
        "miami heat",
        "carolina hurricanes",
        "golden state",
        "rainbow warriors",
        "hockey",
        "football",
        "ncaa",
        "spread",
        "over/under",
    ),
    parse=parse,
    kinds={
        "daily_temperature": ("statistic", "city", "date", "low", "high", "unit"),
        "record_rank": ("period", "rank", "or_lower"),
        "global_anomaly": ("bucket", "period"),
    },
)
