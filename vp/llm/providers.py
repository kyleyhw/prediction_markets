"""The providers a person can pick, and the free demo's country rule.

A preset names a provider, the kind of API it speaks and its address, so
a person picks "Groq" and types a model name rather than a URL. Model
names are typed, never listed here: providers add models every week
(docs/models.md). Addresses are each provider's documented
OpenAI-compatible base.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Provider:
    id: str
    label: str
    kind: str  # anthropic | gemini | openai | command
    base_url: str | None = None  # None: the person (or the copy) gives it
    needs_key: bool = True
    own_copy_only: bool = False  # local addresses or programs: never hosted


PROVIDERS: dict[str, Provider] = {
    p.id: p
    for p in (
        Provider("anthropic", "Anthropic (Claude)", "anthropic"),
        Provider("gemini", "Google Gemini", "gemini"),
        Provider("openai", "OpenAI", "openai", "https://api.openai.com/v1"),
        Provider("openrouter", "OpenRouter", "openai", "https://openrouter.ai/api/v1"),
        Provider("groq", "Groq", "openai", "https://api.groq.com/openai/v1"),
        Provider("mistral", "Mistral", "openai", "https://api.mistral.ai/v1"),
        Provider("deepseek", "DeepSeek", "openai", "https://api.deepseek.com/v1"),
        Provider("together", "Together AI", "openai", "https://api.together.xyz/v1"),
        Provider("xai", "xAI", "openai", "https://api.x.ai/v1"),
        Provider(
            "ollama",
            "Ollama, on your computer",
            "openai",
            "http://localhost:11434/v1",
            needs_key=False,
            own_copy_only=True,
        ),
        Provider("custom", "Another OpenAI-compatible address", "openai", None, False),
        Provider(
            "command",
            "A program of your own",
            "command",
            None,
            False,
            own_copy_only=True,
        ),
    )
}

#: Where the free demo may be offered: the countries Google lists for the
#: Gemini API (ai.google.dev/gemini-api/docs/available-regions, read
#: 2026-10-13), less those whose users Google's terms let an app serve only
#: on paid services: the EEA (with the EU's outermost regions that have
#: their own codes), Switzerland and the United Kingdom. Gibraltar and the
#: Crown Dependencies (Guernsey, Jersey, the Isle of Man) are left out as
#: well: their data law follows the UK's, and doubt counts against.
FREE_TIER_COUNTRIES: frozenset[str] = frozenset(
    """AD AE AG AI AL AM AO AQ AR AS AU AW AZ BA BB BD BF BH BI BJ BL BM BN BO
    BQ BR BS BT BW BZ CA CC CD CF CG CI CK CL CM CO CR CV CW CX DJ DM DO DZ EC
    EG EH ER ET FJ FK FM FO GA GD GE GH GL GM GN GQ GS GT GU GW GY HM HN HT ID
    IL IN IO IQ JM JO JP KE KG KH KI KM KN KR KW KY KZ LA LB LC LK LR LS LY MA
    MC MD ME MG MH MK ML MN MP MR MS MU MV MW MX MY MZ NA NC NE NF NG NI NP NR
    NU NZ OM PA PE PG PH PK PM PN PR PS PW PY QA RS RW SA SB SC SD SG SH SL SM
    SN SO SR SS ST SV SZ TC TD TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM
    US UY UZ VA VC VE VG VI VN VU WF WS XK YE ZA ZM ZW""".split()
)


#: Where Google's terms let an app serve people only on paid services: the
#: EEA (with the EU's outermost regions), Switzerland, the United Kingdom,
#: and, by the same doubt as above, Gibraltar and the Crown Dependencies.
#: Used only to say why the demo is refused (docs/models.md).
PAID_ONLY_COUNTRIES: frozenset[str] = frozenset(
    """AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI
    ES SE IS LI NO GF RE AX MQ GP YT MF CH GB GI GG JE IM""".split()
)


def key_from_environment(provider: str) -> str | None:
    """A provider's key from the environment, under the name its own tools
    use (``GEMINI_API_KEY``, ``GROQ_API_KEY``...), for the command line.
    The platform never calls this: it passes the key it read in config."""
    return os.environ.get(f"{provider.upper()}_API_KEY") or None
